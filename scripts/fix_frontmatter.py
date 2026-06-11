#!/usr/bin/env python3
"""为 wiki 所有笔记注入标准 frontmatter

用法:
  python scripts/fix_frontmatter.py --dry-run   # 预览（默认）
  python scripts/fix_frontmatter.py --apply     # 实际写入
  python scripts/fix_frontmatter.py --report    # 只输出统计报告
"""

import sys, re, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, CONFIG_DIR

# === type 推断规则（基于文件名和目录） ===
TYPE_RULES = [
    ("晓辉博士", "lecture"),
    ("lecture", "lecture"),
    ("研报_", "research"),
    ("研報_", "research"),
    ("研究", "research"),
    ("见解_", "insight"),
    ("insight", "insight"),
    ("review", "reference"),
    ("審查", "reference"),
    ("审查", "reference"),
    ("指南", "reference"),
    ("模板", "reference"),
    ("template", "reference"),
    ("README", "reference"),
    ("CHANGELOG", "reference"),
    ("笔记", "lecture"),
    ("note", "lecture"),
    ("框架", "reference"),
    ("framework", "reference"),
    ("图谱", "reference"),
    ("concept", "reference"),
]

# === domain 推断规则（基于目录路径） ===
DOMAIN_RULES = {
    "01-theory": "AI基础理论",
    "02-fundamentals": "AI基础理论",
    "03-core-ai": "AI核心技术",
    "04-tools": "工具与方法论",
    "05-applications": "AI应用",
    "06-reading-notes": "读书笔记",
    "07-practices": "工具与方法论",
    "08-investment": "投资研究",
    "root": "系统文档",
}

# === source 推断规则 ===
SOURCE_RULES = [
    ("晓辉博士", "晓辉博士"),
    ("research_report", "研报"),
    ("研报_", "研报"),
    ("研報_", "研报"),
    ("V4Pro", "V4 Pro 审计"),
    ("claude-code", "V4 Pro 审计"),
    ("迪哥", "迪哥课程"),
]


def infer_type(filepath, content):
    """基于文件名和内容推断笔记类型"""
    stem = filepath.stem
    rel = str(filepath.relative_to(WIKI_DIR))
    
    for pattern, ntype in TYPE_RULES:
        if pattern in rel or pattern in stem:
            return ntype
    
    # 内容启发式
    if re.search(r"^##\s+核心结论|^##\s+投资逻辑|PE\s+|估值|ROE", content, re.MULTILINE):
        return "research"
    if re.search(r"^##\s+核心知识点|^##\s+关键概念", content, re.MULTILINE):
        return "lecture"
    
    return "reference"


def infer_domain(filepath):
    """基于目录路径推断知识域"""
    rel = str(filepath.relative_to(WIKI_DIR))
    parts = rel.split("\\")
    root_dir = parts[0] if parts else "root"
    return DOMAIN_RULES.get(root_dir, "未分类")


def infer_source(filepath, content):
    """基于文件名和内容推断来源"""
    stem = filepath.stem
    rel = str(filepath.relative_to(WIKI_DIR))
    
    for pattern, source in SOURCE_RULES:
        if pattern in rel or pattern in stem:
            return source
    
    # 只从 frontmatter 提取 source，不扫描正文（避免脏匹配）
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_block = content[3:end]
            m = re.search(r"^source[:：]\s*(.+)", fm_block, re.MULTILINE)
            if m:
                return m.group(1).strip()
    
    return "自研"


def infer_tags(filepath, content):
    """提取标签：文件名中的关键词 + 内容中的标签"""
    tags = set()
    rel = str(filepath.relative_to(WIKI_DIR))
    
    # 文件名关键词
    stem = filepath.stem
    for kw in ["HBM", "AI", "GPU", "Scaling", "Anthropic", "DeepSeek", "OpenAI",
                "Transformer", "Agent", "RAG", "量化", "策略", "回测", "因子",
                "估值", "财务", "宏观", "行业", "芯片", "算力", "光模块",
                "数据中心", "机器人", "新能源", "半导体", "英伟达", "华为"]:
        if kw.lower() in stem.lower() or kw.lower() in rel.lower():
            tags.add(kw)
    
    # 从已有 frontmatter 提取
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        existing_fm = fm_match.group(1)
        tags_m = re.search(r"tags:\s*\[(.*?)\]", existing_fm)
        if tags_m:
            for t in tags_m.group(1).split(","):
                tags.add(t.strip())
    
    # 从正文 H1 标题提取
    title_m = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else stem
    for kw in ["HBM", "AI", "GPU", "Scaling", "Anthropic"]:
        if kw.lower() in title.lower():
            tags.add(kw)
    
    return sorted(tags, key=lambda x: -len(x))[:5]  # 最多5个


def build_frontmatter(filepath, content):
    """为单篇笔记构建 frontmatter"""
    title_m = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else filepath.stem
    
    ntype = infer_type(filepath, content)
    domain = infer_domain(filepath)
    source = infer_source(filepath, content)
    tags = infer_tags(filepath, content)
    now = datetime.now().strftime("%Y-%m-%d")
    
    fm = {
        "title": title,
        "type": ntype,
        "domain": domain,
        "tags": tags,
        "source": source,
        "created": now,
        "updated": now,
    }
    return fm


def apply_frontmatter(filepath, fm):
    """将 frontmatter 注入到笔记文件"""
    content = filepath.read_text(encoding="utf-8")
    
    # 生成 YAML frontmatter
    yaml_lines = ["---"]
    yaml_lines.append(f"title: {fm['title']}")
    yaml_lines.append(f"type: {fm['type']}")
    yaml_lines.append(f"domain: {fm['domain']}")
    yaml_lines.append(f"tags: [{', '.join(fm['tags'])}]")
    yaml_lines.append(f"source: {fm['source']}")
    yaml_lines.append(f"created: {fm['created']}")
    yaml_lines.append(f"updated: {fm['updated']}")
    yaml_lines.append("---")
    yaml_block = "\n".join(yaml_lines)
    
    # 检查是否已有 frontmatter
    if content.startswith("---"):
        # 替换现有 frontmatter
        end = content.find("---", 3)
        if end != -1:
            rest = content[end + 3:].lstrip("\\n")
            return yaml_block + "\\n" + rest
    
    # 新增 frontmatter
    return yaml_block + "\\n" + content


def main():
    dry_run = "--apply" not in sys.argv
    report_only = "--report" in sys.argv
    
    notes = sorted(WIKI_DIR.rglob("*.md"))
    notes = [n for n in notes if ".obsidian" not in str(n)]
    
    if report_only:
        types = {}
        domains = {}
        sources = {}
        for n in notes:
            content = n.read_text(encoding="utf-8", errors="ignore")
            fm = build_frontmatter(n, content)
            types[fm["type"]] = types.get(fm["type"], 0) + 1
            domains[fm["domain"]] = domains.get(fm["domain"], 0) + 1
            sources[fm["source"]] = sources.get(fm["source"], 0) + 1
        
        print("=" * 50)
        print(f"  Frontmatter 统计报告 ({len(notes)} 篇)")
        print("=" * 50)
        print(f"\n📊 类型分布:")
        for t, c in sorted(types.items(), key=lambda x: -x[1]):
            print(f"    {t}: {c}篇")
        print(f"\n📊 领域分布:")
        for d, c in sorted(domains.items(), key=lambda x: -x[1]):
            print(f"    {d}: {c}篇")
        print(f"\n📊 来源分布:")
        for s, c in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"    {s}: {c}篇")
        return
    
    if dry_run:
        print(f"🔍 DRY RUN 模式 — 不写入文件")
        print(f"   运行 --apply 实际执行")
    
    modified = 0
    skipped = 0
    
    for n in notes:
        content = n.read_text(encoding="utf-8", errors="ignore")
        fm = build_frontmatter(n, content)
        
        if dry_run:
            has_fm = content.startswith("---")
            status = "已有 frontmatter" if has_fm else "将新增"
            print(f"  {'✅' if has_fm else '➕'} {fm['type']:>10s} | {fm['domain']:<12s} | {n.relative_to(WIKI_DIR)}")
            modified += 1
        else:
            new_content = apply_frontmatter(n, fm)
            if new_content != content:
                # Backup
                bak = n.with_suffix(n.suffix + ".bak")
                if not bak.exists():
                    n.rename(bak)
                n.write_text(new_content, encoding="utf-8")
                modified += 1
            else:
                skipped += 1
    
    action = "预览" if dry_run else "修改"
    print(f"\n✅ {action}完成: {modified} 篇{' (跳过 {skipped} 篇)' if skipped else ''}")


if __name__ == "__main__":
    main()