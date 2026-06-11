#!/usr/bin/env python3
"""知识图谱导航页生成器

扫描 wiki 笔记的 frontmatter，生成：
1. 图谱索引.md — 按域分组的知识导航页
2. 孤岛笔记报告 — 0入链/0出链的笔记
3. 热点概念 — 被最多笔记引用的 tags

用法:
  python scripts/knowledge_graph.py         # 生成图谱索引
  python scripts/knowledge_graph.py --watch # 增量模式
"""

import sys, re, json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR


def parse_frontmatter(content):
    """解析笔记 frontmatter，返回 dict"""
    fm = {"title": "", "type": "reference", "domain": "未分类", "tags": [], "source": "自研"}
    
    # === 优先级 1: 从 YAML frontmatter 读取 ===
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            yaml_block = content[3:end].strip()
            for line in yaml_block.split('\n'):
                line = line.strip()
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key == "tags":
                        val = val.strip("[]")
                        fm["tags"] = [t.strip() for t in val.split(",") if t.strip()]
                    elif key in ("title", "type", "domain", "source", "created", "updated"):
                        fm[key] = val
    
    # === 优先级 2: 如果 frontmatter 无 title，从 H1 提取 ===
    if not fm["title"]:
        m = re.search(r"^#\\s+(.+)", content, re.MULTILINE)
        if m:
            fm["title"] = m.group(1).strip()
        else:
            fm["title"] = "(无标题)"
    
    # === 优先级 3: 如果 domain 仍是默认值，从目录路径推断 ===
    if fm["domain"] == "未分类" and "path" in fm:
        parts = fm["path"].split("/")
        if parts:
            dir_map = {
                "01-theory": "AI基础理论",
                "02-fundamentals": "AI基础理论",
                "03-core-ai": "AI核心技术",
                "04-tools": "工具与方法论",
                "05-applications": "AI应用",
                "06-reading-notes": "读书笔记",
                "07-practices": "工具与方法论",
                "08-investment": "投资研究",
            }
            first = parts[0]
            if first in dir_map:
                fm["domain"] = dir_map[first]
            elif fm["path"].endswith("图谱索引.md"):
                fm["domain"] = "系统文档"
    
    return fm


def collect_notes():
    """扫描 wiki，收集所有笔记的 frontmatter"""
    notes = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f) or f.name == "CHANGELOG.md":
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        fm = parse_frontmatter(content)
        rel = str(f.relative_to(WIKI_DIR)).replace("\\", "/")
        fm["path"] = rel
        fm["filename"] = f.name
        notes.append(fm)
    return notes


def build_link_graph(notes):
    """构建笔记间引用关系图"""
    titles = {}
    for n in notes:
        t = n.get("title", "").strip()
        if t:
            titles[t] = n
    
    outlinks = {}
    inlinks = defaultdict(list)
    
    for n in notes:
        path = n["path"]
        filepath = WIKI_DIR / path.replace("/", "\\")
        if not filepath.exists():
            print(f"  ⚠️ 文件不存在: {filepath}")
            outlinks[path] = set()
            continue
        
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        refs = set()
        
        for title in titles:
            if title == n.get("title", ""):
                continue
            if not title:
                continue
            # Check both plain text and [[wikilink]] format
            if title in content or f"[[{title}]]" in content:
                refs.add(title)
                inlinks[title].append(path)
        
        outlinks[path] = refs

    return outlinks, inlinks


def generate_index(notes, outlinks, inlinks):
    """生成图谱索引.md"""
    # 按域分组
    by_domain = defaultdict(list)
    for n in notes:
        by_domain[n["domain"]].append(n)
    
    # 按类型分组
    by_type = defaultdict(int)
    for n in notes:
        by_type[n["type"]] += 1
    
    # 热点概念
    tag_freq = defaultdict(int)
    for n in notes:
        for t in n["tags"]:
            tag_freq[t] += 1
    hot_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:20]
    
    # 孤岛笔记 (0 outlinks)
    orphans = [n for n in notes if n["path"] not in outlinks or len(outlinks.get(n["path"], set())) == 0]
    
    # 桥接节点 (被最多跨域引用的笔记)
    bridge_scores = defaultdict(int)
    for title, referrers in inlinks.items():
        domains = set()
        for ref_path in referrers:
            for n in notes:
                if n["path"] == ref_path:
                    domains.add(n["domain"])
                    break
        if len(domains) > 1:
            bridge_scores[title] = len(domains) * len(referrers)
    
    top_bridges = sorted(bridge_scores.items(), key=lambda x: -x[1])[:10]
    
    # 生成 index
    lines = []
    lines.append("---")
    lines.append("title: 知识图谱导航")
    lines.append("type: reference")
    lines.append("domain: 系统文档")
    lines.append("tags: [导航, 索引, 知识图谱]")
    lines.append("source: KMS Engine")
    lines.append(f"created: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("---")
    lines.append("")
    lines.append("# 🗺️ 知识图谱导航")
    lines.append("")
    lines.append(f"> 自动生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(notes)} 篇笔记 | {len(by_domain)} 个知识域")
    lines.append("")
    
    # 全景
    lines.append("## 📊 知识全景")
    lines.append("")
    lines.append("| 知识域 | 篇数 | 类型分布 |")
    lines.append("|:-------|:----:|:---------|")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        types = defaultdict(int)
        for n in items:
            types[n["type"]] += 1
        type_str = " ".join(f"{t}:{c}" for t, c in sorted(types.items(), key=lambda x: -x[1]))
        bar = "█" * min(len(items) // 2, 20)
        lines.append(f"| **{domain}** | {len(items)} | {type_str} |")
    
    lines.append("")
    lines.append("## 📂 按知识域导航")
    lines.append("")
    
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        lines.append(f"### {domain} ({len(items)}篇)")
        lines.append("")
        for n in items:
            tags_str = " ".join(f"`{t}`" for t in n["tags"][:3])
            type_badge = f"[{n['type']}]"
            src_badge = f"({n['source']})" if n["source"] != "自研" else ""
            lines.append(f"- {type_badge} **[{n['title']}]({n['path']})** {src_badge} {tags_str}")
        lines.append("")
    
    # 热点概念
    lines.append("---")
    lines.append("## 🔥 热点概念 Top 20")
    lines.append("")
    lines.append("| 概念 | 出现频次 |")
    lines.append("|:-----|:--------:|")
    for tag, freq in hot_tags:
        bar = "█" * min(freq, 20)
        lines.append(f"| {tag} | {freq} {bar} |")
    lines.append("")
    
    # 桥接节点
    if top_bridges:
        lines.append("---")
        lines.append("## 🌉 桥接节点 (跨域引用最多)")
        lines.append("")
        lines.append("| 笔记 | 覆盖域数 | 被引用数 |")
        lines.append("|:-----|:--------:|:--------:|")
        for title, score in top_bridges:
            matched = [n for n in notes if n["title"] == title]
            n = matched[0] if matched else {}
            path = n.get("path", "")
            domains_count = len(set(n.get("domain", "") for n in notes if n["title"] in inlinks))
            ref_count = len(inlinks.get(title, []))
            lines.append(f"| [{title}]({path}) | {domains_count} | {ref_count} |")
        lines.append("")
    
    # 孤岛笔记
    if orphans:
        lines.append("---")
        lines.append(f"## 🏝️ 孤岛笔记 ({len(orphans)}篇 — 0条出链)")
        lines.append("")
        lines.append("> 这些笔记没有链接到其他笔记，建议审核后补充关联")
        lines.append("")
        for n in orphans:
            lines.append(f"- [{n['title']}]({n['path']}) — {n['domain']}")
        lines.append("")
    
    # 结构图 (ASCII)
    lines.append("---")
    lines.append("## 🧭 知识结构")
    lines.append("")
    lines.append("```")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        lines.append(f"{domain}")
        for n in items[:5]:  # 最多5个
            lines.append(f"  ├── {n['title'][:30]}")
        if len(items) > 5:
            lines.append(f"  └── ... 还有 {len(items)-5} 篇")
        lines.append("")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append(f"> 由 KMS knowledge_graph.py 自动生成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    return "\\n".join(lines)


def main():
    print("=" * 50)
    print("  KMS — 知识图谱生成")
    print("=" * 50)
    
    notes = collect_notes()
    print(f"  📊 扫描: {len(notes)} 篇笔记")
    
    # Build link graph
    outlinks, inlinks = build_link_graph(notes)
    linking_notes = sum(1 for v in outlinks.values() if v)
    print(f"  🔗 引用关系: {linking_notes} 篇有出链, {len(inlinks)} 个概念被引用")
    
    # Generate index
    index_content = generate_index(notes, outlinks, inlinks)
    index_path = WIKI_DIR / "图谱索引.md"
    index_path.write_text(index_content, encoding="utf-8")
    print(f"  ✅ wiki/图谱索引.md 已生成 ({index_path.stat().st_size/1024:.1f} KB)")
    
    # Stats
    orphans = [n for n in notes if n["path"] not in outlinks or len(outlinks.get(n["path"], set())) == 0]
    print(f"  🏝️ 孤岛笔记: {len(orphans)} 篇")
    
    tag_freq = defaultdict(int)
    for n in notes:
        for t in n["tags"]:
            tag_freq[t] += 1
    print(f"  🔥 热点概念 Top 5:")
    for tag, freq in sorted(tag_freq.items(), key=lambda x: -x[1])[:5]:
        print(f"      {tag}: {freq}次")


if __name__ == "__main__":
    main()