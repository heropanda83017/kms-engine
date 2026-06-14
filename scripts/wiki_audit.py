#!/usr/bin/env python3
"""wiki_audit.py — Wiki 治理工具箱

自动检测 wiki 知识库的冗余、归类混乱、内容过胖等治理问题。

用法:
  python wiki_audit.py                             # 全量治理报告
  python wiki_audit.py --redundancy                # 仅冗余检测
  python wiki_audit.py --categories                # 仅归类审计
  python wiki_audit.py --digest                    # 仅精华摘要
  python wiki_audit.py --report                    # 只输出报告，不交互
  python wiki_audit.py --json                      # JSON 输出
"""

import sys, json, argparse, re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, CONFIG_DIR
from kg_store import get_all_entities, get_all_relations, \
    get_entities_for_note, search_entities

# ── 目录 ↦ 知识域映射 ────────────────────────────────
# 用于归类审计：检测笔记的实际实体类型是否匹配目录预期
DIR_DOMAIN_MAP = {
    "01-theory":       ["concept", "domain", "method"],
    "02-AI核心":       ["concept", "domain", "method", "tool"],
    "03-core-ai":      ["concept", "tool"],
    "03-工具篇":       ["tool", "method"],
    "04-tools":        ["tool", "method"],
    "05-applications": ["concept"],
    "05-读书笔记":     ["concept", "method", "person", "company", "domain"],
    "06-reading-notes":["concept", "method", "person"],
    "07-practices":    ["method", "tool", "concept"],
    "08-investment":   ["factor", "indicator", "company", "method", "concept"],
    "00-系统":         ["concept", "domain"],
    "00-个人":         ["person", "concept"],
    "导航":            [],
}

# ── 大文件阈值 ────────────────────────────────────────
LARGE_FILE_LINES = 500     # >500行 → 需要精华摘要
HUGE_FILE_LINES = 2000     # >2000行 → 红牌警告


# ════════════════════════════════════════════════════════
# 1. 冗余检测 — KG实体重叠率
# ════════════════════════════════════════════════════════

def detect_redundancy(min_overlap: float = 0.4) -> list:
    """基于KG实体重叠率检测高相似笔记对

    返回: [(note_a, note_b, overlap_rate, shared_entities, path_a, path_b), ...]
         按 overlap_rate 降序排列
    """
    # 收集有实体关联的笔记
    note_entities = {}  # note_path -> set(entity_names)
    all_ents = get_all_entities()
    for ename in all_ents:
        notes = _get_notes_for_entity_fast(ename)
        for n in notes:
            if n not in note_entities:
                note_entities[n] = set()
            note_entities[n].add(ename)

    # 没有实体的笔记无法参与检测
    if len(note_entities) < 2:
        return []

    # 两两比较实体重叠率
    results = []
    paths = list(note_entities.keys())
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            a, b = paths[i], paths[j]
            set_a = note_entities[a]
            set_b = note_entities[b]
            if not set_a or not set_b:
                continue
            overlap = set_a & set_b
            if not overlap:
                continue
            # 重叠率 = 重叠实体数 / min(两笔记实体数)
            rate = len(overlap) / max(len(set_a | set_b), 1)
            if rate >= min_overlap:
                results.append((rate, a, b, list(overlap), len(set_a), len(set_b)))

    results.sort(key=lambda x: -x[0])
    return [
        {
            "overlap_rate": r,
            "note_a": {"path": a, "entity_count": ac},
            "note_b": {"path": b, "entity_count": bc},
            "shared_entities": ents,
        }
        for r, a, b, ents, ac, bc in results
    ]


def _get_notes_for_entity_fast(entity_name: str) -> list:
    """快速获取实体关联的笔记（不走SQLite，用已缓存的 KG 数据）"""
    from kg_store import get_notes_for_entity
    return [n["note_path"] for n in get_notes_for_entity(entity_name)]


# ════════════════════════════════════════════════════════
# 2. 归类审计 — 目录 vs 实际实体类型
# ════════════════════════════════════════════════════════

def audit_categories() -> list:
    """检测归类混乱的笔记

    返回: [{"note": str, "current_dir": str, "expected_dirs": [str],
            "actual_types": [str], "mismatch_score": float}, ...]
    """
    wiki = WIKI_DIR
    results = []

    for f in sorted(wiki.rglob("*.md")):
        if ".obsidian" in str(f) or f.name == "CHANGELOG.md":
            continue
        rel = str(f.relative_to(wiki)).replace("\\", "/")
        parts = rel.split("/")
        top_dir = parts[0] if parts else ""
        expected_types = DIR_DOMAIN_MAP.get(top_dir, [])

        # 获取该笔记的实体类型分布
        entities = get_entities_for_note(rel)
        if not entities:
            continue  # 无实体知识的笔记跳过审计

        actual_types = Counter(e.get("type", "") for e in entities if e.get("type"))
        if not actual_types:
            continue

        # 如果实体类型和目录预期的类型完全不匹配 → 归类可能有问题
        if expected_types:
            # 计算实际类型中「不在预期内」的比例
            total = sum(actual_types.values())
            unexpected = sum(v for t, v in actual_types.items() if t not in expected_types)
            mismatch_rate = unexpected / total if total > 0 else 0

            if mismatch_rate > 0.5:
                # 仅报告 >50% 实体类型与目录不匹配的笔记
                results.append({
                    "note": rel,
                    "current_dir": top_dir,
                    "expected_types": expected_types,
                    "actual_types": dict(actual_types.most_common()),
                    "mismatch_rate": round(mismatch_rate, 2),
                })

    results.sort(key=lambda x: -x["mismatch_rate"])
    return results


# ════════════════════════════════════════════════════════
# 3. 精华摘要 — 超长笔记标注
# ════════════════════════════════════════════════════════

def audit_digest_needs(lines_threshold: int = 500) -> list:
    """检查超长笔记，建议生成精华摘要

    返回: [{"note": str, "lines": int, "entities": [str], "suggest": str}, ...]
    """
    wiki = WIKI_DIR
    results = []

    for f in sorted(wiki.rglob("*.md")):
        if ".obsidian" in str(f) or f.name in ("CHANGELOG.md", "EVOLUTION.md"):
            continue
        rel = str(f.relative_to(wiki)).replace("\\", "/")
        content = f.read_text(encoding="utf-8", errors="ignore")
        lines = content.count("\n") + 1

        if lines < lines_threshold:
            continue

        # 获取该笔记的实体
        entities = get_entities_for_note(rel)
        entity_names = [e.get("name", "") for e in entities[:8]]

        if lines >= HUGE_FILE_LINES:
            suggest = "🔴 超大型笔记，强烈建议拆分为多篇或生成精华摘要"
        else:
            suggest = "🟡 长篇笔记，建议顶部添加摘要区"

        results.append({
            "note": rel,
            "lines": lines,
            "entities": entity_names,
            "suggest": suggest,
        })

    results.sort(key=lambda x: -x["lines"])
    return results


# ════════════════════════════════════════════════════════
# 4. 全局治理报告
# ════════════════════════════════════════════════════════

def generate_report(redundancy: list, categories: list, digest: list,
                     output_json: bool = False) -> dict:
    """生成全局治理报告"""
    # 总体统计
    wiki = WIKI_DIR
    all_md = [f for f in wiki.rglob("*.md") if ".obsidian" not in str(f)]
    total_notes = len(all_md)
    total_lines = sum(f.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
                      for f in all_md)
    large_notes = len(digest)
    total_entities = len(get_all_entities())

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "total_notes": total_notes,
            "total_lines": total_lines,
            "avg_lines_per_note": round(total_lines / total_notes, 1) if total_notes else 0,
            "total_entities": total_entities,
            "notes_with_entities": len(get_all_relations()),
        },
        "red_flags": {
            "redundant_pairs": len(redundancy),
            "misclassified_notes": len(categories),
            "large_notes_needing_digest": large_notes,
        },
        "details": {
            "redundancy": redundancy[:15],       # 取Top冗余对
            "categories": categories[:15],       # 取Top归类问题
            "digest": digest[:10],                # 取Top大文件
        },
    }

    return report


def print_report(report: dict):
    """人类可读输出"""
    s = report["summary"]
    rf = report["red_flags"]
    d = report["details"]

    print(f"{'='*55}")
    print(f"  📊 Wiki 治理报告 — {report['generated_at']}")
    print(f"{'='*55}")
    print(f"\n📈 总体统计:")
    print(f"  笔记总数: {s['total_notes']}")
    print(f"  总行数: {s['total_lines']:,}")
    print(f"  平均行数/篇: {s['avg_lines_per_note']}")
    print(f"  知识图谱实体: {s['total_entities']}")

    print(f"\n🚩 红旗指标:")
    print(f"  🔴 冗余笔记对: {rf['redundant_pairs']}")
    print(f"  🟡 归类异常: {rf['misclassified_notes']}")
    print(f"  🟠 需精华摘要: {rf['large_notes_needing_digest']}")

    # 冗余详情
    if d["redundancy"]:
        print(f"\n🔴 高冗余笔记对 (实体重叠率 ≥40%):")
        for item in d["redundancy"][:10]:
            a = Path(item["note_a"]["path"]).name
            b = Path(item["note_b"]["path"]).name
            rate = item["overlap_rate"]
            ents = ", ".join(item["shared_entities"][:3])
            print(f"  {rate:.0%}  {a}  ↔  {b}")
            print(f"       共享实体: {ents}")

    # 归类异常
    if d["categories"]:
        print(f"\n🟡 归类异常笔记 (实体类型与目录不匹配):")
        for item in d["categories"][:10]:
            name = Path(item["note"]).name
            types = ", ".join(f"{t}:{c}" for t, c in item["actual_types"].items())
            print(f"  {name}")
            print(f"    当前: {item['current_dir']} | 实际类型: {types}")

    # 大文件
    if d["digest"]:
        print(f"\n🟠 大文件 (建议精华摘要):")
        for item in d["digest"][:8]:
            name = Path(item["note"]).name
            print(f"  {item['suggest']}")
            print(f"    {name} ({item['lines']}行)")
            if item["entities"]:
                print(f"    核心实体: {', '.join(item['entities'][:5])}")

    print(f"\n{'='*55}")
    print(f"  💡 建议: 对冗余笔记做 `kms kg merge` 合并实体；对归类异常手动移动文件")
    print(f"{'='*55}")


# ════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Wiki 治理工具箱")
    parser.add_argument("--redundancy", action="store_true", help="仅冗余检测")
    parser.add_argument("--categories", action="store_true", help="仅归类审计")
    parser.add_argument("--digest", action="store_true", help="仅精华摘要检测")
    parser.add_argument("--report", action="store_true", help="全量报告")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--overlap", type=float, default=0.4,
                        help="冗余检测实体重叠率阈值 (默认0.4)")
    args = parser.parse_args()

    # 默认：全量报告
    run_all = not (args.redundancy or args.categories or args.digest)

    redundancy = detect_redundancy(min_overlap=args.overlap) if (run_all or args.redundancy) else []
    categories = audit_categories() if (run_all or args.categories) else []
    digest = audit_digest_needs() if (run_all or args.digest) else []

    report = generate_report(redundancy, categories, digest, output_json=args.json)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
