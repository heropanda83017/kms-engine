#!/usr/bin/env python3
"""
投资心理晴雨表 — 每日复盘 D10 维度

基于「觉察之道」框架，在每日复盘中增加心理维度分析：
  1. 近期交易行为偏差评估
  2. 觉察日志覆盖率趋势
  3. 常见触发场景与自动程序
  4. 投资心态综合评分

用法:
    # 默认最近7天
    python3 scripts/psych_check.py

    # 指定天数 (适合周末或月末深度复盘)
    python3 scripts/psych_check.py --days 30

    # Markdown格式 (供每日复盘直接嵌入)
    python3 scripts/psych_check.py --markdown

依赖:
    - TradeLedger (trade_ledger.py)
    - Emotion filter (emotion_filter.py) — 作为子模块调用
"""
import argparse, json, os, sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# 自动情绪检测器 — 在模块层面导入
_AUTO_DETECTOR_READY = False
try:
    from emotion_detector import analyze_trades as _analyze_trades
    _AUTO_DETECTOR_READY = True
except ImportError:
    _AUTO_DETECTOR_READY = False

# 台账路径（与 TradeLedger 保持一致）
DEFAULT_LEDGER_DIR = Path(
    os.environ.get("BLACKHORSE_LEDGER_DIR",
                   os.path.join(os.path.dirname(__file__), "..", "..",
                                "输出", "investment-engine", "data", "ledger"))
)


def _load_trades(ledger_dir: Path) -> list:
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


def psych_check(trades: list, days: int = 7) -> dict:
    """生成心理晴雨表"""
    cutoff = datetime.now() - timedelta(days=days)
    active = [t for t in trades if _parse_date(t.get("date", ""))
              and _parse_date(t.get("date", "")) >= cutoff]

    result = {
        "period_days": days,
        "total_trades": len(active),
        "awareness_rate": 0.0,
        "mood_score": 0,       # 0-100
        "top_triggers": {},
        "top_programs": {},
        "reversal_count": 0,
        "assessment": "暂无数据",
        "suggestion": "暂无数据",
    }

    if not active:
        return result

    # ── 觉察日志分析 ──
    import json as _json
    awareness_count = 0
    triggers = Counter()
    programs = Counter()
    attachments = []

    for t in active:
        raw = t.get("awareness_log", "")
        if raw:
            try:
                log = _json.loads(raw)
                awareness_count += 1
                if log.get("trigger"):
                    triggers[log["trigger"]] += 1
                if log.get("auto_program"):
                    programs[log["auto_program"]] += 1
                if log.get("attachment"):
                    attachments.append(log["attachment"])
            except (_json.JSONDecodeError, TypeError):
                pass

    result["awareness_rate"] = round(awareness_count / len(active), 4) if active else 0
    result["top_triggers"] = dict(triggers.most_common(5))
    result["top_programs"] = dict(programs.most_common(5))
    result["attachments"] = attachments[:3]

    # ── 反转交易检测 ──
    reversals = _count_reversals(active)
    result["reversal_count"] = reversals

    # ── 情绪评分计算 ──
    # 基准分: 60
    score = 60
    # 加分: 觉察覆盖率每10% +5
    score += int(result["awareness_rate"] * 10) * 5
    # 加分: 记录觉察日志的笔数 +2/笔 (上限20)
    score += min(awareness_count * 2, 20)
    # 减分: 每笔反转交易 -10
    score -= reversals * 10
    # 减分: 无觉察日志记录 -15
    if awareness_count == 0 and len(active) > 3:
        score -= 15
    result["mood_score"] = max(0, min(100, score))

    # ── 文字评估 ──
    s = result["mood_score"]
    if s >= 80:
        result["assessment"] = "🟢 心态良好 — 纪律执行到位，觉察意识强"
        result["suggestion"] = "保持当前状态，持续填写觉察日志有助于长期纪律固化"
    elif s >= 60:
        result["assessment"] = "🟡 心态中等 — 有一定觉察意识，但情绪干扰仍存在"
        result["suggestion"] = "对反转交易逐一复盘，找出每个反向操作的触发点"
    elif s >= 40:
        result["assessment"] = "🟠 心态偏弱 — 情绪驱动交易较多，需要加强觉察训练"
        result["suggestion"] = "建议: 暂停交易5分钟→静坐觉察→只按策略信号操作"
    else:
        result["assessment"] = "🔴 心态风险 — 存在明显情绪驱动交易行为"
        result["suggestion"] = "强烈建议: 当日暂停所有手动交易，只执行既定策略信号"

    # ── 自动情绪检测已移到 main() 中统一补充，psych_check 保持纯净

    return result


def _mood_bar(score: int) -> str:
    """生成情绪进度条"""
    filled = score // 10
    empty = 10 - filled
    return "▓" * filled + "░" * empty


def _count_reversals(active: list) -> int:
    """统计反转交易次数"""
    from collections import defaultdict
    by_code = defaultdict(list)
    for t in active:
        code = t.get("code", "")
        dt = _parse_date(t.get("date", ""))
        action = t.get("action", "")
        if code and dt and action in ("BUY", "SELL"):
            by_code[code].append((dt, action))
    count = 0
    for _, entries in by_code.items():
        sorted_entries = sorted(entries, key=lambda x: x[0])
        for i in range(len(sorted_entries) - 1):
            for j in range(i + 1, min(i + 5, len(sorted_entries))):
                diff = (sorted_entries[j][0] - sorted_entries[i][0]).days
                if diff <= 3:
                    a1, a2 = sorted_entries[i][1], sorted_entries[j][1]
                    if (a1 == "BUY" and a2 == "SELL") or (a1 == "SELL" and a2 == "BUY"):
                        count += 1
    return count


def to_markdown(result: dict) -> str:
    """生成可嵌入每日复盘的Markdown段落"""
    if result["total_trades"] == 0:
        return (
            "## 🧘 D10 投资心理晴雨表\n\n"
            f"  分析周期: 最近 {result['period_days']} 天\n"
            f"  📭 无交易记录\n"
        )

    lines = [
        f"## 🧘 D10 投资心理晴雨表",
        "",
        f"| 指标 | 数值 |",
        f"|:----|:----:|",
        f"| 分析周期 | 最近 {result['period_days']} 天 |",
        f"| 交易笔数 | {result['total_trades']} 笔 |",
        f"| 觉察日志覆盖率 | {result['awareness_rate']:.1%} |",
        f"| 反转交易 (3天内) | {result['reversal_count']} 次 |",
        f"| 心态评分 | {result['mood_score']}/100 |",
        "",
        f"  {_mood_bar(result['mood_score'])}  {result['assessment']}",
        "",
        "**建议:**",
        f"  {result['suggestion']}",
    ]

    if result.get("top_triggers"):
        lines.extend([
            "",
            "**常见触发场景:**",
        ])
        for t, c in result["top_triggers"].items():
            lines.append(f"  · {t} （{c}次）")

    if result.get("top_programs"):
        lines.extend([
            "",
            "**常见自动程序:**",
        ])
        for p, c in result["top_programs"].items():
            lines.append(f"  · {p}（{c}次）")

    lines.append("")
    auto_block = _fmt_auto_flags(result)
    if auto_block:
        lines.append(auto_block)
    return "\n".join(lines)


def _fmt_auto_flags(result: dict) -> str:
    """格式化自动检测标记"""
    flags = result.get("auto_flags", [])
    if not flags:
        return ""

    severity = result.get("auto_severity", "normal")
    icon = {"normal": "🟢", "mild": "🟡", "moderate": "🟠", "severe": "🔴"}
    sv = icon.get(severity, "🟢")

    lines = [
        "",
        f"**{sv} 自动情绪检测** [{severity}]",
        "",
    ]
    for f in flags[:8]:  # 最多显示8条
        sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        lines.append(
            f"  {sev_icon.get(f.get('severity','low'),'🟢')} "
            f"[{f['type']}] {f['code']}: {f['detail']}"
        )

    scores = result.get("auto_scores", {})
    if scores:
        lines.append("")
        for dim, score in scores.items():
            bar = "▓" * int(score * 10) + "░" * (10 - int(score * 10))
            lines.append(f"  {dim}: {score:.2f} {bar}")

    lines.append(f"\n  {result.get('auto_summary', '')}")

    deduction = result.get("auto_deduction", 0)
    if deduction > 0:
        lines.append(f"  ⚡ 自动检测异常已扣分: -{deduction}")

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="投资心理晴雨表")
    p.add_argument("--days", type=int, default=7, help="分析天数（默认7）")
    p.add_argument("--markdown", action="store_true", help="Markdown格式输出")
    p.add_argument("--json", action="store_true", help="JSON格式输出")
    p.add_argument("--ledger-dir", default=str(DEFAULT_LEDGER_DIR))
    args = p.parse_args()

    trades = _load_trades(Path(args.ledger_dir))
    result = psych_check(trades, args.days)

    # 补充自动情绪检测（零成本分析，不依赖手动觉察日志）
    try:
        from emotion_detector import analyze_trades
        auto_flags = analyze_trades(trades, days=args.days)
        result["auto_flags"] = auto_flags["flags"]
        result["auto_scores"] = auto_flags["behavior_scores"]
        result["auto_summary"] = auto_flags["summary"]
        result["auto_severity"] = auto_flags["severity"]
        if auto_flags["severity"] in ("moderate", "severe"):
            result["auto_deduction"] = min(25, len(auto_flags["flags"]) * 5)
            result["mood_score"] = max(0, result["mood_score"] - result["auto_deduction"])
    except ImportError:
        pass

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(to_markdown(result))
    else:
        s = result["mood_score"]
        bar = _mood_bar(s)
        print(f"🧘 投资心理晴雨表 (最近{result['period_days']}天)")
        print(f"  📊 交易: {result['total_trades']}笔 | 觉察率: {result['awareness_rate']:.1%}")
        print(f"  🔄 反转交易: {result['reversal_count']}次")
        print(f"  {bar}  {s}/100 — {result['assessment']}")
        print(f"  建议: {result['suggestion']}")
        if result.get("top_triggers"):
            print(f"  常见触发: {', '.join(result['top_triggers'].keys())}")


if __name__ == "__main__":
    main()
