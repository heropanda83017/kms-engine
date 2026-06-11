#!/usr/bin/env python3
"""Wiki 内容同步检查器

检测 wiki 投资体系页面是否与 investment-engine 代码实际状态一致。
自动标记过时/历史/当前状态。

用法:
  python scripts/wiki_sync_check.py               # 扫描并报告
  python scripts/wiki_sync_check.py --mark         # 自动标记 frontmatter
  python scripts/wiki_sync_check.py --report       # 只输出报告,不修改
"""

import sys, re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR

# === 过时关键词 — 引用旧系统 ===
OLD_KEYWORDS = [
    "blackhorse", "data-source-hub", "data_source_hub",
    "DSH_", "dsh_", "黑马量化"
]

# === 当前关键词 — 引用现行系统 ===
CURRENT_KEYWORDS = [
    "investment-engine", "investment_engine", "IE_", "ie_",
    "wudao", "mcp_servers", "tickflow_provider",
    "factor_tracker", "backtest_engine", "strategy_pipeline",
    "position_sizing", "risk_manager",
]

# === 分类规则 ===
CATEGORIES = {
    "审计报告": ["审计", "audit", "架构审查", "评审"],
    "设计文档": ["ARCH:", "ARCH ", "架构设计"],
    "数据源配置": ["数据源", "信源", "baostock", "tushare"],
    "回测报告": ["回测", "backtest", "回撤"],
    "系统架构": ["体系", "架构", "系统设计"],
    "工具指南": ["指南", "教程", "配置"],
    "分析报告": ["分析", "研究", "报告", "review"],
}


def check_file(filepath):
    """检测单篇笔记的同步状态"""
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    rel = str(filepath.relative_to(WIKI_DIR)).replace("\\", "/")
    
    refs_old = [kw for kw in OLD_KEYWORDS if kw in content.lower()]
    refs_current = [kw for kw in CURRENT_KEYWORDS if kw in content.lower()]
    
    # Categorize
    category = "其他"
    content_lower = content.lower()
    for cat, keywords in CATEGORIES.items():
        if any(kw in content_lower for kw in keywords):
            category = cat
            break
    
    # Determine status
    if refs_old and not refs_current:
        status = "outdated"
    elif refs_old and refs_current:
        status = "mixed"
    else:
        status = "current"
    
    return {
        "path": rel,
        "status": status,
        "category": category,
        "old_refs": refs_old[:3],
        "current_refs": refs_current[:3],
        "size": filepath.stat().st_size,
    }


def mark_frontmatter(filepath, status):
    """在 frontmatter 中标记 status 字段（安全的 frontmatter 操作）"""
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    
    fm_start = content.find("---")
    if fm_start != 0:
        # No frontmatter, add one
        new_content = f"---\\nstatus: {status}\\n---\\n\\n" + content
        filepath.write_text(new_content, encoding="utf-8")
        return True
    
    fm_end = content.find("---", 3)
    if fm_end == -1:
        return False
    
    fm_block = content[3:fm_end]
    
    # Check if status already exists
    if re.search(r"^status:", fm_block, re.MULTILINE):
        new_fm = re.sub(r"^status:.*$", f"status: {status}", fm_block, flags=re.MULTILINE)
    else:
        lines = fm_block.strip().split("\\n")
        lines.append(f"status: {status}")
        new_fm = "\n".join(lines)
    
    new_content = "---" + "\n" + new_fm + "\n" + "---" + content[fm_end+3:]
    filepath.write_text(new_content, encoding="utf-8")
    return True


def generate_report(results):
    """生成同步状态报告"""
    lines = []
    lines.append("---")
    lines.append(f"title: Wiki 同步状态报告")
    lines.append("type: report")
    lines.append("domain: 系统文档")
    lines.append("tags: [同步, 状态]")
    lines.append("source: KMS Engine")
    lines.append(f"created: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"updated: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("---")
    lines.append("")
    lines.append("# Wiki 同步状态报告")
    lines.append(f"> 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## 概览")
    lines.append("")
    
    by_status = {"current": 0, "mixed": 0, "outdated": 0}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    
    lines.append(f"| 状态 | 数量 | 含义 |")
    lines.append(f"|:----|:----:|:-----|")
    lines.append(f"| ✅ 当前 | {by_status.get('current', 0)} | 引用现行 investment-engine |")
    lines.append(f"| ⚠️ 混合 | {by_status.get('mixed', 0)} | 新旧系统均引用 |")
    lines.append(f"| ❌ 过时 | {by_status.get('outdated', 0)} | 仅引用旧系统 (blackhorse/data-source-hub) |")
    lines.append("")
    
    if by_status.get("outdated", 0) > 0:
        lines.append("## ❌ 过时页面 (需处理)")
        lines.append("")
        lines.append("| 页面 | 分类 | 过时引用 |")
        lines.append("|:-----|:----|:---------|")
        for r in results:
            if r["status"] == "outdated":
                refs = ", ".join(r["old_refs"])
                lines.append(f"| {r['path']} | {r['category']} | `{refs}` |")
        lines.append("")
    
    if by_status.get("mixed", 0) > 0:
        lines.append("## ⚠️ 混合页面 (需审核)")
        lines.append("")
        lines.append("| 页面 | 分类 | 旧引用 | 当前引用 |")
        lines.append("|:-----|:----|:-------|:---------|")
        for r in results:
            if r["status"] == "mixed":
                old = ", ".join(r["old_refs"])
                cur = ", ".join(r["current_refs"])
                lines.append(f"| {r['path']} | {r['category']} | {old} | {cur} |")
        lines.append("")
    
    lines.append("## 分类统计")
    lines.append("")
    by_cat = {}
    for r in results:
        cat = r["category"]
        if cat not in by_cat:
            by_cat[cat] = {"current": 0, "mixed": 0, "outdated": 0}
        by_cat[cat][r["status"]] = by_cat[cat].get(r["status"], 0) + 1
    
    for cat, stats in sorted(by_cat.items()):
        current = stats.get("current", 0)
        outdated = stats.get("outdated", 0)
        lines.append(f"- **{cat}**: ✅{current} ❌{outdated}")
    lines.append("")
    
    lines.append("## 建议")
    lines.append("")
    lines.append(f"1. ❌ 过时页面 ({by_status.get('outdated', 0)} 篇) → 标记为 `status: historical` 并存档")
    lines.append(f"2. ⚠️ 混合页面 ({by_status.get('mixed', 0)} 篇) → 审核后移除旧引用")
    lines.append(f"3. 运行 `kms sync-check --mark` 自动标记状态")
    lines.append("")
    
    return "\n".join(lines)


def main():
    mark = "--mark" in sys.argv
    report_only = "--report" in sys.argv
    
    # Scan all wiki .md files
    notes = sorted(WIKI_DIR.rglob("*.md"))
    notes = [n for n in notes if ".obsidian" not in str(n)]
    
    results = [check_file(n) for n in notes]
    invest_only = [r for r in results if r["status"] != "current"]
    
    if report_only or not mark:
        report = generate_report(invest_only)
        report_path = WIKI_DIR / "sync状态报告.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"✅ 报告已生成: {report_path}")
    
    if mark:
        marked = 0
        for n in notes:
            rel = str(n.relative_to(WIKI_DIR)).replace("\\", "/")
            # Find matching result
            for r in invest_only:
                if r["path"] == rel:
                    if mark_frontmatter(n, r["status"]):
                        marked += 1
                    break
        print(f"✅ 已标记 {marked} 篇笔记的 status 字段")
    
    # Print summary to stdout
    for r in invest_only:
        icon = {"current": "✅", "mixed": "⚠️", "outdated": "❌"}
        print(f"  {icon[r['status']]} [{r['category']}] {r['path']}")
    
    by_status = {"current": 0, "mixed": 0, "outdated": 0}
    for r in invest_only:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print(f"\n总计投资体系相关: {len(invest_only)} 篇")
    print(f"  ✅ 当前: {by_status.get('current', 0)}")
    print(f"  ⚠️ 混合: {by_status.get('mixed', 0)}")
    print(f"  ❌ 过时: {by_status.get('outdated', 0)}")


if __name__ == "__main__":
    main()