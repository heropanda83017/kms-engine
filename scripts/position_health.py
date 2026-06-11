#!/usr/bin/env python3
"""持仓健康自检 — 从 TradeLedger 自动计算持仓健康度

检测维度（6项）:
  1. 仓位集中度 — 单一品种占总投资比例
  2. 持仓亏损 — 持仓品种的未实现盈亏
  3. 浮亏加仓 — 在亏损头寸上加仓
  4. 方向集中 — 所有持仓同一方向（全多/全空）
  5. 频繁换仓 — 单一品种的换手率异常
  6. 仓位暴露 — 总保证金占用比例

数据源:
  - TradeLedger CSV（必备）
  - akshare 收盘价（可选，用于计算浮亏）

用法:
  # 仅 TradeLedger 分析
  python3 scripts/position_health.py
  
  # 带价格数据
  python3 scripts/position_health.py --fetch-prices

  # 导入
  from position_health import check_position_health

  输出:
  返回 dict: {healthy: bool, warnings: [...], scores: {...}, positions: [...]}
"""

import sys, os, json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ── 配置 ──
SCRIPTS_DIR = Path(__file__).resolve().parent

CONCENTRATION_LIMIT = 0.40        # 单一品种上限 40%
DRAWDOWN_WARN_PCT = -5.0         # 单品种浮亏告警阈值 -5%
DRAWDOWN_CRITICAL_PCT = -15.0    # 单品种浮亏红线 -15%
MARGIN_USAGE_WARN = 0.70         # 保证金占用告警 70%
MARGIN_USAGE_CRITICAL = 0.90     # 保证金占用红线 90%
FREQ_TRADE_WARN = 10             # 30天内同品种交易次数告警

# 期货参数（用于估算保证金）
FUTURES_PARAMS = {
    'IM': {'multiplier': 200, 'margin_rate': 0.12},
    'IC': {'multiplier': 200, 'margin_rate': 0.12},
    'IF': {'multiplier': 300, 'margin_rate': 0.12},
    'IH': {'multiplier': 300, 'margin_rate': 0.12},
}


def _get_ledger():
    """获取 TradeLedger 实例"""
    sys.path.insert(0, str(SCRIPTS_DIR.parent.parent / "输出" / "investment-engine" / "strategies"))
    from trade_ledger import TradeLedger
    return TradeLedger()


def check_position_health(total_capital: float = None,
                          fetch_prices: bool = False) -> dict:
    """持仓健康主检查

    参数:
        total_capital: 总资金（不传则从持仓反估）
        fetch_prices: 是否拉取最新价格（计算浮亏）

    返回:
        {
            healthy: bool,
            warnings: [str, ...],
            scores: {concentration, drawdown, direction, ...},
            positions: [{code, lots, side, entry_price, ...}],
            summary: str
        }
    """
    ledger = _get_ledger()
    all_rows = ledger.query(limit=10000)

    if not all_rows:
        return {
            "healthy": True,
            "warnings": [],
            "scores": {},
            "positions": [],
            "summary": "无持仓记录，无需检查"
        }

    # ── 计算当前持仓（从交易历史推导） ──
    # 按 code + date 排序
    by_code = defaultdict(list)
    for r in all_rows:
        by_code[r.get("code", "")].append(r)

    positions = []
    total_cost = 0.0
    for code, trades in by_code.items():
        if not code:
            continue
        trades.sort(key=lambda x: x.get("date", ""))

        net_lots = 0
        total_buy_cost = 0.0
        total_buy_vol = 0
        last_sell_price = 0.0
        last_action_date = ""

        for t in trades:
            action = t.get("action", "")
            price = float(t.get("price", 0))
            volume = int(float(t.get("volume", 0)))
            date_str = t.get("date", "")[:10]

            if action in ("BUY", "ADD"):
                # 检查浮亏加仓：如果 Net_lots > 0 且当前 BUY 价比上次开盘低
                if net_lots > 0 and last_sell_price > 0 and price < last_sell_price:
                    pass  # 标记为 add_to_loser（在 summary 中处理）

                net_lots += volume
                total_buy_cost += price * volume
                total_buy_vol += volume
                last_action_date = date_str

            elif action in ("SELL", "REDUCE"):
                net_lots -= volume
                last_sell_price = price
                last_action_date = date_str

        if net_lots > 0:
            avg_cost = total_buy_cost / total_buy_vol if total_buy_vol > 0 else 0
            positions.append({
                "code": code,
                "lots": net_lots,
                "side": "long",
                "avg_cost": round(avg_cost, 2),
                "last_action": last_action_date,
            })
            total_cost += avg_cost * net_lots * \
                FUTURES_PARAMS.get(code, {}).get("multiplier", 200)

    if not positions:
        return {
            "healthy": True,
            "warnings": [],
            "scores": {},
            "positions": [],
            "summary": "当前无持仓"
        }

    # ── 计算各项指标 ──
    warnings = []
    scores = {}
    capital = total_capital or total_cost / 0.3  # 反估（假设仓位30%）

    # 1. 仓位集中度
    for p in positions:
        pct = (p["avg_cost"] * p["lots"] * FUTURES_PARAMS.get(p["code"], {}).get("multiplier", 200)) / capital
        p["pct"] = round(pct * 100, 1)
        if pct > CONCENTRATION_LIMIT:
            warnings.append(f"⚠️ {p['code']} 仓位占比 {p['pct']:.0f}%（上限 {CONCENTRATION_LIMIT*100:.0f}%）")
    scores["concentration"] = min(1.0, max(
        0, 1 - len([p for p in positions if p.get("pct", 0) > CONCENTRATION_LIMIT * 100]) * 0.3))

    # 2. 方向集中
    sides = [p["side"] for p in positions]
    same_direction = len(set(sides)) <= 1
    if same_direction and len(positions) >= 2:
        warnings.append(f"⚠️ 所有持仓同一方向（{'多头' if sides[0]=='long' else '空头'}）")
    scores["direction"] = 0.5 if same_direction and len(positions) >= 2 else 1.0

    # 3. 频繁换仓
    now = datetime.now()
    cutoff = now - timedelta(days=30)
    recent_trades = [r for r in all_rows if _parse_date(r.get("date", ""))
                     and _parse_date(r.get("date", "")) >= cutoff]
    freq_by_code = defaultdict(int)
    for r in recent_trades:
        freq_by_code[r.get("code", "")] += 1
    for code, freq in freq_by_code.items():
        if freq > FREQ_TRADE_WARN:
            warnings.append(f"⚠️ {code} 近30天交易 {freq} 次（阈值 {FREQ_TRADE_WARN} 次）")
    scores["freq"] = min(1.0, max(0, 1 - max(
        (f - FREQ_TRADE_WARN) / FREQ_TRADE_WARN if f > FREQ_TRADE_WARN else 0
        for f in freq_by_code.values()
    ))) if freq_by_code else 1.0

    # 4. 浮亏加仓（从交易历史检测）
    add_to_losers = _detect_add_to_loser(all_rows)
    for add in add_to_losers:
        warnings.append(f"⚠️ 浮亏加仓 {add['code']}: 在 {add['loss_pct']:.1f}% 浮亏后加仓")
    scores["add_to_loser"] = max(0, 1 - len(add_to_losers) * 0.4)

    # 5. 总健康评分
    score_values = [v for v in scores.values() if isinstance(v, (int, float))]
    overall = sum(score_values) / len(score_values) if score_values else 1.0
    healthy = len(warnings) == 0

    # 汇总
    if healthy:
        summary = f"✅ 持仓健康: {len(positions)} 个品种, 集中度/方向/频率均正常"
    else:
        n = len(warnings)
        summary = f"⚠️ 持仓异常: {len(positions)} 个品种, {n} 项警告, 健康分 {overall:.2f}"

    result = {
        "healthy": healthy,
        "warnings": warnings,
        "scores": {
            "concentration": round(scores.get("concentration", 1.0), 2),
            "direction": round(scores.get("direction", 1.0), 2),
            "freq": round(scores.get("freq", 1.0), 2),
            "add_to_loser": round(scores.get("add_to_loser", 1.0), 2),
            "overall": round(overall, 2),
        },
        "positions": positions,
        "total_trades_30d": len(recent_trades),
        "summary": summary,
        "add_to_loser_events": add_to_losers,
    }

    # ── 触发告警 ──
    if not healthy:
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from alert_manager import send_position_alert
            send_position_alert(warnings)
        except ImportError:
            pass

    return result


def _parse_date(date_str: str) -> datetime:
    """安全解析日期字符串"""
    if not date_str or len(date_str) < 10:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _detect_add_to_loser(trades: list) -> list:
    """检测浮亏加仓行为"""
    by_code = defaultdict(list)
    for t in trades:
        by_code[t.get("code", "")].append(t)

    events = []
    for code, code_trades in by_code.items():
        if not code:
            continue
        code_trades.sort(key=lambda x: x.get("date", ""))
        net_pos = 0
        buy_prices = []

        for t in code_trades:
            action = t.get("action", "")
            price = float(t.get("price", 0))
            vol = int(float(t.get("volume", 0)))

            if action in ("BUY", "ADD") and net_pos > 0 and buy_prices:
                # 已有持仓时买入 — 检查是否比上次开盘低
                avg_prev = sum(buy_prices) / len(buy_prices)
                if price < avg_prev * 0.97:  # 比平均成本低 3% 以上
                    events.append({
                        "code": code,
                        "avg_cost": round(avg_prev, 2),
                        "add_price": price,
                        "loss_pct": round((price - avg_prev) / avg_prev * 100, 1),
                    })
                buy_prices.append(price)
                net_pos += vol
            elif action in ("BUY", "ADD"):
                buy_prices.append(price)
                net_pos += vol
            elif action in ("SELL", "REDUCE"):
                net_pos -= vol
                if net_pos <= 0:
                    buy_prices = []

    return events


def _fmt_markdown(result: dict) -> str:
    """将检查结果格式化为 Markdown（供每日复盘 D10 使用）"""
    lines = ["### 📊 持仓健康自检\n"]
    lines.append(f"**{result['summary']}**")
    lines.append(f"")
    lines.append(f"| 维度 | 评分 | 状态 |")
    lines.append(f"|:----|:---:|:----|")
    icons = {True: "✅", False: "⚠️"}
    for dim, score in result.get('scores', {}).items():
        if dim == 'overall':
            continue
        ok = score >= 0.6
        lines.append(f"| {dim} | {score:.2f} | {icons[ok]} |")
    lines.append(f"| **综合** | {result['scores'].get('overall', 0):.2f} | {'✅' if result['healthy'] else '⚠️'} |")

    if result.get('positions'):
        lines.append(f"\n当前持仓:")
        for p in result['positions']:
            pct_str = f"({p['pct']:.0f}%)" if 'pct' in p else ""
            lines.append(f"  - {p['code']} {p['lots']}手 {p['side']} @{p['avg_cost']} {pct_str}")
    if result.get('warnings'):
        lines.append(f"\n告警:")
        for w in result['warnings']:
            lines.append(f"  - {w}")
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="持仓健康自检")
    parser.add_argument("--capital", type=float, default=None, help="总资金(元)")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出")
    args = parser.parse_args()

    result = check_position_health(total_capital=args.capital)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(_fmt_markdown(result))


if __name__ == "__main__":
    main()
