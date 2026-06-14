#!/usr/bin/env python3
"""kg_extract.py — 实体抽取管线

从笔记正文中提取结构化实体和关系，存入 kg-store。

用法:
  python kg_extract.py <note.md>                        # 单篇提取并存储
  python kg_extract.py <note.md> --dry-run              # 预览不存储
  python kg_extract.py --batch <dir>                    # 批量处理目录
  python kg_extract.py --all                            # 全库扫描（跳过已提取的）
  python kg_extract.py --all --force                    # 全库扫描（强制重提）
  python kg_extract.py <note.md> --no-store             # 只输出 JSON 到 stdout

工作流：
  1. 读取笔记正文（跳过 frontmatter）
  2. 调用 LLM 提取实体+关系（kg_entity_types.py 定义的8种实体/6种关系）
  3. 存入 kg-store（entities.json + relations.json）
  4. 返回提取结果 dict
"""

import json, os, re, sys, time, argparse, logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# 抑制 LiteLLM 无意义警告（SSL超时/remote cost map下载失败）
os.environ.setdefault("LITELLM_LOG", "ERROR")
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").disabled = True

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, SCRIPTS_DIR
from kg_store import batch_store, get_stats, get_entities_for_note, \
    get_all_entities, search_entities, get_related_entities
from kg_entity_types import build_system_prompt

# ── LLM 配置（同 quality_gate_scorer.py 模式） ────────
MODEL = os.environ.get("KG_EXTRACT_MODEL", "deepseek/deepseek-v4-flash")
API_KEY = os.environ.get("KG_EXTRACT_API_KEY") or \
          os.environ.get("DEEPSEEK_PRO_API_KEY", "")
API_BASE = os.environ.get("KG_EXTRACT_API_BASE", "https://api.deepseek.com")

# ── 系统 Prompt ───────────────────────────────────────
SYSTEM_PROMPT = build_system_prompt()

# ── 进度跟踪文件 ──────────────────────────────────────
PROGRESS_FILE = Path(__file__).resolve().parent.parent / "config" / "cache" / "kg_extract_progress.json"


def _load_progress() -> set:
    """已提取过的笔记路径（相对 WIKI_DIR），容错：损坏时自动重建"""
    if not PROGRESS_FILE.exists():
        return set()
    try:
        return set(json.loads(PROGRESS_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️  kg_extract 进度文件损坏，将重建: {e}", file=sys.stderr)
        # 备份损坏文件
        backup = PROGRESS_FILE.with_suffix(".json.bak")
        try:
            PROGRESS_FILE.rename(backup)
        except OSError:
            pass
        return set()


def _save_progress(path: str):
    """标记一篇笔记为已提取（原子写入）"""
    progress = _load_progress()
    progress.add(path)
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 原子写入：临时文件 → rename
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(sorted(progress), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(PROGRESS_FILE)


def parse_frontmatter(text: str) -> tuple:
    """解析 frontmatter，返回 (fm_dict, body_text)"""
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end_idx = stripped.find("---", 3)
        if end_idx != -1:
            raw_fm = stripped[3:end_idx].strip()
            body = stripped[end_idx + 3:].lstrip()
            # 简单解析 frontmatter
            fm = {"title": "", "type": "", "domain": "", "tags": []}
            for line in raw_fm.split("\n"):
                line = line.strip()
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if k == "tags":
                        v = v.strip("[]\"'")
                        fm["tags"] = [t.strip() for t in v.split(",") if t.strip()]
                    elif k in ("title", "type", "domain"):
                        fm[k] = v
            return fm, body
    return {"title": ""}, text


def extract_entities(content: str, max_retries: int = 2) -> Optional[dict]:
    """调用 LLM 提取实体和关系

    返回: {"entities": [...], "relations": [...]}
    失败返回 None
    """
    if not API_KEY:
        print("  ❌ 未配置 KG_EXTRACT_API_KEY 或 DEEPSEEK_PRO_API_KEY", file=sys.stderr)
        return None

    from litellm import completion

    # 限制输入长度（前 4000 字符 + 后 1000 字符）
    if len(content) > 5000:
        content = content[:4000] + "\n...(中间省略)...\n" + content[-1000:]

    for attempt in range(max_retries):
        try:
            resp = completion(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                api_key=API_KEY,
                api_base=API_BASE,
                temperature=0.1,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content.strip()

            # 提取 JSON（处理 LLM 可能输出 markdown 代码块的情况）
            # 先移除 markdown 代码块标记
            raw_clean = re.sub(r'```(?:json)?\s*', '', raw).strip()
            # 尝试多种 JSON 提取策略
            json_match = re.search(r'\{[\s\S]*"entities"[\s\S]*"relations"[\s\S]*\}', raw_clean, re.DOTALL)
            if not json_match:
                # 最宽松：找第一个 { 到最后一个 }
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end > start:
                    json_match = re.search(r'\{.*\}', raw[start:end+1], re.DOTALL)

            if json_match:
                result = json.loads(json_match.group())
                entities = result.get("entities", [])
                relations = result.get("relations", [])
                if isinstance(entities, list) and isinstance(relations, list):
                    # 清理：过滤掉没有 name 的实体
                    entities = [e for e in entities if e.get("name", "").strip()]
                    # 清理：过滤掉 source/target 为空的 relation
                    relations = [r for r in relations
                                 if r.get("source", "").strip()
                                 and r.get("target", "").strip()]
                    return {"entities": entities, "relations": relations}

            print(f"  ⚠️  LLM 返回格式异常 (attempt {attempt+1}): {raw[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  LLM 调用失败 (attempt {attempt+1}): {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) * 2)

    return None


def extract_note(note_path: Path, dry_run: bool = False,
                 no_store: bool = False, verbose: bool = False) -> Optional[dict]:
    """从一篇笔记中提取实体并存储

    返回: {"filename": str, "entities": list, "relations": list, "note_rel": str}
    """
    if not note_path.exists():
        print(f"  ❌ 文件不存在: {note_path}", file=sys.stderr)
        return None

    # 读取笔记
    text = note_path.read_text(encoding="utf-8", errors="ignore")
    fm, body = parse_frontmatter(text)

    if len(body.strip()) < 100:
        if verbose:
            print(f"  ⏭️  {note_path.name}: 正文过短 ({len(body.strip())} 字), 跳过")
        return None

    title = fm.get("title", note_path.stem)
    note_rel = str(note_path.relative_to(WIKI_DIR)).replace("\\", "/")

    if verbose:
        print(f"  🔍 {title} ({len(body.strip())} 字)...", end="", flush=True)

    # 调用 LLM 提取
    result = extract_entities(body)
    if result is None:
        if verbose:
            print(" ❌ LLM 提取失败")
        return None

    entities = result["entities"]
    relations = result["relations"]

    if verbose:
        print(f" 提取 {len(entities)} 实体 + {len(relations)} 关系")

    # 存储
    if not dry_run and not no_store:
        batch_store(entities, relations, note_rel)
        _save_progress(note_rel)

    if dry_run:
        print(f"\n  笔记: {title} ({note_rel})")
        print(f"  --- 实体({len(entities)}):")
        for e in entities:
            print(f"    [{e['type']}] {e['name']} — {e.get('description', '')}")
        print(f"  --- 关系({len(relations)}):")
        for r in relations:
            print(f"    {r['source']} --[{r['type']}]--> {r['target']} {r.get('description', '')}")

    return {
        "filename": note_path.name,
        "title": title,
        "note_rel": note_rel,
        "entities": entities,
        "relations": relations,
    }


def scan_batch(directory: str, dry_run: bool = False,
               force: bool = False, verbose: bool = True) -> dict:
    """批量扫描一个目录下的所有 .md 文件"""
    path = Path(directory)
    if not path.exists():
        print(f"  ❌ 目录不存在: {directory}", file=sys.stderr)
        return {"total": 0, "extracted": 0, "skipped": 0, "failed": 0}

    # 加载进度
    progress = set() if force else _load_progress()

    md_files = sorted(path.rglob("*.md"))
    # 排除 .obsidian 目录
    md_files = [f for f in md_files if ".obsidian" not in str(f)]

    total = len(md_files)
    extracted = 0
    skipped = 0
    failed = 0

    for i, f in enumerate(md_files):
        note_rel = str(f.relative_to(WIKI_DIR)).replace("\\", "/")

        if not force and note_rel in progress:
            skipped += 1
            continue

        if verbose:
            print(f"  [{i+1}/{total}] ", end="")
        result = extract_note(f, dry_run=dry_run, verbose=verbose)

        if result:
            extracted += 1
        else:
            failed += 1

    if verbose:
        print(f"\n  ✅ 完成: {extracted} 提取 / {skipped} 跳过 / {failed} 失败 / {total} 总计")

    return {"total": total, "extracted": extracted, "skipped": skipped, "failed": failed}


# ── CLI ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="KG 实体抽取管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("target", nargs="?", help="笔记路径")
    parser.add_argument("--dry-run", action="store_true", help="预览不存储")
    parser.add_argument("--no-store", action="store_true", help="只输出JSON到stdout")
    parser.add_argument("--batch", action="store_true",
                        help="批量处理 target 目录下的所有 .md")
    parser.add_argument("--all", action="store_true", help="全库扫描")
    parser.add_argument("--force", action="store_true",
                        help="全库扫描时强制重提（忽略进度）")
    parser.add_argument("--verbose", "-v", action="store_true", default=True,
                        help="详细输出")

    # 内置管理子命令
    parser.add_argument("--stats", action="store_true", help="显示实体存储统计")
    parser.add_argument("--search", type=str, help="搜索实体")
    parser.add_argument("--related", type=str, help="查看实体的关联")
    parser.add_argument("--note-entities", type=str,
                        help="查看某篇笔记的实体（相对wiki路径）")

    args = parser.parse_args()

    # ── 统计/搜索命令 ──
    if args.stats:
        s = get_stats()
        print(f"  实体数: {s['total_entities']}")
        print(f"  关系数: {s['total_relations']}")
        print(f"  已关联笔记: {s['notes_with_entities']}")
        print(f"  最后提取: {s.get('last_extract_time', '从未')}")
        return

    if args.search:
        for e in search_entities(args.search):
            print(f"  [{e['type']}] {e['name']} — {e.get('description', '')}")
        return

    if args.related:
        g = get_related_entities(args.related)
        print(f"  `{args.related}` 的关联实体 ({len(g['nodes'])}个):")
        for n in g["nodes"]:
            print(f"    [{n.get('type','?')}] {n['name']} — {n.get('description','')}")
        print(f"  关系: {len(g['edges'])} 条")
        return

    if args.note_entities:
        ents = get_entities_for_note(args.note_entities)
        print(f"  `{args.note_entities}` 中的实体 ({len(ents)}个):")
        for e in ents:
            print(f"    [{e.get('type','?')}] {e['name']} — {e.get('description','')}")
        return

    # ── 提取命令 ──
    if args.all:
        scan_batch(str(WIKI_DIR), dry_run=args.dry_run, force=args.force,
                   verbose=args.verbose)
        return

    if args.target:
        target_path = Path(args.target)

        if args.batch:
            # 批量模式
            scan_batch(str(target_path), dry_run=args.dry_run,
                       force=args.force, verbose=args.verbose)
        else:
            # 单篇模式
            extract_note(target_path, dry_run=args.dry_run,
                         no_store=args.no_store, verbose=args.verbose)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
