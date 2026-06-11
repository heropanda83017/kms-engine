#!/usr/bin/env python3
"""
learn_to_note.py — 因子分析对话 → 结构化知识笔记

将分析对话中的发现、修复、洞察沉淀为 wiki 笔记，
支持"同因子更新"而非"同因子重复"。

用法:
  python learn_to_note.py <note_json>

note_json 格式:
{
  "factor": "capital-flow",          # 因子英文名（用作文件名）
  "title": "资金因子：金额归一化修复", # 中文标题
  "tags": ["资金流", "融资融券", "归一化"],
  "related_factors": ["capital", "volume"],
  "issues_found": [                   # 发现的问题
    {"problem": "净买入按绝对金额打分", "severity": "high",
     "fix": "改为按流通市值比例打分", "impact": "修正大/小盘股评分偏差"}
  ],
  "key_insights": [                   # 核心认知
    "绝对金额在不同市值公司之间不可比",
    "归一化到市值是最小可行方案",
    "大宗交易溢价率是有效信号"
  ],
  "code_changes": [                   # 代码变更
    {"file": "strategies/factor_capital_flow.py",
     "change": "net_buy归一化 + 大宗交易评分"}
  ],
  "data_fields_confirmed": [           # 确认的数据字段
    {"source": "block_trade", "fields": ["premium_pct", "vol", "amount"]},
    {"source": "margin_trading", "fields": ["rzye", "rqye"]}
  ],
  "open_questions": ["如何验证IC提升？"]  # 未解决的问题
}
"""

import sys, json, os, re
from pathlib import Path
from datetime import datetime

# ── 路径 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
from _path_setup import WIKI_DIR

FACTOR_NOTE_DIR = WIKI_DIR / "08-investment" / "04-因子研究"
FACTOR_NOTE_DIR.mkdir(parents=True, exist_ok=True)

# ── 同因子笔记检测 ──
FACTOR_INDEX_FILE = FACTOR_NOTE_DIR / "_因子索引.md"


def _find_existing_note(factor_name: str) -> Path:
    """查找是否已有同名因子的笔记文件"""
    # 规范化文件名: 下划线分割
    stem = factor_name.lower().replace(" ", "-").replace("_", "-")
    # 搜索已有文件
    for f in FACTOR_NOTE_DIR.glob("*.md"):
        if f.stem == stem or f.stem.startswith(stem + "-"):
            return f
        # 也检查 frontmatter 中的 factor 字段
        if f.stem == "_因子索引":
            continue
        try:
            text = f.read_text(encoding="utf-8")
            m = re.search(r'factor:\s*["\']?([\w-]+)', text)
            if m and m.group(1) == stem:
                return f
        except Exception:
            pass
    return None


def _generate_note(data: dict, is_update: bool) -> str:
    """生成笔记 Markdown 内容"""
    now = datetime.now().strftime("%Y-%m-%d")
    stem = data["factor"].lower().replace(" ", "-").replace("_", "-")

    # Tags
    tags = data.get("tags", [])
    tags_str = "\n".join(f"  - {t}" for t in tags)

    # Related factors
    related = data.get("related_factors", [])
    related_links = " ".join(f"[[{r}]]" for r in related)

    # Issues
    issues_lines = []
    for i, iss in enumerate(data.get("issues_found", []), 1):
        sev_icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(iss.get("severity", ""), "🔵")
        issues_lines.append(f"  {i}. **{iss['problem']}** {sev_icon}")
        issues_lines.append(f"     - 修复: {iss.get('fix', '')}")
        issues_lines.append(f"     - 影响: {iss.get('impact', '')}")

    # Insights
    insights_lines = [f"  - {ins}" for ins in data.get("key_insights", [])]

    # Code changes
    code_lines = []
    for ch in data.get("code_changes", []):
        code_lines.append(f"  - `{ch['file']}`: {ch['change']}")

    # Data fields
    field_lines = []
    for ds in data.get("data_fields_confirmed", []):
        field_lines.append(f"  - {ds['source']}: `{'`, `'.join(ds['fields'])}`")

    # Open questions
    questions = data.get("open_questions", [])

    # Build the note
    if is_update:
        header = f"> 📝 **更新于 {now}** — 同因子新增学习内容，与历史笔记合并\n"
    else:
        header = ""

    note = f"""---
title: "{data.get('title', stem)}"
factor: {stem}
type: factor-study
domain: 因子研究
tags:
{tags_str}
created: {"2026-05-30" if not is_update else data.get('created', now)}
updated: {now}
related_factors: [{related}]
---

# {data.get('title', stem)}

{header}

## 🎯 发现的问题

{chr(10).join(issues_lines) if issues_lines else '（首次分析，尚未发现问题）'}

## 💡 核心认知

{chr(10).join(insights_lines) if insights_lines else '（待补充）'}

## 🔧 代码变更

{chr(10).join(code_lines) if code_lines else '（无代码变更）'}

## 📊 数据字段确认

{chr(10).join(field_lines) if field_lines else '（待确认）'}

## ❓ 待解答的问题

{chr(10).join(f'  - {q}' for q in questions) if questions else '（无待解答问题）'}

## 🔗 关联因子

{related_links if related else '（暂无关联）'}
"""
    return note


def build_note(data: dict) -> Path:
    """主入口：创建或更新因子学习笔记"""
    stem = data["factor"].lower().replace(" ", "-").replace("_", "-")
    existing = _find_existing_note(stem)

    if existing:
        mode = "UPDATE"
        note_path = existing
        # 把原有笔记的创建时间保留
        try:
            text = existing.read_text(encoding="utf-8")
            m = re.search(r'created:\s*([\d-]+)', text)
            if m:
                data["created"] = m.group(1)
        except Exception:
            pass
    else:
        mode = "CREATE"
        note_path = FACTOR_NOTE_DIR / f"{stem}.md"

    content = _generate_note(data, is_update=(mode == "UPDATE"))
    note_path.write_text(content, encoding="utf-8")

    # 更新因子索引
    _update_index(stem, data.get("title", stem), mode)

    return note_path, mode


def _update_index(stem: str, title: str, mode: str):
    """更新 _因子索引.md，记录所有因子笔记"""
    if FACTOR_INDEX_FILE.exists():
        index_text = FACTOR_INDEX_FILE.read_text(encoding="utf-8")
    else:
        index_text = f"""---
title: 因子研究索引
type: index
domain: 因子研究
created: {datetime.now().strftime("%Y-%m-%d")}
updated: {datetime.now().strftime("%Y-%m-%d")}
---

# 因子研究索引

| 因子 | 最新更新 | 状态 |
|:----|:---------|:----:|
"""

    now = datetime.now().strftime("%Y-%m-%d")
    line = f"| [[{stem}]] | {title} | {now} | ✅ 已分析 |\n"

    if f"[[{stem}]]" in index_text:
        # 替换已存在的行
        index_text = re.sub(
            r"\| \[\[" + re.escape(stem) + r"\]\].*\|.*\|.*\|",
            line.rstrip("\n"),
            index_text,
        )
    else:
        # 追加到表格末尾
        # 找到表格行插入点
        table_end = index_text.rfind("|")
        if table_end > 0:
            index_text = index_text.rstrip() + "\n" + line

    FACTOR_INDEX_FILE.write_text(index_text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python learn_to_note.py <note_json>")
        print("或:   python learn_to_note.py --stdin  # 从stdin读取JSON")
        sys.exit(1)

    if sys.argv[1] == "--stdin":
        data = json.loads(sys.stdin.read())
    else:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            data = json.load(f)

    path, mode = build_note(data)
    print(f"✅ [{mode}] {path}")
    print(f"   Title: {data.get('title', '')}")
    print(f"   Issues: {len(data.get('issues_found', []))}")
    print(f"   Insights: {len(data.get('key_insights', []))}")
