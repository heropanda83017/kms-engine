#!/usr/bin/env python3
"""
填充学习笔记 v2 — 读取原始转写，调用LLM结构化提取知识点
用法: python fill_note.py <转写文件路径>
"""

import os, sys, re, json, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR
NOTE_DIR = WIKI_DIR / "06-reading-notes" / "晓辉博士"
def _build_frontmatter(title, source="自研"):
    """生成笔记 frontmatter"""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d")
    return f"""---
title: {title}
type: lecture
domain: 读书笔记
tags: []
source: {source}
created: {now}
updated: {now}
---"""





def parse_transcript(transcript_path: str) -> dict:
    with open(transcript_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Parse header
    title = re.search(r"标题:\s*(.+)", content)
    source = re.search(r"来源:\s*(.+)", content)
    duration = re.search(r"时长:\s*(.+)", content)
    
    # Extract plain text (remove timestamps)
    lines = content.split("\n")
    text_parts = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("标题:") or line.startswith("来源:") or \
           line.startswith("时长:") or line.startswith("语言:") or line.startswith("="):
            continue
        clean = re.sub(r"^\[\d+:\d+\]\s*", "", line)
        if clean:
            text_parts.append(clean)
    
    return {
        "title": title.group(1).strip() if title else "未知标题",
        "source": source.group(1).strip() if source else "",
        "duration": duration.group(1).strip() if duration else "",
        "plain_text": "\n".join(text_parts),
        "full_text": content,
    }


def generate_note(data: dict) -> str:
    """生成LLM提示，由Agent读取后注入模型完成填充"""
    
    prompt = f"""# 结构化学学习笔记任务

## 视频信息
- **标题:** {data['title']}
- **来源:** {data['source']}
- **时长:** {data['duration']}

## 转写原文
{data['plain_text']}

---

## 要求
请根据以上转写内容，生成结构化学习笔记，包含以下章节：

### 核心知识点（2-4个）
每个知识点用【概念/事件】→【解释】→【投资/学习含义】三段式。

### 关键概念表
| 概念 | 解释 |
提取转写中出现的所有专业术语、公司名、模型名、人物名。

### 实用建议/行动项
可直接落地的操作、工具推荐、关注方向。

### 延伸学习方向
值得进一步研究的相关话题。

## 输出格式
直接输出 markdown，不要额外解释。
"""
    return prompt


def main():
    parser = argparse.ArgumentParser(description="填充学习笔记")
    parser.add_argument("transcript_path", help="转写文件路径")
    args = parser.parse_args()
    
    if not os.path.exists(args.transcript_path):
        print(f"错误: 文件不存在 {args.transcript_path}")
        sys.exit(1)
    
    data = parse_transcript(args.transcript_path)
    prompt = generate_note(data)
    
    # 输出给LLM填充
    print("# 学习笔记填充请求")
    print()
    print(prompt)


if __name__ == "__main__":
    main()
