#!/usr/bin/env python3
"""
book_to_skill.py — 从读书笔记自动生成 Hermes SKILL.md

用法:
  python3 book_to_skill.py <笔记路径> [--name 技能名] [--dry-run]

从 wiki 读书笔记中提取核心框架 → 生成 skills/books/<书名>/SKILL.md
"""
import re, json, sys
from pathlib import Path
from _path_setup import WIKI_DIR

SKILLS_DIR = Path.home() / ".hermes" / "profiles" / "ai-investor" / "skills" / "books"
WIKI_DIR = WIKI_DIR / "05-读书笔记"


def extract_book_info(content: str) -> dict:
    """从笔记 frontmatter 和正文提取书籍信息"""
    info = {"title": "", "author": "", "tags": [], "core_framework": "", "key_concepts": []}
    
    # Frontmatter
    fm = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm:
        for line in fm.group(1).split("\n"):
            if line.startswith("title:"):
                info["title"] = line.split(":", 1)[1].strip().strip('"')
            if line.startswith("tags:"):
                tags_match = re.findall(r"- (\S+)", fm.group(1))
                if tags_match:
                    info["tags"] = [t for t in tags_match if t not in ("-", "")]
    
    # Author from 来源 line
    src_match = re.search(r">\s*来源[：:]\s*(.+?)(?:\n|$)", content)
    if src_match:
        info["source"] = src_match.group(1).strip()
    
    # Extract section headers as framework
    sections = re.findall(r"^###+\s+(.+)$", content, re.MULTILINE)
    info["sections"] = sections[:10]
    
    # Extract bold definitions
    definitions = re.findall(r"\*\*(.+?)\*\*[=：:]\s*(.+?)(?:\n|$)", content)
    info["definitions"] = [(d[0], d[1].strip()) for d in definitions[:5]]
    
    # Extract key quotes
    quotes = re.findall(r">\s*(.+?)(?:\n|$)", content)
    info["quotes"] = [q.strip() for q in quotes if len(q.strip()) > 10][:5]
    
    return info


def generate_skill_md(info: dict, note_path: str) -> str:
    """生成 SKILL.md 内容"""
    title = info.get("title", "未知书籍")
    short_name = title.replace("：", ":").split(":")[0].strip() if "：" in title or ":" in title else title
    short_name = short_name[:20]
    
    tags = info.get("tags", [])
    tags_str = ", ".join(tags[:8]) if tags else "读书笔记"
    
    # Build description
    desc_parts = [f"用《{short_name}》的视角分析问题。"]
    if info.get("definitions"):
        core = info["definitions"][0]
        desc_parts.append(f"核心：{core[0]} — {core[1][:40]}")
    desc_parts.append(f"说「用{short_name}的视角」「{short_name}分析」时加载。详细内容在 references/ 按需加载。")
    
    description = " ".join(desc_parts)
    
    # Build trigger words
    triggers = [f"用{short_name}的视角", f"{short_name}分析", f"{short_name}怎么看"]
    if "觉察" in short_name:
        triggers = ["觉察一下", "用觉察之道的视角", "从觉察的角度看", "觉察分析"]
    
    # Build references content
    ref_lines = []
    if info.get("definitions"):
        ref_lines.append("## 核心概念")
        for name, desc in info["definitions"]:
            ref_lines.append(f"- **{name}**：{desc}")
    
    if info.get("quotes"):
        ref_lines.append("\n## 金句")
        for q in info["quotes"]:
            ref_lines.append(f"> {q}")
    
    if info.get("sections"):
        ref_lines.append("\n## 框架")
        for s in info["sections"]:
            ref_lines.append(f"- {s}")
    
    return f"""---
name: {short_name}
description: >-
  {description}
trigger:
{chr(10).join(f'  - {t}' for t in triggers)}
version: 1.0.0
metadata:
  hermes:
    tags: [{tags_str}]
    related_skills: [book-note-maker, systematic-learning]
---

# {short_name} — 认知框架 Skill

> 来源：{info.get('source', '未知')}
> 转化自：{note_path}

## 核心框架

{info.get('core_framework', '详见 references/ 目录')}

## 使用方式

### 分析一个决策/问题

```
用户说：「用{short_name}的视角看看这个决策」
→ 加载本 Skill
→ 用{short_name}的核心框架分析
```

## 详细文档

> 完整笔记见 `references/读书笔记.md`
"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="从读书笔记生成 Hermes SKILL.md")
    parser.add_argument("note_path", help="读书笔记 Markdown 文件路径")
    parser.add_argument("--name", help="技能名（默认从标题提取）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    args = parser.parse_args()
    
    note_path = Path(args.note_path)
    if not note_path.exists():
        print(f"❌ 笔记文件不存在: {note_path}")
        sys.exit(1)
    
    content = note_path.read_text(encoding="utf-8", errors="replace")
    info = extract_book_info(content)
    
    if args.name:
        info["title"] = args.name
    
    skill_md = generate_skill_md(info, str(note_path))
    
    skill_name = info.get("title", "未知").replace("：", ":").split(":")[0].strip()[:20]
    skill_dir = SKILLS_DIR / skill_name
    skill_path = skill_dir / "SKILL.md"
    ref_dir = skill_dir / "references"
    
    if args.dry_run:
        print(f"📄 预览: {skill_path}")
        print("=" * 50)
        print(skill_md)
        print("=" * 50)
        print(f"✅ dry-run 完成，未写入")
        return
    
    skill_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)
    
    skill_path.write_text(skill_md, encoding="utf-8")
    
    # Copy original note as reference
    ref_path = ref_dir / "读书笔记.md"
    ref_path.write_text(content, encoding="utf-8")
    
    print(f"✅ Skill 已生成: {skill_path}")
    print(f"📎 参考文件: {ref_path}")
    print(f"💡 现在可以说「用{skill_name}的视角分析一下」来使用")


if __name__ == "__main__":
    main()
