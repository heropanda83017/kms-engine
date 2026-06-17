#!/usr/bin/env python3
"""
process_pdf.py — PDF 书籍 → 结构化笔记 + 可选 Skill 注入

融合 book-note-maker 的 8 阶段流水线到 KMS 统一入口。

用法:
    python3 process_pdf.py <pdf_path> [--output <dir>] [--make-skill] [--inject-agent <agent>]

阶段:
    1. 文本提取 (pypdf / marker-pdf OCR)
    2. 元数据提取
    3. 章节检测
    4. 内容分块
    5. 逐章四段式分析 (核心论点/概念/案例/金句)
    6. Mermaid 思维导图生成
    7. 笔记组装 + 保存
    8. 可选: smart-fuse → wiki-link → EVOLUTION.md
    9. 可选: --make-skill → book_to_skill.py + agent_river.py 注入
"""

import argparse, json, math, os, re, subprocess, sys, time
from pathlib import Path

# 路径注入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import SCRIPTS_DIR, WIKI_DIR

from _text_utils import chunk_text, strip_markdown, detect_chapters, extract_metadata


# ── 阶段1: 文本提取 ─────────────────────────────────────────
def extract_text(pdf_path: str) -> tuple[str, int, bool]:
    """从 PDF 提取文本，返回 (文本, 页数, 是否OCR)"""
    import pypdf
    reader = pypdf.PdfReader(pdf_path)
    full_text = ""
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            full_text += txt + "\n"

    chars = len(full_text)
    pages = len(reader.pages)
    is_ocr = False

    # 扫描版 PDF 检测
    if chars < pages * 20:
        print(f"  📄 扫描版 PDF 检测 ({chars} chars / {pages} pages)")
        is_ocr = True
        # 尝试 marker-pdf
        marker_result = subprocess.run(
            ["which", "marker_single"], capture_output=True, text=True, timeout=10
        )
        if marker_result.returncode == 0:
            print("  🔍 启动 marker-pdf OCR...")
            ocr_dir = Path("/tmp/book_ocr")
            ocr_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["marker_single", pdf_path, "--output_dir", str(ocr_dir),
                 "--languages", "zh,en"],
                timeout=600
            )
            # 读取 OCR 结果
            md_files = list(ocr_dir.rglob("*.md"))
            if md_files:
                full_text = md_files[0].read_text(encoding="utf-8", errors="replace")
                chars = len(full_text)
                print(f"  ✅ OCR 完成: {chars} chars")
        else:
            print("  ⚠️ marker-pdf 未安装，使用 pypdf 原始文本（可能稀疏）")
            print("    安装: uv pip install marker-pdf")

    return full_text, pages, is_ocr


# ── 阶段5: 逐章分析（LLM 调用） ─────────────────────────────
def analyze_chapter(title: str, content: str, chunk_idx: int) -> dict:
    """用 LLM 分析一个章节，返回结构化结果"""
    from _llm_call import llm_analyze

    prompt = f"""分析以下章节内容，返回 JSON（不要包含其他文字）：

章节标题: {title}

内容:
{content[:3000]}

请提取：
1. "core_arguments": 核心论点列表（每点一句话，最多5条）
2. "key_concepts": 关键概念列表 [{{"name": "概念名", "definition": "定义", "example": "举例"}}]
3. "cases": 典型案例列表 [{{"title": "案例名", "description": "简述", "role": "论证作用"}}]
4. "quotes": 金句列表 [{{"text": "原句", "context": "上下文"}}]

JSON 格式:
{{"core_arguments": [...], "key_concepts": [...], "cases": [...], "quotes": [...]}}
"""
    result = llm_analyze(prompt, max_tokens=2000)
    try:
        # 从文本中提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass
    return {"core_arguments": [], "key_concepts": [], "cases": [], "quotes": []}


def generate_mindmap(chapters: list[tuple[str, int, str]], book_title: str) -> str:
    """生成 Mermaid mindmap"""
    lines = ["mindmap", f"  root(({book_title}))"]
    for title, line_no, label in chapters:
        if label == "front_matter":
            clean = title[:30]
            lines.append(f"    [{clean}]")
        else:
            clean = title.replace('第', '').replace('章', ': ')[:40]
            lines.append(f"    [{clean}]")
    lines.append("  [结语/总结]")
    return "\n".join(lines)


def assemble_note(book_title: str, author: str, pages: int, is_ocr: bool,
                  chapters: list, chapter_analyses: list[dict],
                  mindmap: str, full_text: str) -> str:
    """组装最终笔记 Markdown"""
    lines = []
    lines.append(f"# 📖 {book_title} 读书笔记")
    lines.append("")
    lines.append(f"**作者**：{author or '未知'} | **页数**：{pages}页")
    lines.append(f"**提取方式**：{'扫描版OCR ✅' if is_ocr else '文本型PDF ✅'}")
    lines.append(f"**笔记日期**：{time.strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、全书逻辑框架鸟瞰")
    lines.append("")
    lines.append("```mermaid")
    lines.append(mindmap)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、章节精读笔记")
    lines.append("")

    for i, (title, line_no, label) in enumerate(chapters):
        analysis = chapter_analyses[i] if i < len(chapter_analyses) else {}
        lines.append(f"### {title}")
        lines.append("")
        # 核心论点
        lines.append("#### 核心论点")
        for arg in analysis.get("core_arguments", []):
            lines.append(f"- {arg}")
        lines.append("")
        # 关键概念
        lines.append("#### 关键概念")
        for c in analysis.get("key_concepts", []):
            lines.append(f"- **{c.get('name', '')}**：{c.get('definition', '')}")
            if c.get("example"):
                lines.append(f"  - 例：{c['example']}")
        lines.append("")
        # 案例
        lines.append("#### 典型案例")
        for case in analysis.get("cases", []):
            lines.append(f"**{case.get('title', '')}**")
            lines.append(f"- {case.get('description', '')}")
            lines.append(f"- 论证作用：{case.get('role', '')}")
        lines.append("")
        # 金句
        lines.append("#### 金句摘录")
        for q in analysis.get("quotes", []):
            lines.append(f'> "{q.get("text", "")}"')
            if q.get("context"):
                lines.append(f"  — {q['context']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 三、金句精选")
    lines.append("")
    all_quotes = []
    for a in chapter_analyses:
        all_quotes.extend(a.get("quotes", []))
    for q in all_quotes[:10]:
        lines.append(f'> "{q.get("text", "")}"')
    lines.append("")

    lines.append("## 四、延伸阅读推荐")
    lines.append("")
    lines.append("（待补充）")
    lines.append("")

    return "\n".join(lines)


def save_note(note_content: str, output_dir: str, book_title: str) -> str:
    """保存笔记到文件"""
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', book_title)[:50]
    note_path = Path(output_dir) / f"{safe_title}_读书笔记.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note_content, encoding="utf-8")
    return str(note_path)


# ── 阶段8: smart-fuse + wiki-link ──────────────────────────
def run_smart_fuse(note_path: str):
    """为新笔记找融合候选"""
    script = SCRIPTS_DIR / "smart_fuse.py"
    if not script.exists():
        print("  ⚠️ smart_fuse.py 未找到，跳过融合")
        return
    r = subprocess.run(
        [sys.executable, str(script), note_path],
        capture_output=True, text=True, timeout=60
    )
    print(r.stdout[-1000:] if r.stdout else "  ✅ smart-fuse 完成")


def run_wiki_link():
    """更新 wiki 链接"""
    script = SCRIPTS_DIR / "wiki-link.py"
    if not script.exists():
        print("  ⚠️ wiki-link.py 未找到，跳过")
        return
    r = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=60
    )
    print(r.stdout[-500:] if r.stdout else "  ✅ wiki-link 完成")


def update_evolution(note_title: str):
    """更新 EVOLUTION.md"""
    evo_path = WIKI_DIR / "EVOLUTION.md"
    if not evo_path.exists():
        return
    entry = f"- {time.strftime('%Y-%m-%d')} 新增读书笔记：{note_title} → [[{note_title}]]\n"
    with open(evo_path, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"  ✅ EVOLUTION.md 已更新")


# ── 阶段9: --make-skill ────────────────────────────────────
def make_skill(note_path: str, inject_agent: str = ""):
    """从笔记生成 Hermes Skill + 可选注入 Agent"""
    script = SCRIPTS_DIR / "book_to_skill.py"
    if not script.exists():
        print("  ⚠️ book_to_skill.py 未找到，跳过 Skill 生成")
        return

    cmd = [sys.executable, str(script), note_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    print(r.stdout[-1000:] if r.stdout else "  ✅ Skill 生成完成")

    if inject_agent:
        # 注入到 agent_river.py
        inject_to_agent(inject_agent)


def inject_to_agent(agent_name: str):
    """将认知框架注入到 agent_river.py 的指定 Agent"""
    agent_river = Path(__file__).resolve().parent.parent.parent / \
        "investment-engine" / "scripts" / "agent_river.py"
    if not agent_river.exists():
        print(f"  ⚠️ agent_river.py 未找到: {agent_river}")
        return
    print(f"  ℹ️ 注入到 Agent '{agent_name}' 需手动编辑 agent_river.py")
    print(f"     在对应 SubAgentDef 添加 cognitive_frameworks=[\"{agent_name}\"]")


# ── 主流程 ──────────────────────────────────────────────────
def process_pdf(pdf_path: str, output_dir: str = "",
                make_skill_flag: bool = False,
                inject_agent: str = "",
                skip_fuse: bool = False,
                skip_link: bool = False) -> dict:
    """执行完整 PDF 处理流水线"""
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        return {"success": False, "error": f"文件不存在: {pdf_path}"}

    book_title = pdf_file.stem
    output_dir = output_dir or str(WIKI_DIR / "05-读书笔记")
    result = {"success": True, "stages": {}}

    print(f"\n{'='*50}")
    print(f"  📖 处理: {book_title}")
    print(f"{'='*50}\n")

    # 阶段1: 文本提取
    print("[1/7] 文本提取...")
    full_text, pages, is_ocr = extract_text(pdf_path)
    result["stages"]["extract"] = {"chars": len(full_text), "pages": pages, "ocr": is_ocr}
    print(f"  ✅ {len(full_text)} chars, {pages} pages{' (OCR)' if is_ocr else ''}")

    # 阶段2: 元数据
    print("[2/7] 元数据提取...")
    meta = extract_metadata(full_text)
    author = meta.get("作者", meta.get("author", ""))
    print(f"  ✅ 作者: {author or '未知'}")

    # 阶段3: 章节检测
    print("[3/7] 章节检测...")
    chapters = detect_chapters(full_text)
    print(f"  ✅ 检测到 {len(chapters)} 个章节")
    for t, ln, lb in chapters[:15]:
        print(f"     [{lb}] {t} (行 {ln})")
    if len(chapters) > 15:
        print(f"     ... 还有 {len(chapters)-15} 个")

    # 阶段4: 内容分块
    print("[4/7] 内容分块...")
    chunks = chunk_text(full_text, max_chars=50000)
    print(f"  ✅ {len(chunks)} 个分块")

    # 阶段5: 逐章分析
    print("[5/7] 逐章分析...")
    chapter_analyses = []
    for i, (title, line_no, label) in enumerate(chapters):
        # 找到对应内容
        approx_offset = line_no * 80
        chunk_idx = 0
        for ci, chunk in enumerate(chunks):
            chunk_start = sum(len(c) for c in chunks[:ci])
            if chunk_start <= approx_offset < chunk_start + len(chunk):
                chunk_idx = ci
                break
        content = chunks[chunk_idx] if chunk_idx < len(chunks) else full_text[:50000]
        print(f"     [{i+1}/{len(chapters)}] {title[:40]}...", end=" ", flush=True)
        analysis = analyze_chapter(title, content, chunk_idx)
        chapter_analyses.append(analysis)
        print(f"✅ {len(analysis.get('core_arguments',[]))}论点 "
              f"{len(analysis.get('key_concepts',[]))}概念 "
              f"{len(analysis.get('cases',[]))}案例")
    result["stages"]["analyze"] = {"chapters": len(chapters)}

    # 阶段6: 思维导图
    print("[6/7] 思维导图生成...")
    mindmap = generate_mindmap(chapters, book_title)
    print(f"  ✅ {len(chapters)} 节点")

    # 阶段7: 笔记组装 + 保存
    print("[7/7] 笔记组装...")
    note_content = assemble_note(book_title, author, pages, is_ocr,
                                 chapters, chapter_analyses, mindmap, full_text)
    note_path = save_note(note_content, output_dir, book_title)
    result["stages"]["save"] = {"path": note_path, "size": len(note_content)}
    print(f"  ✅ 保存到: {note_path}")

    # 阶段8: 可选 — smart-fuse + wiki-link
    if not skip_fuse:
        print("\n[8/8a] smart-fuse 融合候选...")
        run_smart_fuse(note_path)
    if not skip_link:
        print("[8/8b] wiki-link 更新...")
        run_wiki_link()
        update_evolution(book_title)

    # 阶段9: 可选 — Skill 生成
    if make_skill_flag:
        print("\n[9/9] Skill 生成...")
        make_skill(note_path, inject_agent)

    print(f"\n{'='*50}")
    print(f"  ✅ 完成! 笔记: {note_path}")
    print(f"{'='*50}\n")

    return result


def main():
    parser = argparse.ArgumentParser(description="PDF 书籍 → 结构化笔记 + Skill")
    parser.add_argument("pdf", help="PDF 文件路径")
    parser.add_argument("--output", "-o", default="",
                        help="输出目录 (默认 wiki/05-读书笔记)")
    parser.add_argument("--make-skill", action="store_true",
                        help="生成 Hermes Skill")
    parser.add_argument("--inject-agent", default="",
                        help="注入到指定 Agent (如 macro, deep, sentiment)")
    parser.add_argument("--skip-fuse", action="store_true",
                        help="跳过 smart-fuse 融合")
    parser.add_argument("--skip-link", action="store_true",
                        help="跳过 wiki-link 更新")
    parser.add_argument("--json", action="store_true",
                        help="JSON 格式输出结果")

    args = parser.parse_args()
    result = process_pdf(
        args.pdf, args.output,
        make_skill_flag=args.make_skill,
        inject_agent=args.inject_agent,
        skip_fuse=args.skip_fuse,
        skip_link=args.skip_link,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
