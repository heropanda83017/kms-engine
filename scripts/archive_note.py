#!/usr/bin/env python3
"""
笔记归档工具 — 笔记完成后自动执行分类、更新索引、提取术语
用法: python archive_note.py <笔记.md路径>
"""

import os, sys, re, shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR
XHS_BASE = WIKI_DIR / "06-reading-notes" / "晓辉博士"
WIKI_BASE = WIKI_DIR

CATEGORY_MAP = {
    "Scaling Law": "03-core-ai", "大模型": "03-core-ai", "算法": "03-core-ai",
    "训练": "03-core-ai", "推理": "03-core-ai",
    "算力": "08-investment", "HBM": "08-investment", "数据中心": "08-investment",
    "芯片": "08-investment", "公司研究": "08-investment", "Anthropic": "08-investment",
    "OpenAI": "08-investment", "投资": "08-investment",
    "组织文化": "07-practices", "管理": "07-practices",
    "应用": "05-applications", "AI经济": "05-applications",
    "理论": "01-theory", "基础": "02-fundamentals",
}


def parse_note(note_path):
    content = Path(note_path).read_text(encoding="utf-8")
    title_m = re.search(r"^# (.+)$", content, re.MULTILINE)
    tags_m = re.search(r"tags:\s*\[(.+?)\]", content)
    source_m = re.search(r"source:\s*(.+)", content)
    date_m = re.search(r"date:\s*(.+)", content)
    
    title = title_m.group(1).strip() if title_m else Path(note_path).stem
    tags = [t.strip() for t in tags_m.group(1).split(",")] if tags_m else []
    source = source_m.group(1).strip() if source_m else ""
    note_date = date_m.group(1).strip() if date_m else datetime.now().strftime("%Y-%m-%d")
    
    return {"title": title, "tags": tags, "source": source, "date": note_date,
            "content": content, "path": note_path, "safe_name": Path(note_path).stem}


def classify(note):
    for tag in note["tags"]:
        for keyword, target_dir in CATEGORY_MAP.items():
            if keyword.lower() in tag.lower():
                return target_dir
    for keyword, target_dir in CATEGORY_MAP.items():
        if keyword.lower() in note["title"].lower():
            return target_dir
    return "06-reading-notes"


def update_catalog(note, category):
    catalog_path = XHS_BASE / "索引" / "catalog.md"
    if not catalog_path.exists():
        return
    content = catalog_path.read_text(encoding="utf-8")
    tags_str = ", ".join(note["tags"])
    note_rel = f"学习笔记/{note['safe_name']}.md"
    transcribe_path = XHS_BASE / "原始转写" / f"{note['safe_name'].replace('_笔记','_转写')}.txt"
    transcribe_rel = f"原始转写/{transcribe_path.name}" if transcribe_path.exists() else "N/A"
    
    new_row = f"| {note['date']} | [{note['title']}](#) | {category} | {tags_str} | [笔记]({note_rel}) | [转写]({transcribe_rel}) |"
    lines = content.split("\n")
    insert_pos = next((i+1 for i, l in enumerate(lines) if l.startswith("| ---")), len(lines))
    lines.insert(insert_pos, new_row)
    
    note_count = len([l for l in lines if l.startswith("| 202")])
    for i, l in enumerate(lines):
        if "笔记本数:" in l:
            lines[i] = f"> 更新时间: {datetime.now().strftime('%Y-%m-%d')} | 笔记本数: {note_count}"
    
    catalog_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  -> catalog updated ({note_count} notes)")


def copy_to_wiki(note_path, category):
    target_dir = WIKI_BASE / category
    target_dir.mkdir(exist_ok=True)
    stem = Path(note_path).stem.replace("_笔记", "")
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
    date_prefix = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
    target_name = f"{date_prefix}_晓辉博士_{stem.replace('_笔记','')}.md"
    shutil.copy2(note_path, str(target_dir / target_name))
    print(f"  -> copied to wiki/{category}/{target_name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python archive_note.py <note.md>")
        sys.exit(1)
    note_path = Path(sys.argv[1])
    if not note_path.exists():
        print(f"Error: {note_path} not found")
        sys.exit(1)
    
    note = parse_note(note_path)
    print(f"Title: {note['title']}")
    print(f"Tags: {note['tags']}")
    category = classify(note)
    print(f"Category: -> wiki/{category}/")
    update_catalog(note, category)
    copy_to_wiki(note_path, category)
    print("Done")
