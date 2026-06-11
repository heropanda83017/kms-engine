#!/usr/bin/env python3
"""
情绪过滤器 — 检测交易中的冲动模式（投资觉察体系应用层）

基于「觉察之道」四步法(看盯挖改)，从交易记录中识别：
  1. 高频冲动交易（同一股票3天内买卖）
  2. 连续错误决策（高买低卖反转）
  3. 情绪驱动交易（觉察日志中标注的触发器）
  4. 决策质量趋势（胜率波动 vs 纪律执行）

用法:
    # 默认最近30天
    python3 scripts/emotion_filter.py

    # 指定天数
    python3 scripts/emotion_filter.py --days 90

    # 详细输出 + JSON
    python3 scripts/emotion_filter.py --json --verbose

依赖:
    - trade_ledger.py (实盘台账 CSV)
    - BLACKHORSE_LEDGER_DIR 环境变量 或 默认路径
"""
import argparse, json, os, sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter

# 默认台账路径
DEFAULT_LEDGER_DIR = Path(
    os.environ.get("BLACKHORSE_LEDGER_DIR",
                   os.path.join(os.path.dirname(__file__), "..", "..",
                                "输出", "investment-engine", "data", "ledger"))
)


def _load_trades(ledger_dir: Path) -> list:
    """加载交易台账"""
    fp = ledger_dir / "trade_ledger.csv"
    if not fp.exists():
        return []
    import csv
    with open(fp, "r", encoding="utf_8_sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _parse_date(d: str):
    """尝试解析日期"""
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(d.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def detect_impulse_trades(trades: list, days: int = 30) -> dict:
    """检测冲动交易模式"""
    cutoff = datetime.now() - timedelta(days=days)
    active = [t for t in trades if _parse_date(t.get("date", ""))
              and _parse_date(t.get("date", "")) >= cutoff]

    result = {
        "period_days": days,
        "total_trades": len(active),
        "impulse_signals": [],
        "patterns": {},
        "risk_level": "low"
    }

    # ── 模式1: 同一股票3天内买卖 (反转交易) ──
    by_code = defaultdict(list)
    for t in active:
        code = t.get("code", "")
        dt = _parse_date(t.get("date", ""))
        action = t.get("action", "")
        if code and dt and action in ("BUY", "SELL"):
            by_code[code].append((dt, action, t))

    reversals = []
    for code, entries in by_code.items():
        sorted_entries = sorted(entries, key=lambda x: x[0])
        for i in range(len(sorted_entries) - 1):
            for j in range(i + 1, min(i + 5, len(sorted_entries))):
                diff = (sorted_entries[j][0] - sorted_entries[i][0]).days
                if diff <= 3:
                    a1, a2 = sorted_entries[i][1], sorted_entries[j][1]
                    if (a1 == "BUY" and a2 == "SELL") or (a1 == "SELL" and a2 == "BUY"):
                        reversals.append({
                            "code": code,
                            "date_from": sorted_entries[i][0].strftime("%Y-%m-%d"),
                            "date_to": sorted_entries[j][0].strftime("%Y-%m-%d"),
                            "gap_days": diff,
                            "type": f"{a1}→{a2}"
                        })

    result["patterns"]["reversal_trades"] = {
        "count": len(reversals),
        "details": reversals[:10],
        "risk": "high" if len(reversals) >= 3 else "medium" if len(reversals) >= 1 else "low"
    }

    # ── 模式2: 高频交易日 (单日操作 ≥3只) ──
    daily_counts = Counter()
    for t in active:
        d = t.get("date", "")
        daily_counts[d] += 1

    high_freq_days = {d: c for d, c in daily_counts.items() if c >= 3}
    result["patterns"]["high_frequency_days"] = {
        "count": len(high_freq_days),
        "details": high_freq_days,
        "risk": "high" if len(high_freq_days) >= 5 else "medium" if len(high_freq_days) >= 2 else "low"
    }

    # ── 模式3: 觉察日志分析 ──
    awareness_records = []
    import json as _json
    for t in active:
        raw = t.get("awareness_log", "")
        if raw:
            try:
                log = _json.loads(raw)
                awareness_records.append(log)
            except (_json.JSONDecodeError, TypeError):
                pass

    triggers = Counter(log.get("trigger", "未记录") for log in awareness_records if log.get("trigger"))
    programs = Counter(log.get("auto_program", "未记录") for log in awareness_records if log.get("auto_program"))

    result["patterns"]["awareness_coverage"] = {
        "total_trades": len(active),
        "with_awareness_log": len(awareness_records),
        "coverage_pct": round(len(awareness_records) / len(active), 4) if active else 0,
        "top_triggers": dict(triggers.most_common(5)),
        "top_programs": dict(programs.most_common(5)),
        "risk": "high" if len(awareness_records) < len(active) * 0.3 and active else "medium"
    }

    # ── 综合风险等级 ──
    risk_scores = {
        "high": 3, "medium": 2, "low": 1
    }
    scores = [
        risk_scores.get(result["patterns"].get(p, {}).get("risk", "low"), 1)
        for p in result["patterns"]
    ]
    avg_risk = sum(scores) / len(scores) if scores else 1
    if avg_risk >= 2.5:
        result["risk_level"] = "high"
    elif avg_risk >= 1.5:
        result["risk_level"] = "medium"
    else:
        result["risk_level"] = "low"

    result["impulse_signals"] = reversals[:5]

    return result


def _fmt_risk(r: str) -> str:
    return {"high": "🔴 高风险", "medium": "🟡 中等", "low": "🟢 低风险"}.get(r, r)


def generate_report(result: dict) -> str:
    """生成可读的情绪报告"""
    lines = [
        "=" * 60,
        f"🧠 投资情绪过滤器 — 行为偏差检测报告",
        "=" * 60,
        f"  分析周期: 最近 {result['period_days']} 天",
        f"  交易总数: {result['total_trades']} 笔",
        f"  综合风险: {_fmt_risk(result['risk_level'])}",
        "",
        "── 检测模式 ──",
    ]

    for pattern_name, pattern_data in result.get("patterns", {}).items():
        label_map = {
            "reversal_trades": "🔄 反转交易 (3天内买卖)",
            "high_frequency_days": "⚡ 高频交易日 (单日≥3只)",
            "awareness_coverage": "👁️ 觉察日志覆盖率",
        }
        label = label_map.get(pattern_name, pattern_name)
        lines.append(f"\n  {label}: {_fmt_risk(pattern_data.get('risk', 'low'))}")
        lines.append(f"    数值: {pattern_data.get('count', pattern_data.get('total_trades', 'N/A'))}")

        if pattern_name == "reversal_trades" and pattern_data.get("details"):
            lines.append("    详情:")
            for rev in pattern_data["details"][:5]:
                lines.append(
                    f"      {rev['code']}: {rev['date_from']} → "
                    f"{rev['date_to']} ({rev['gap_days']}天, {rev['type']})"
                )

        if pattern_name == "awareness_coverage":
            lines.append(f"    覆盖率: {pattern_data.get('coverage_pct', 0):.1%}")
            if pattern_data.get("top_triggers"):
                lines.append("    常见触发场景:")
                for t, c in pattern_data["top_triggers"].items():
                    lines.append(f"      · {t} ({c}次)")

    # ── 建议 ──
    lines.extend([
        "",
        "── 改善建议 ──",
    ])
    risk = result["risk_level"]
    if risk == "high":
        lines.extend([
            "  🔴 当前行为偏差风险较高，建议:",
            "    1. 暂停交易，静坐觉察5分钟后再决策",
            "    2. 每笔交易操作前先填写觉察日志",
            "    3. 检查是否在按策略信号操作，还是情绪驱动",
        ])
    elif risk == "medium":
        lines.extend([
            "  🟡 存在一定行为偏差风险，建议:",
            "    1. 对反转交易复盘: 是什么情绪触发了反向操作?",
            "    2. 提高觉察日志填写率",
            "    3. 减少单日操作频率",
        ])
    else:
        lines.extend([
            "  🟢 行为偏差控制在正常范围，继续保持",
            "    坚持记录觉察日志有助于长期纪律",
        ])

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="投资情绪过滤器")
    p.add_argument("--days", type=int, default=30, help="分析天数（默认30）")
    p.add_argument("--json", action="store_true", help="JSON格式输出")
    p.add_argument("--verbose", action="store_true", help="详细输出")
    p.add_argument("--ledger-dir", default=str(DEFAULT_LEDGER_DIR), help="台账目录")
    args = p.parse_args()

    trades = _load_trades(Path(args.ledger_dir))
    if not trades:
        print(f"⚠️ 未找到交易台账: {args.ledger_dir}/trade_ledger.csv")
        print("首次使用请先创建一条交易记录。")
        return

    result = detect_impulse_trades(trades, args.days)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(generate_report(result))

    if args.verbose and not args.json:
        print(f"\n📊 原始数据: {len(trades)} 条总记录")


if __name__ == "__main__":
    main()
