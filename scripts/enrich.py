#!/usr/bin/env python3
"""
enrich.py — Horizon式 背景富化引擎

为新笔记自动搜索相关背景信息并生成结构化总结。

灵感来自 Horizon (github.com/Thysrael/Horizon) 的 Enrich 阶段：
  高分条目 → 概念提取 → Web搜索 → 结构化报告

用法:
  python enrich.py <笔记.md>                        # 富化（需已有 search_results）
  python enrich.py <笔记.md> --dry-run               # 预览：输出搜索关键词和query
  python enrich.py <笔记.md> --force                 # 忽略 score ≥ 6 门槛
  python enrich.py <笔记.md> --search-results JSON    # 传入预搜索结果JSON

前置条件:
  - 笔记已由 quality_gate_scorer.py 打分（有 score ≥ 6）
  - 搜索结果由外部工具（web_search / agent）采集

流程:
  1. 读笔记 frontmatter → 检查 score ≥ 6 且未富化
  2. 从标题+标签+类型生成搜索查询
  3. 输出搜索查询（--dry-run）或接受预搜索结果
  4. 用 LLM 生成结构化富化总结
  5. 追加到笔记 + 更新 frontmatter
"""

import os, sys, re, json, argparse, time
from pathlib import Path
from datetime import date

# litellm 用于 LLM 调用（延迟导入，仅实际调用时加载）
_llm_completion = None
def _get_llm():
    global _llm_completion
    if _llm_completion is None:
        try:
            from litellm import completion as c
            _llm_completion = c
        except ImportError:
            _llm_completion = False
    return _llm_completion

# ── 默认配置 ──
MODEL    = os.environ.get("ENRICH_MODEL", "deepseek/deepseek-v4-flash")
API_KEY = os.environ.get("ENRICH_API_KEY") or os.environ.get("DEEPSEEK_PRO_API_KEY", "")
API_BASE = os.environ.get("ENRICH_API_BASE", "https://api.deepseek.com")
MIN_SCORE = int(os.environ.get("ENRICH_MIN_SCORE", "6"))

# ── Frontmatter 解析 ──
def parse_frontmatter(content):
    """解析 frontmatter 返回 dict"""
    fm = {"title": "", "type": "note", "tags": [], "score": 0}
    if not content.startswith("---"):
        return fm
    end = content.find("---", 3)
    if end == -1:
        return fm
    raw = content[3:end].strip()
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip("'\"")
        # 处理 YAML 多行列表
        if key in ("tags", "score_tags"):
            if val:
                # 内联格式: tags: [a, b]
                val = val.strip("[]")
                fm["tags"] = [t.strip().strip("'\"") for t in val.split(",") if t.strip()]
            else:
                # 多行格式: tags:\n  - a\n  - b
                list_items = []
                while i < len(lines) and lines[i].strip().startswith("- "):
                    item = lines[i].strip()[2:].strip().strip("'\"")
                    if item:
                        list_items.append(item)
                    i += 1
                if list_items:
                    fm["tags"] = list_items
        elif key == "score":
            try:
                fm["score"] = int(val)
            except ValueError:
                fm["score"] = 0
        elif key == "enriched":
            fm["enriched"] = val.lower() == "true"
        elif key in ("title", "type", "domain"):
            fm[key] = val
        elif key == "score_summary" and not fm.get("title"):
            fm["title"] = val
    return fm


def read_frontmatter_raw(content):
    """返回 frontmatter 原始文本行列表"""
    if not content.startswith("---"):
        return [], content
    end = content.find("---", 3)
    if end == -1:
        return [], content
    lines = content[3:end].strip().split("\n")
    body = content[end + 3:].strip()
    return lines, body


def update_frontmatter(content, new_fields):
    """在 frontmatter 中追加新字段"""
    lines, body = read_frontmatter_raw(content)
    for key, val in new_fields.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for v in val:
                lines.append(f"- {v}")
        elif isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        else:
            lines.append(f"{key}: {val}")
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body


# ── 搜索查询生成 ──
def build_search_queries(fm, body, max_queries=3):
    """从笔记内容生成搜索查询列表（支持中英文双语）

    检测内容语言: 如果有大量英文技术词汇, 同时生成英文和中文查询
    """
    queries = []
    title = fm.get("title", "")
    tags = fm.get("tags", [])

    # 检测语言: 统计英文/中文比例
    head = body[:500]
    en_chars = len(re.findall(r'[a-zA-Z]', head))
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', head))
    is_english_dominant = en_chars > cn_chars * 2 and en_chars > 100

    # 查询1: 标题 (原语言)
    if title:
        queries.append(title.strip())

    # 查询2: 提取技术术语
    tech_terms = re.findall(r"[A-Z][a-zA-Z0-9+#./-]{2,}", head)
    cn_terms = re.findall(r"[\u4e00-\u9fff]{3,10}", head)

    combined = []
    if tech_terms:
        # 去重后取前3个
        unique_tech = list(dict.fromkeys(tech_terms))[:3]
        combined.extend(unique_tech)
    if tags:
        combined.extend(tags[:3])
    if cn_terms:
        cn_sorted = sorted(set(cn_terms), key=len, reverse=True)[:2]
        combined.extend(cn_sorted)

    if combined:
        queries.append(" ".join(combined[:5]))

    # 查询3: 如果是英文主导的内容, 生成中文对照查询
    if is_english_dominant:
        cn_query_parts = []
        if cn_terms:
            cn_query_parts.extend(sorted(set(cn_terms), key=len, reverse=True)[:2])
        # 用英文技术词 + 中文说明词
        if tech_terms:
            eng_part = " ".join(list(dict.fromkeys(tech_terms))[:2])
            cn_query_parts.append(eng_part)
        if cn_query_parts:
            queries.append(" ".join(cn_query_parts[:4]))
    else:
        # 中文内容: 加一个英文术语查询 (如果有关键的技术英文词)
        if tech_terms:
            queries.append(" ".join(list(dict.fromkeys(tech_terms))[:3]))

    # 去重
    seen = set()
    unique = []
    for q in queries:
        qn = q.lower().strip()
        if qn not in seen and len(qn) > 5:
            seen.add(qn)
            unique.append(q)
    return unique[:max_queries]


# ── LLM 富化总结 ──
def build_enrich_prompt(fm, body, search_results):
    """构造 LLM enrich prompt"""
    title = fm.get("title", "无标题")
    note_type = fm.get("type", "note")
    tags = ", ".join(fm.get("tags", []))

    results_text = ""
    for i, sr in enumerate(search_results, 1):
        src = sr.get("source", "")
        title_r = sr.get("title", "")
        snippet = sr.get("snippet", "") or sr.get("description", "")
        results_text += f"\n### 来源 {i}: {title_r}\n  链接: {src}\n  摘要: {snippet}\n"

    return f"""你是一个技术情报研究员。请对以下笔记进行背景富化分析。
请根据笔记内容语言选择回答语言: 如果笔记主要是英文则用英文回答, 中文则用中文回答。

## 笔记信息
标题: {title}
类型: {note_type}
标签: {tags}

## 笔记正文片段
{body[:800]}

## 网络搜索结果
{results_text}

## 输出要求
请只返回 JSON，不要包含 markdown 代码块标记或其他额外文字。
JSON 必须包含以下字段：
- "key_findings": 字符串，3-5句关键发现/补充信息
- "why_this_matters": 字符串，2-3句说明为什么这个主题重要
- "background": 字符串，2-3句背景信息
- "sources_used": 整数，实际使用的搜索结果数量"""


def llm_enrich(fm, body, search_results):
    """调用 LLM 生成富化内容，失败时返回降级文本"""
    llm = _get_llm()
    if not llm:
        return _degrade_enrich(search_results)

    prompt = build_enrich_prompt(fm, body, search_results)
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = llm(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                api_key=API_KEY,
                base_url=API_BASE,
                max_tokens=1000,
                temperature=0.3,
            )
            text = resp.choices[0].message.content.strip()
            # 提取 JSON
            json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "key_findings": data.get("key_findings", ""),
                    "why_this_matters": data.get("why_this_matters", ""),
                    "background": data.get("background", ""),
                    "sources_used": data.get("sources_used", len(search_results)),
                }
            # 如果没找到 JSON，用全文当发现
            return {
                "key_findings": text[:500],
                "why_this_matters": "",
                "background": "",
                "sources_used": len(search_results),
            }
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return _degrade_enrich(search_results)


def _degrade_enrich(search_results):
    """LLM 不可用时的降级富化文本"""
    snippets = []
    for sr in search_results[:3]:
        s = sr.get("snippet", "") or sr.get("description", "")
        if s:
            snippets.append(s[:200])
    return {
        "key_findings": " | ".join(snippets) if snippets else "搜索结果摘要未获取到",
        "why_this_matters": "",
        "background": "",
        "sources_used": len(search_results),
    }


# ── 富化文本生成 ──
def build_enrich_section(result, sources):
    """生成追加到笔记的富化 markdown 区块"""
    enrich = "\n\n---\n\n## 🔎 背景富化\n\n"
    enrich += "> 以下内容由 AI 自动搜索补充，提供相关背景信息。可能包含不准确信息，请注意甄别。\n"
    enrich += f"> 富化日期：{date.today()}\n\n"

    if result.get("key_findings"):
        enrich += "### 关键发现\n\n"
        enrich += result["key_findings"] + "\n\n"

    if result.get("why_this_matters"):
        enrich += "### 为什么重要\n\n"
        enrich += result["why_this_matters"] + "\n\n"

    if result.get("background"):
        enrich += "### 背景信息\n\n"
        enrich += result["background"] + "\n\n"

    if sources:
        enrich += "### 参考来源\n\n"
        for i, src in enumerate(sources[:8], 1):
            title = src.get("title", "")
            href = src.get("source", "") or src.get("href", "")
            snippet = (src.get("snippet", "") or src.get("description", ""))[:120]
            if href:
                enrich += f"- [{title}]({href})"
            else:
                enrich += f"- {title}"
            if snippet:
                enrich += f" — {snippet}"
            enrich += "\n"

    return enrich


# ── 核心 enrich 逻辑 ──
def enrich_note(note_path, search_results=None, dry_run=False, force=False):
    """对笔记执行背景富化"""
    if not note_path.exists():
        return {"success": False, "error": f"文件不存在: {note_path}"}

    content = note_path.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(content)
    body = content

    # 检查是否已富化
    if fm.get("enriched") and not force:
        return {"success": False, "error": "该笔记已富化（enriched: true），用 --force 覆盖"}

    # 检查分数门槛
    score = fm.get("score", 0)
    if score < MIN_SCORE and not force:
        return {
            "success": False,
            "error": f"分数 {score} 低于门槛 {MIN_SCORE}，用 --force 跳过检查",
            "score": score,
            "min_score": MIN_SCORE,
        }

    # 生成搜索查询
    queries = build_search_queries(fm, body)
    if not queries:
        queries = [fm.get("title", note_path.stem)]

    if dry_run:
        return {
            "success": True,
            "note": str(note_path),
            "title": fm.get("title", note_path.stem),
            "score": score,
            "type": fm.get("type", "note"),
            "tags": fm.get("tags", []),
            "queries": queries,
            "dry_run": True,
            "message": "dry-run 模式：请使用以下搜索查询获取结果，然后传入 --search-results",
        }

    # 必须有搜索结果
    if not search_results:
        return {
            "success": False,
            "error": "缺少搜索结果，请先运行 --dry-run 获取查询，搜索后传入 --search-results",
            "queries": queries,
        }

    # 调用 LLM 富化
    result = llm_enrich(fm, body, search_results)

    # 生成富化区块
    enrich_block = build_enrich_section(result, search_results)

    # 更新 frontmatter
    fm_fields = {
        "enriched": True,
        "enriched_at": str(date.today()),
    }
    # 提取来源 URL 列表
    source_urls = []
    for s in search_results[:10]:
        u = s.get("source", "") or s.get("href", "") or s.get("url", "")
        if u:
            source_urls.append(u)
    if source_urls:
        fm_fields["enrichment_sources"] = source_urls

    new_content = update_frontmatter(content, fm_fields)
    new_content += enrich_block

    # 写入文件
    note_path.write_text(new_content, encoding="utf-8")

    return {
        "success": True,
        "note": str(note_path),
        "title": fm.get("title", note_path.stem),
        "score": score,
        "queries": queries,
        "sources_used": len(search_results),
        "enriched": True,
    }


def main():
    parser = argparse.ArgumentParser(description="Horizon式背景富化引擎")
    parser.add_argument("note", nargs="?", help="笔记文件路径")
    parser.add_argument("--dry-run", action="store_true", help="预览搜索关键词，不写入")
    parser.add_argument("--force", action="store_true", help="跳过 score ≥ 6 检查")
    parser.add_argument("--search-results", help="JSON 格式搜索结果（可传入文件路径或 JSON 字符串）")
    args = parser.parse_args()

    if not args.note:
        parser.print_help()
        sys.exit(1)

    note_path = Path(args.note)
    if not note_path.exists():
        print(json.dumps({"success": False, "error": f"文件不存在: {note_path}"}, ensure_ascii=False))
        sys.exit(1)

    # 解析搜索结果
    search_results = None
    if args.search_results:
        # 尝试作为文件路径读取
        sr_path = Path(args.search_results)
        if sr_path.exists():
            search_results = json.loads(sr_path.read_text(encoding="utf-8"))
        else:
            # 尝试作为 JSON 字符串解析
            try:
                search_results = json.loads(args.search_results)
            except json.JSONDecodeError as e:
                print(json.dumps({"success": False, "error": f"search-results 解析失败: {e}"}, ensure_ascii=False))
                sys.exit(1)

    result = enrich_note(note_path, search_results, dry_run=args.dry_run, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("success"):
        sys.exit(2 if result.get("error", "").startswith("分数") else 1)


if __name__ == "__main__":
    main()
