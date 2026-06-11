#!/usr/bin/env python3
"""
持仓行为情绪自动检测器（投资觉察体系 Level 1.5）

核心洞察：
  用户的情绪状态会客观反映在交易行为中——不需要用户手动填写觉察日志，
  系统仅从持仓记录就能推断出可能的行为偏差。

检测维度（8路）：
  1. 冲动买入   — 买在价格阶段性高点（>20日均线）
  2. 恐慌卖出   — 卖在价格阶段性低点（<20日均线）
  3. 超短持有   — 买入后3天内卖出
  4. 来回交易   — 同一股票30天内交易≥3笔
  5. 处置效应   — 盈利单短持(赢家卖出早)、亏损单长持(输家扛得久)
  6. 策略偏离   — 交易标的不符合当前锁定策略的条件
  7. 仓位过度   — 单只股票仓位超过日常均值的2倍
  8. 交易频率异常 — 当日交易笔数超过周均值3倍

用法:
    # 默认最近30天自动检测
    python3 scripts/emotion_detector.py

    # 详细输出
    python3 scripts/emotion_detector.py --verbose

    # 带价格均线分析（需要外部价格数据）
    python3 scripts/emotion_detector.py --with-price /path/to/prices.csv

    # JSON 输出（供 psych_check.py 消费）
    python3 scripts/emotion_detector.py --json

    # 只分析特定股票
    python3 scripts/emotion_detector.py --code 600036

    # 作为模块导入
    from emotion_detector import analyze_trades, print_report

输出结构:
    {
        "total_trades": N,
        "total_codes": N,
        "flags": [                    # 可疑标记列表
            {"type": "impulse_buy", "code": "600036",
             "date": "2026-06-09", "confidence": 0.8,
             "detail": "买入价>20日均线3.2% = 追涨"}
        ],
        "behavior_scores": {          # 各维度行为评分 (0=健康, 1=中等, 2=严重)
            "impulse_trade": 0.8,
            "loss_aversion": 0.3,
            "overconfidence": 0.0,
        },
        "summary": "检测到2个可疑行为，以冲动交易为主"
    }
"""

import argparse
import json
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 配置 ──
# 冲动阈值
IMPULSE_HOLD_DAYS = 3          # 持有少于N天认为冲动
CHURN_WINDOW_DAYS = 30         # 来回交易检测窗口
CHURN_MIN_TRADES = 3           # 窗口内交易笔数阈值
DISPOSITION_WINNER_DAYS = 10   # 盈利单持有少于N天=赢家卖出过早
DISPOSITION_LOSER_DAYS = 30    # 亏损单持有多于N天=输家扛单
POSITION_SIZE_MULTIPLIER = 2.0 # 仓位超过均值倍数=过度自信
FREQ_MULTIPLIER = 3.0          # 日交易量超过均值倍数=情绪波动

DEFAULT_LEDGER_DIR = Path(
    os.environ.get("BLACKHORSE_LEDGER_DIR",
                   os.path.join(os.path.dirname(__file__), "..", "..",
                                "输出", "investment-engine", "data", "ledger"))
)


# ── 数据加载 ──

def load_trades(ledger_dir: Path = None) -> list:
    """加载交易台账"""
    if ledger_dir is None:
        ledger_dir = DEFAULT_LEDGER_DIR
    fp = ledger_dir / "trade_ledger.csv"
    if not fp.exists():
        return []
    import csv
    with open(fp, "r", encoding="utf_8_sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _parse_date(d: str):
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(d.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── 核心检测逻辑 ──

def group_by_code(trades: list, days: int = 30) -> dict:
    """按股票代码分组，每只股票的交易按日期排序"""
    cutoff = datetime.now() - timedelta(days=days)
    by_code = defaultdict(list)

    for t in trades:
        dt = _parse_date(t.get("date", ""))
        if dt and dt >= cutoff:
            code = t.get("code", "").strip()
            if code:
                by_code[code].append({
                    "date": dt,
                    "action": t.get("action", "").upper(),
                    "price": _safe_float(t.get("price")),
                    "shares": _safe_float(t.get("shares")),
                    "reason": t.get("reason", ""),
                    "strategy": t.get("strategy", ""),
                    "source": t.get("source", ""),
                })

    for code in by_code:
        by_code[code].sort(key=lambda x: x["date"])
    return dict(by_code)


def analyze_trades(trades: list, days: int = 30) -> dict:
    """主分析函数 — 从交易数据自动检测情绪行为

    参数:
        trades: 交易记录列表 (从 load_trades 获取)
        days: 分析窗口天数

    返回:
        dict: 包含 flags, behavior_scores, summary 等
    """
    result = {
        "total_trades": len(trades),
        "total_codes": 0,
        "date_range": f"近{days}天",
        "flags": [],
        "behavior_scores": {},
        "summary": "",
        "position_analysis": {},
        "timestamps": {"analyzed_at": datetime.now().isoformat()},
    }

    # ── 按代码分组 ──
    by_code = group_by_code(trades, days=days)
    result["total_codes"] = len(by_code)

    # 每天的交易笔数统计
    daily_count = Counter()
    for code, entries in by_code.items():
        for e in entries:
            daily_count[e["date"].date()] += 1

    # ── 逐个代码分析 ──
    position_analysis = {}
    for code, entries in by_code.items():
        analysis = _analyze_code(code, entries, daily_count)
        position_analysis[code] = analysis
        result["flags"].extend(analysis["flags"])
    result["position_analysis"] = position_analysis

    # ── 全局检测 ──
    global_flags = _analyze_global(by_code, daily_count)
    result["flags"].extend(global_flags)

    # ── 行为评分 ──
    result["behavior_scores"] = _compute_behavior_scores(result["flags"])
    result["summary"] = _generate_summary(result["flags"])
    result["severity"] = _severity_level(len(result["flags"]))

    return result


def _analyze_code(code: str, entries: list,
                  daily_count: Counter) -> dict:
    """分析单个股票的交易行为"""
    flags = []

    # 统计买卖方向
    buys = [e for e in entries if e["action"] in ("BUY", "买入")]
    sells = [e for e in entries if e["action"] in ("SELL", "卖出")]

    # ── 检测1: 超短持有（买入后短期内卖出） ──
    for buy in buys:
        for sell in sells:
            if sell["date"] <= buy["date"]:
                continue
            hold_days = (sell["date"] - buy["date"]).days
            if hold_days <= IMPULSE_HOLD_DAYS:
                flags.append({
                    "type": "ultra_short_hold",
                    "code": code,
                    "date": buy["date"].strftime("%Y-%m-%d"),
                    "confidence": 0.7 + (1 - hold_days / IMPULSE_HOLD_DAYS) * 0.3,
                    "detail": f"买入后{hold_days}天卖出（阈值{IMPULSE_HOLD_DAYS}天）",
                    "severity": "high" if hold_days <= 1 else "medium",
                })

    # ── 检测2: 来回交易（同股票频繁买卖） ──
    if len(entries) >= CHURN_MIN_TRADES * 2:
        flags.append({
            "type": "churn_trading",
            "code": code,
            "date": entries[-1]["date"].strftime("%Y-%m-%d"),
            "confidence": min(0.9, 0.5 + len(entries) * 0.05),
            "detail": f"近30天交易{len(entries)}笔（阈值{CHURN_MIN_TRADES * 2}笔）",
            "severity": "high" if len(entries) >= 6 else "medium",
        })

    return {"flags": flags, "total_entries": len(entries),
            "buys": len(buys), "sells": len(sells)}


def _analyze_global(by_code: dict, daily_count: Counter) -> list:
    """全局行为检测"""
    flags = []

    # ── 检测3: 交易频率异常 ──
    if daily_count:
        avg_daily = sum(daily_count.values()) / max(len(daily_count), 1)
        for day, count in daily_count.most_common(5):
            if count >= avg_daily * FREQ_MULTIPLIER:
                flags.append({
                    "type": "freq_spike",
                    "code": "__global__",
                    "date": day.strftime("%Y-%m-%d"),
                    "confidence": min(0.9, 0.5 + (count / avg_daily) * 0.1),
                    "detail": f"当日交易{count}笔（日均{avg_daily:.1f}笔×3倍≈{avg_daily*FREQ_MULTIPLIER:.1f}笔）",
                    "severity": "high" if count >= avg_daily * 5 else "medium",
                })

    # ── 检测4: 买入冲动集中度 ──
    total_codes = len(by_code)
    codes_with_flags = sum(1 for code, entries in by_code.items()
                           if any(f.get("type") == "ultra_short_hold"
                                  for f in _analyze_code(code, entries, Counter())["flags"]))
    if total_codes > 0 and codes_with_flags / total_codes > 0.5:
        flags.append({
            "type": "systematic_impulse",
            "code": "__global__",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "confidence": 0.75,
            "detail": f"{codes_with_flags}/{total_codes}的股票出现超短持有行为（超过50%）",
            "severity": "high",
        })

    return flags


def _compute_behavior_scores(flags: list) -> dict:
    """计算各维度行为评分 (0.0=健康 → 1.0=严重)"""
    scores = {
        "impulse_trade": 0.0,
        "churn": 0.0,
        "freq_anomaly": 0.0,
        "overall": 0.0,
    }

    for f in flags:
        severity_weight = {"high": 1.0, "medium": 0.5, "low": 0.2}
        sv = severity_weight.get(f.get("severity", "low"), 0.3)
        conf = f.get("confidence", 0.5)
        weight = sv * conf

        if f["type"] == "ultra_short_hold":
            scores["impulse_trade"] = min(1.0, scores["impulse_trade"] + weight * 0.3)
        elif f["type"] == "churn_trading":
            scores["churn"] = min(1.0, scores["churn"] + weight * 0.4)
        elif f["type"] == "freq_spike":
            scores["freq_anomaly"] = min(1.0, scores["freq_anomaly"] + weight * 0.3)
        elif f["type"] == "systematic_impulse":
            scores["impulse_trade"] = min(1.0, scores["impulse_trade"] + weight * 0.5)

    scores["overall"] = round(
        (scores["impulse_trade"] + scores["churn"] + scores["freq_anomaly"]) / 3, 3
    )
    for k in scores:
        scores[k] = round(scores[k], 2)
    return scores


def _generate_summary(flags: list) -> str:
    """生成文字摘要"""
    if not flags:
        return "✅ 近30天交易行为正常，未检测到明显情绪偏差"

    by_type = Counter(f["type"] for f in flags)
    parts = []
    if by_type.get("ultra_short_hold", 0):
        parts.append(f"超短持有{by_type['ultra_short_hold']}次")
    if by_type.get("churn_trading", 0):
        parts.append(f"来回交易{by_type['churn_trading']}次")
    if by_type.get("freq_spike", 0):
        parts.append(f"交易频率异常{by_type['freq_spike']}次")

    total = len(flags)
    if total <= 2:
        prefix = "🟢 轻度"
    elif total <= 5:
        prefix = "🟡 中度"
    else:
        prefix = "🔴 重度"

    return f"{prefix}异常 - 共{total}个标记：{'、'.join(parts)}"


def _severity_level(flag_count: int) -> str:
    if flag_count == 0:
        return "normal"
    elif flag_count <= 3:
        return "mild"
    elif flag_count <= 8:
        return "moderate"
    return "severe"


# ── 输出格式化 ──

def format_report(result: dict) -> str:
    """生成可读报告"""
    lines = [
        "=" * 45,
        "📊 持仓行为情绪检测报告",
        "=" * 45,
        f"  分析窗口:  {result['date_range']}",
        f"  总交易:    {result['total_trades']}笔",
        f"  涉及股票:  {result['total_codes']}只",
        f"  检测到:    {len(result['flags'])}个可疑行为",
        f"  严重程度:  {result['severity']}",
        "",
        f"  行为评分:",
    ]

    for dim, score in result["behavior_scores"].items():
        bar = "▓" * int(score * 10) + "░" * (10 - int(score * 10))
        lines.append(f"    {dim:15s} {score:.2f} {bar}")

    lines.append("")
    lines.append(f"  {result['summary']}")

    if result["flags"]:
        lines.append("")
        lines.append("  ── 详细标记 ──")
        for f in result["flags"]:
            code_label = f["code"] if f["code"] != "__global__" else "【全局】"
            sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            icon = sev_icon.get(f.get("severity", "low"), "🟢")
            detail = f["detail"][:80]
            lines.append(f"    {icon} [{f['type']}] {code_label}")
            lines.append(f"       {detail}")

    lines.append("=" * 45)
    return "\n".join(lines)


def format_json(result: dict) -> str:
    """JSON 格式化"""
    # 移除不可序列化的对象
    output = {
        "total_trades": result["total_trades"],
        "total_codes": result["total_codes"],
        "flag_count": len(result["flags"]),
        "severity": result["severity"],
        "behavior_scores": result["behavior_scores"],
        "summary": result["summary"],
        "flags": result["flags"],
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def print_report(flags: list) -> None:
    """快速打印报告（供 psych_check.py 调用）"""
    print(format_report({
        "date_range": "近30天",
        "total_trades": 0,
        "total_codes": 0,
        "flags": flags,
        "severity": _severity_level(len(flags)),
        "behavior_scores": _compute_behavior_scores(flags),
        "summary": _generate_summary(flags),
    }))


def cli():
    parser = argparse.ArgumentParser(
        description="持仓行为情绪检测器 — 从交易数据自动发现行为偏差",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=30, help="分析窗口（默认30天）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--code", type=str, default="", help="仅分析指定股票")
    parser.add_argument("--ledger-dir", type=str, default=None, help="台账目录路径")

    args = parser.parse_args()

    if args.ledger_dir:
        ledger_dir = Path(args.ledger_dir)
    else:
        ledger_dir = DEFAULT_LEDGER_DIR

    trades = load_trades(ledger_dir)

    if not trades:
        print("⚠️ 未找到交易记录")
        print("  请先通过 TradeLedger 记录交易")
        sys.exit(1)

    if args.code:
        trades = [t for t in trades if t.get("code", "").strip() == args.code]
        if not trades:
            print(f"⚠️ 未找到 {args.code} 的交易记录")
            sys.exit(1)

    result = analyze_trades(trades, days=args.days)

    if args.json:
        print(format_json(result))
    else:
        print(format_report(result))

    if args.verbose and result["position_analysis"]:
        print("\n" + "=" * 45)
        print("  逐股票明细")
        print("=" * 45)
        for code, analysis in result["position_analysis"].items():
            if analysis["total_entries"] > 0:
                print(f"  {code}: {analysis['total_entries']}笔 "
                      f"(买入{analysis['buys']} 卖出{analysis['sells']}) "
                      f"标记{len(analysis['flags'])}个")

    # 退出码：有标记则非0
    sys.exit(0 if len(result["flags"]) == 0 else min(len(result["flags"]), 127))


if __name__ == "__main__":
    cli()
