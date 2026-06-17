#!/usr/bin/env python3
"""
batch_fix_frontmatter.py — 批量修复 53 个无 frontmatter 文件的元数据

策略: 根据文件路径推断 type/domain/tags, 追加到文件头部。
不会覆盖已有 frontmatter (只处理不以 --- 开头的文件)。
"""

from pathlib import Path
from datetime import date
from _path_setup import WIKI_DIR

WIKI = WIKI_DIR

# 路径→frontmatter 推断映射
PATH_RULES = [
    # (path_parts, frontmatter_template)
    ("06-reading-notes/AI大模型前沿研究/", {
        "type": "note", "domain": "AI技术",
        "tags": ["LLM", "reading-notes"],
    }),
    ("06-reading-notes/build-your-own-x/", {
        "type": "note", "domain": "AI技术",
        "tags": ["project", "reading-notes"],
    }),
    ("06-reading-notes/code秘密花园/", {
        "type": "note", "domain": "AI技术",
        "tags": ["engineering", "reading-notes"],
    }),
    ("08-investment/00-系统/", {
        "type": "reference", "domain": "投资研究",
        "tags": ["system", "architecture"],
    }),
    ("08-investment/01-数据源与工具/", {
        "type": "reference", "domain": "投资研究",
        "tags": ["data-source", "tool"],
    }),
    ("08-investment/03-宏观与产业/", {
        "type": "research", "domain": "投资研究",
        "tags": ["macro", "industry-chain"],
    }),
    ("08-investment/04-因子研究/", {
        "type": "research", "domain": "投资研究",
        "tags": ["factor", "research"],
    }),
    ("08-investment/05-投资体系/策略/", {
        "type": "strategy", "domain": "投资研究",
        "tags": ["strategy", "investment-system"],
    }),
    ("08-investment/05-投资体系/衍生品/", {
        "type": "strategy", "domain": "投资研究",
        "tags": ["derivatives", "futures"],
    }),
    ("08-investment/05-投资体系/交易行为", {
        "type": "reference", "domain": "投资研究",
        "tags": ["trading-psychology", "behavior"],
    }),
    ("08-investment/05-投资体系/分析管线", {
        "type": "reference", "domain": "投资研究",
        "tags": ["pipeline", "investment-system"],
    }),
    ("08-investment/05-投资体系/多策略引擎", {
        "type": "reference", "domain": "投资研究",
        "tags": ["multi-strategy", "design"],
    }),
    ("08-investment/05-融资与政策/", {
        "type": "reference", "domain": "投资研究",
        "tags": ["policy", "financing"],
    }),
    ("08-investment/06-投研分析/外部借鉴记录/", {
        "type": "reference", "domain": "投资研究",
        "tags": ["external-reference", "learning"],
    }),
    ("08-investment/06-投研分析/个股候选池/", {
        "type": "research", "domain": "投资研究",
        "tags": ["candidate-pool", "screening"],
    }),
    ("08-investment/06-投研分析/每日复盘/", {
        "type": "review", "domain": "投资研究",
        "tags": ["daily-review", "market"],
    }),
    ("08-investment/06-投研分析/电话会议纪要/", {
        "type": "meeting", "domain": "投资研究",
        "tags": ["earnings-call", "transcript"],
    }),
    ("08-investment/06-投研分析/研报/", {
        "type": "research", "domain": "投资研究",
        "tags": ["company-report", "deep-research"],
    }),
    ("08-investment/06-投研分析/策略回测/", {
        "type": "research", "domain": "投资研究",
        "tags": ["backtest", "strategy"],
    }),
    ("root/EVOLUTION", {
        "type": "reference", "domain": "知识管理",
        "tags": ["system-evolution", "changelog"],
    }),
]


def infer_frontmatter(rel_path: str) -> dict | None:
    """根据文件路径推断 frontmatter"""
    for pattern, fm in PATH_RULES:
        if pattern in rel_path or rel_path.startswith(pattern.replace("root/", "")):
            title = Path(rel_path).stem
            # Clean title
            title = title.replace("_", " ").replace("-", " ").replace("  ", " ")
            fm_copy = dict(fm)
            fm_copy["title"] = title.strip()
            fm_copy["created"] = date.today().isoformat()
            return fm_copy
    return None


def format_frontmatter(fm: dict) -> str:
    """将 frontmatter dict 格式化为 YAML 字符串"""
    lines = ["---"]
    for k, v in fm.items():
        if k == "tags":
            lines.append(f"tags: [{', '.join(v)}]")
        elif isinstance(v, str):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def main():
    fixed = 0
    skipped = 0
    no_rule = 0

    for f in sorted(WIKI.rglob("*.md")):
        if ".bak" in str(f) or "/archive/" in str(f):
            continue
        rel = str(f.relative_to(WIKI))
        content = f.read_text(encoding="utf-8", errors="ignore")

        if content.startswith("---"):
            skipped += 1
            continue

        # Infer frontmatter
        fm = infer_frontmatter(rel)
        if fm is None:
            print(f"  ⚠️ 无匹配规则: {rel}")
            no_rule += 1
            continue

        # Prepend frontmatter
        fm_text = format_frontmatter(fm)
        new_content = fm_text + content
        f.write_text(new_content, encoding="utf-8")
        print(f"  ✅ {rel} → type={fm['type']}, tags={fm['tags']}")
        fixed += 1

    print(f"\n=== 完成 ===")
    print(f"  修复: {fixed}")
    print(f"  跳过(已有frontmatter): {skipped}")
    print(f"  无匹配规则: {no_rule}")


if __name__ == "__main__":
    main()
