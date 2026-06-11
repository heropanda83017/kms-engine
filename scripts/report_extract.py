"""
report_extract.py — 研报提取管线：合并 wudao MCP 数据 → 结构化 Markdown 报告

用法:
    python3 scripts/report_extract.py <input.json> [-o <output.md>]

输入 JSON 格式:
    {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "date": "2026-06-05",
        "research_reports": [...],       # 来自 wudao MCP research_reports
        "financial_summary": {...},       # 来自 wudao MCP financial_summary
        "announcements": [...],           # 来自 wudao MCP official_announcements
        "interactions": [...]             # 来自 wudao MCP official_interactions
    }
"""

import json, sys, os
from pathlib import Path
from datetime import datetime


def _s(val, default="--"):
    """Safe string conversion."""
    if val is None:
        return default
    if isinstance(val, float):
        return f"{val:.2f}"
    s = str(val)
    # Strip surrounding whitespace
    s = s.strip()
    return s


def _pct(val):
    """Format as percentage string."""
    if val is None:
        return "--"
    try:
        v = float(val)
        return f"{v:+.2f}%" if abs(v) > 0.01 else f"{v:.2f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_yi(val):
    """Format yuan value as 亿 (100M)."""
    if val is None:
        return "--"
    try:
        v = float(val)
        if abs(v) >= 1e8:
            return f"{v/1e8:.2f}亿"
        elif abs(v) >= 1e4:
            return f"{v/1e4:.2f}万"
        return f"{v:.2f}"
    except (ValueError, TypeError):
        return str(val)[:20]


def section_business(segments):
    """Render business segments section."""
    if not segments:
        return ""

    lines = ["### 业务结构\n"]
    lines.append("| 业务 | 收入(亿) | 成本(亿) | 毛利(亿) | 毛利率 |")
    lines.append("|:----|:--------|:--------|:--------|:------|")

    for seg in segments[:8]:
        item = seg.get("bz_item", seg.get("产品", "--"))
        sales = _fmt_yi(seg.get("bz_sales", ""))
        cost = _fmt_yi(seg.get("bz_cost", ""))
        profit = _fmt_yi(seg.get("bz_profit", ""))
        # Calculate gross margin with type safety
        try:
            raw_profit = float(seg.get("bz_profit") or 0)
            raw_sales = float(seg.get("bz_sales") or 0)
            if raw_sales > 0:
                margin_pct = f"{raw_profit / raw_sales * 100:.1f}%"
            else:
                margin_pct = seg.get("毛利率", "--")
        except (TypeError, ValueError):
            margin_pct = seg.get("毛利率", "--")
        lines.append(f"| {item} | {sales} | {cost} | {profit} | {margin_pct} |")

    lines.append("")
    return "\n".join(lines)

def section_financial(fs_data):
    """Render financial summary section."""
    if not fs_data:
        return "## 财务摘要\n\n> 数据不可用\n"

    lines = ["## 财务摘要\n"]

    # Try to extract key indicators from financial_summary
    indicators = fs_data.get("indicators", {}) or {}
    if indicators:
        lines.append("| 指标 | 最新值 | 同比 |")
        lines.append("|:-----|:------|:-----|")
        for row in indicators:
            name = row.get("name", "--")
            value = _s(row.get("value"))
            yoy = _pct(row.get("yoy"))
            lines.append(f"| {name} | {value} | {yoy} |")
        lines.append("")

    # Income statement
    income = fs_data.get("income", {}) or {}
    if income:
        # income might be a list of periods
        if isinstance(income, list) and len(income) > 0:
            lines.append("### 利润表趋势\n")
            cols = ["报告期"]
            for key in ["营业总收入", "营业收入", "净利润", "归母净利润", "扣非净利润",
                         "营业总成本", "营业成本", "销售费用", "管理费用", "财务费用",
                         "研发费用", "投资收益", "营业利润", "利润总额"]:
                if any(key in (str(k) for k in r.keys()) for r in income[:3]):
                    cols.append(key)
            header = "| " + " | ".join(cols[:7]) + " |"
            sep = "|" + "|".join([":---"] * min(len(cols), 7)) + "|"
            lines.append(header)
            lines.append(sep)
            for period in income[:5]:
                row_vals = [str(period.get(c, "--"))[:20] for c in cols[:7]]
                lines.append("| " + " | ".join(row_vals) + " |")
            lines.append("")

    # Balance sheet
    balance = fs_data.get("balance", {}) or {}
    if isinstance(balance, list) and len(balance) > 0:
        lines.append("### 资产负债表摘要\n")
        for period in balance[:3]:
            lines.append(f"- **{period.get('REPORT_DATE', period.get('报告期', '--'))}**："
                         f"总资产 {_s(period.get('TOTAL_ASSETS', period.get('总资产', '')))} 亿, "
                         f"总负债 {_s(period.get('TOTAL_LIABILITIES', period.get('总负债', '')))} 亿, "
                         f"权益 {_s(period.get('TOTAL_EQUITY', period.get('所有者权益合计', '')))} 亿")
        lines.append("")

    # Cash flow
    cashflow = fs_data.get("cashflow", []) or {}
    if isinstance(cashflow, list) and len(cashflow) > 0:
        lines.append("### 现金流摘要\n")
        for period in cashflow[:3]:
            lines.append(f"- **{period.get('REPORT_DATE', period.get('报告期', '--'))}**："
                         f"经营 {_fmt_yi(period.get('经营活动产生的现金流量净额', period.get('OPERATING_CF', '')))}, "
                         f"投资 {_fmt_yi(period.get('投资活动产生的现金流量净额', period.get('INVESTING_CF', '')))}, "
                         f"筹资 {_fmt_yi(period.get('筹资活动产生的现金流量净额', period.get('FINANCING_CF', '')))}")
        lines.append("")

    return "\n".join(lines)


def section_research(reports):
    """Render research reports section."""
    if not reports:
        return "## 近期研报\n\n> 无近期研报记录\n"

    lines = ["## 近期研报\n"]
    lines.append(f"共 **{len(reports)}** 篇研报\n")
    lines.append("| 日期 | 券商 | 评级 | 目标价 | EPS预测 | 摘要 |")
    lines.append("|:----|:-----|:----|:------|:--------|:-----|")

    for r in reports[:15]:  # Top 15
        date = r.get("publishDate", r.get("日期", "--"))[:10]
        broker = r.get("brokerName", r.get("券商", "--"))
        rating = r.get("rating", r.get("评级", "--"))
        tp = _s(r.get("targetPrice", r.get("目标价", "")))
        eps = r.get("epsForecast", r.get("EPS预测", ""))
        summary = r.get("summary", r.get("摘要", ""))[:60]

        lines.append(f"| {date} | {broker} | {rating} | {tp} | {eps} | {summary} |")

    lines.append("")
    return "\n".join(lines)


def section_announcements(anns):
    """Render official announcements section."""
    if not anns:
        return "## 官方公告\n\n> 近期无重大公告\n"

    lines = ["## 官方公告\n"]
    lines.append(f"共 **{len(anns)}** 条公告\n")
    lines.append("| 日期 | 标题 | 内容摘要 |")
    lines.append("|:----|:-----|:---------|")

    for a in anns[:10]:
        date = a.get("announcementDate", a.get("日期", "--"))[:10]
        title = a.get("announcementTitle", a.get("标题", "--"))
        content = a.get("announcementContent", a.get("内容", ""))[:80]
        lines.append(f"| {date} | {title} | {content} |")

    lines.append("")
    return "\n".join(lines)


def section_interactions(interactions):
    """Render investor Q&A section."""
    if not interactions:
        return "## 投资者互动\n\n> 近期无互动问答记录\n"

    lines = ["## 投资者互动\n"]

    for qa in interactions[:8]:
        date = qa.get("questionDate", qa.get("日期", "--"))[:10]
        question = qa.get("question", qa.get("提问", ""))[:100]
        answer = qa.get("answer", qa.get("回复", ""))[:200]
        lines.append(f"- **{date}**：{question}")
        lines.append(f"  > {answer}\n")

    return "\n".join(lines)


def section_summary():
    """Render summary section with risk disclaimer."""
    return (
        "## 综合结论\n\n"
        "> 以上信息由 wudao MCP 实时数据 + 自动合并生成，仅供参考。\n"
        "> ⚠️ 以上分析仅供学习研究，不构成投资建议。市场有风险，投资需谨慎。\n"
    )


def merge_report(data):
    """Merge all sections into a complete report."""
    stock_code = data.get("stock_code", "--")
    stock_name = data.get("stock_name", "--")
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))

    lines = [
        f"# 研报提取: {stock_name}({stock_code})",
        "",
        f"> 生成日期: {date_str} | 数据源: wudao MCP",
        "",
        "---",
        "",
    ]

    lines.append(section_financial(data.get("financial_summary", {})))
    lines.append(section_business(
        data.get("financial_summary", {}).get("business_segments", [])
    ))
    lines.append("")
    lines.append("---\n")
    lines.append(section_research(data.get("research_reports", [])))
    lines.append("")
    lines.append("---\n")
    lines.append(section_announcements(data.get("announcements", [])))
    lines.append("")
    lines.append("---\n")
    lines.append(section_interactions(data.get("interactions", [])))
    lines.append("")
    lines.append("---\n")
    lines.append(section_summary())
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = None
    if "-o" in sys.argv:
        idx = sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    report = merge_report(data)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"✅ 报告已保存: {output_path}")
        print(f"   大小: {len(report)} 字符")
    else:
        print(report)

    # Output JSON summary for the agent to parse
    summary = {
        "stock": f"{stock_name}({stock_code})" if (stock_name := data.get("stock_name")) and (stock_code := data.get("stock_code")) else "unknown",
        "sections": 5,
        "chars": len(report),
        "announcements": len(data.get("announcements", [])),
        "research_reports": len(data.get("research_reports", [])),
        "interactions": len(data.get("interactions", [])),
        "summary_only": 0,
    }
    print(f"\n--- REPORT SUMMARY ---\n{json.dumps(summary, ensure_ascii=False)}\n--- END SUMMARY ---")


if __name__ == "__main__":
    main()
