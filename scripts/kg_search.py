#!/usr/bin/env python3
"""kg_search.py — 融合检索引擎 (KG+RRF Fusion Search)

Phase 3: 在 RRF 搜索基础上引入知识图谱实体感知，提升搜索精准度。

用法:
  python kg_search.py <query>                              # 融合搜索
  python kg_search.py <query> --boost 0.3                  # 自定义boost系数
  python kg_search.py <query> --kg-only                    # 仅KG搜索(调试)
  python kg_search.py <query> --rrf-only                   # 仅RRF搜索(调试)
  python kg_search.py --analyze <query>                    # 只显示查询分析结果

融合公式:
  final_score = rrf_score × (1 + boost × match_type_weight)

  match_type_weight:
    exact_entity    = 1.0  (查询精确匹配实体名，笔记引用了该实体)
    related_entity  = 0.5  (笔记引用了关联实体)
    same_type       = 0.25 (笔记实体类型与查询主类型匹配)
"""

import sys, json, argparse
from pathlib import Path
from collections import Counter
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import SCRIPTS_DIR, WIKI_DIR
from kg_store import search_entities, get_notes_for_entity, get_related_entities

# ── 匹配类型权重 ──────────────────────────────────────
MATCH_WEIGHTS = {
    "exact_entity": 1.0,    # 精确匹配 +100%
    "fuzzy_entity": 0.5,    # 模糊匹配 +50%
    "related_entity": 0.5,  # 关联实体 +50%
    "same_type": 0.25,      # 同类型 +25%
}


# ════════════════════════════════════════════════════════
# 查询分析器
# ════════════════════════════════════════════════════════

def analyze_query(query: str) -> dict:
    """分析查询，提取实体和意图

    返回:
    {
        "entities": [entity_dict, ...],       # KG中匹配的实体
        "primary_type": str|None,              # 主要实体类型
        "matched_entity": str|None,            # 精确匹配的实体名
        "related_entities": [entity_dict,...], # 关联实体
        "related_edges": [relation_dict,...],  # 关联关系
        "entity_notes": {entity_name: [note_path,...]},  # 各实体的关联笔记
    }
    """
    # 1. 在 KG 中搜索匹配实体 (前缀/包含匹配)
    entities = search_entities(query, limit=10)

    # 2. 推断主要实体类型
    types = Counter(e["type"] for e in entities)
    primary_type = types.most_common(1)[0][0] if types else None

    # 3. 精确匹配检测
    q_lower = query.lower().strip()
    matched_entity = None
    matched_etype = None
    for e in entities:
        if e["name"].lower() == q_lower:
            matched_entity = e["name"]
            matched_etype = e["type"]
            break
        # 也检查别名
        for alias in e.get("aliases", []):
            if alias.lower() == q_lower:
                matched_entity = e["name"]
                matched_etype = e["type"]
                break
        if matched_entity:
            break

    # 4. 获取关联实体/关系
    related_entities = []
    related_edges = []
    if matched_entity:
        related = get_related_entities(matched_entity)
        related_entities = related.get("nodes", [])
        related_edges = related.get("edges", [])

    # 5. 收集所有相关实体的笔记
    entity_notes = {}
    all_relevant = [e["name"] for e in entities]
    if matched_entity:
        all_relevant.append(matched_entity)
    all_relevant.extend(e["name"] for e in related_entities)
    all_relevant = list(set(all_relevant))

    for ename in all_relevant:
        notes = get_notes_for_entity(ename)
        if notes:
            entity_notes[ename] = [n["note_path"] for n in notes]

    return {
        "entities": entities,
        "primary_type": primary_type,
        "matched_entity": matched_entity,
        "matched_etype": matched_etype,
        "related_entities": related_entities,
        "related_edges": related_edges,
        "entity_notes": entity_notes,
    }


# ════════════════════════════════════════════════════════
# KG 搜索
# ════════════════════════════════════════════════════════

def kg_search(analysis: dict) -> dict:
    """基于 KG 分析结果搜索相关笔记

    返回: {note_path: {"score": float, "match_type": str, "reasons": [str]}}
    """
    results = {}  # note_path -> {score, match_type, reasons}

    # 信号1: 精确匹配实体 → 该实体关联的笔记
    if analysis["matched_entity"]:
        ename = analysis["matched_entity"]
        notes = get_notes_for_entity(ename)
        for n in notes:
            path = n["note_path"]
            if path not in results:
                results[path] = {"score": 0, "match_type": "exact_entity", "reasons": []}
            results[path]["score"] += 10 * MATCH_WEIGHTS["exact_entity"]
            results[path]["reasons"].append(f"精确匹配实体「{ename}」")

    # 信号2: 模糊匹配实体 → 实体关联笔记
    for e in analysis["entities"]:
        ename = e["name"]
        if ename == analysis["matched_entity"]:
            continue  # 已在信号1处理
        notes = get_notes_for_entity(ename)
        for n in notes:
            path = n["note_path"]
            if path not in results:
                results[path] = {"score": 0, "match_type": "fuzzy_entity", "reasons": []}
            results[path]["score"] += 4
            results[path]["reasons"].append(f"匹配实体「{ename}」({e['type']})")

    # 信号3: 关联实体的笔记
    for e in analysis["related_entities"]:
        ename = e["name"]
        notes = get_notes_for_entity(ename)
        for n in notes:
            path = n["note_path"]
            if path not in results:
                results[path] = {"score": 0, "match_type": "related_entity", "reasons": []}
            results[path]["score"] += 5 * MATCH_WEIGHTS["related_entity"]
            results[path]["reasons"].append(f"关联实体「{ename}」")

    # 信号4: 同类型实体的笔记（非精确匹配时）
    if analysis["primary_type"] and not analysis["matched_entity"]:
        ptype = analysis["primary_type"]
        for e in analysis["entities"]:
            if e["type"] == ptype:
                notes = get_notes_for_entity(e["name"])
                for n in notes:
                    path = n["note_path"]
                    if path not in results:
                        results[path] = {"score": 0, "match_type": "same_type", "reasons": []}
                    if "score" in results[path]:
                        results[path]["score"] += 3 * MATCH_WEIGHTS["same_type"]
                        results[path]["reasons"].append(f"同类型实体「{e['name']}」({ptype})")

    # 归一化分数到 0-10
    if results:
        max_score = max(r["score"] for r in results.values())
        if max_score > 0:
            for r in results.values():
                r["score"] = round(r["score"] / max_score * 10, 2)

    return results


# ════════════════════════════════════════════════════════
# 融合排序
# ════════════════════════════════════════════════════════

def fusion_rank(rrf_results: list, kg_results: dict, boost: float = 0.3) -> list:
    """融合 RRF 和 KG 搜索结果

    rrf_results: [(note_path, rrf_score, snippet), ...]  (已排序)
    kg_results:  {note_path: {"score": float, "match_type": str, "reasons": [str]}}

    返回: [(note_path, final_score, snippet, rrf_score, kg_score, reasons), ...]
         (按 final_score 降序)
    """
    if not kg_results:
        # KG 无结果，返回纯 RRF
        return [(p, s, sn, s, 0, []) for p, s, sn in rrf_results]

    fused = []
    for path, rrf_score, snippet in rrf_results:
        kg_info = kg_results.get(path, None)
        if kg_info:
            kg_score = kg_info["score"]
            match_type = kg_info["match_type"]
            weight = MATCH_WEIGHTS.get(match_type, 0.5)
            # 融合公式: final = rrf × (1 + boost × weight)
            final_score = rrf_score * (1 + boost * weight)
            reasons = kg_info["reasons"]
        else:
            kg_score = 0
            final_score = rrf_score  # 无KG增强
            reasons = []

        fused.append((path, round(final_score, 4), snippet, rrf_score, kg_score, reasons))

    # 按 final_score 降序
    fused.sort(key=lambda x: -x[1])
    return fused


def rrf_search_fallback(query: str, limit: int = 20) -> list:
    """调用 RRF 搜索获取基准结果（降级：无 RRF 时返回空列表）

    返回: [(path, rrf_score, snippet), ...]
    """
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from rrf_search import search_rrf
        result = search_rrf(query, top_k=limit)
        items = result.get("results", [])
        return [
            (r.get("path", ""), r.get("rrf_score", 0.0), r.get("title", ""))
            for r in items
        ]
    except (ImportError, Exception) as e:
        print(f"  ⚠️  RRF search 不可用: {e}", file=sys.stderr)
        return []


# ════════════════════════════════════════════════════════
# 融合搜索入口
# ════════════════════════════════════════════════════════

def fusion_search(query: str, boost: float = 0.3,
                  kg_only: bool = False, rrf_only: bool = False,
                  rrf_fn=None) -> dict:
    """融合搜索入口

    返回:
    {
        "query": str,
        "analysis": dict,
        "rrf_results": [(path, score, snippet), ...] or None,
        "kg_results": {path: kg_info} or None,
        "fused_results": [(path, final, snippet, rrf, kg, reasons), ...],
    }
    """
    # 1. 查询分析
    analysis = analyze_query(query)

    result = {
        "query": query,
        "analysis": analysis,
        "rrf_results": None,
        "kg_results": None,
        "fused_results": [],
    }

    # 2. KG 搜索（除非 rrf_only）
    if not rrf_only:
        result["kg_results"] = kg_search(analysis)

    # 3. RRF 搜索（除非 kg_only）
    if not kg_only:
        fn = rrf_fn or rrf_search_fallback
        result["rrf_results"] = fn(query, limit=20)

    # 4. 融合
    rrf_empty = result["rrf_results"] is None or len(result["rrf_results"]) == 0
    if rrf_empty and result["kg_results"]:
        # RRF不可用，降级为纯KG结果
        if not rrf_only:  # 只有非手动纯KG模式才打印降级提示
            print("  ⚠️  RRF 搜索不可用，降级为纯 KG 结果", file=sys.stderr)
        if result["kg_results"]:
            sorted_kg = sorted(result["kg_results"].items(), key=lambda x: -x[1]["score"])
            result["fused_results"] = [
                (path, info["score"], "", 0, info["score"], info["reasons"])
                for path, info in sorted_kg
            ]
    elif rrf_only or result["rrf_results"] is None:
        # 纯KG模式：直接用 KG 结果排序
        if result["kg_results"]:
            sorted_kg = sorted(result["kg_results"].items(), key=lambda x: -x[1]["score"])
            result["fused_results"] = [
                (path, info["score"], "", 0, info["score"], info["reasons"])
                for path, info in sorted_kg
            ]
    elif kg_only:
        pass  # fused 保持空
    else:
        result["fused_results"] = fusion_rank(
            result["rrf_results"],
            result["kg_results"],
            boost=boost,
        )

    return result


# ════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════

def _print_analysis(analysis: dict):
    """打印查询分析结果"""
    print(f"\n📊 查询分析:")
    print(f"  精确匹配实体: {analysis.get('matched_entity', '无')}")
    print(f"  主要类型: {analysis.get('primary_type', '无')}")
    print(f"  KG实体匹配: {len(analysis['entities'])}个")
    for e in analysis["entities"][:5]:
        print(f"    [{e['type']}] {e['name']}")
    if analysis["related_entities"]:
        print(f"  关联实体: {len(analysis['related_entities'])}个")
        for e in analysis["related_entities"][:3]:
            print(f"    [{e['type']}] {e['name']}")
    if analysis["entity_notes"]:
        total_notes = sum(len(ns) for ns in analysis["entity_notes"].values())
        print(f"  KG关联笔记: {total_notes}篇")


def main():
    parser = argparse.ArgumentParser(description="KG+RRF 融合搜索")
    parser.add_argument("query", nargs="?", help="搜索查询")
    parser.add_argument("--boost", type=float, default=0.3, help="KG增强系数 (默认0.3)")
    parser.add_argument("--kg-only", action="store_true", help="仅KG搜索")
    parser.add_argument("--rrf-only", action="store_true", help="仅RRF搜索")
    parser.add_argument("--analyze", action="store_true", help="仅显示查询分析")
    parser.add_argument("--json", action="store_true", help="输出JSON")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        return

    # 查询分析
    analysis = analyze_query(args.query)
    if args.analyze:
        _print_analysis(analysis)
        return

    # 融合搜索
    result = fusion_search(
        args.query,
        boost=args.boost,
        kg_only=args.kg_only,
        rrf_only=args.rrf_only,
    )

    if args.json:
        # 简化输出，避免循环引用
        output = {
            "query": result["query"],
            "matched_entity": result["analysis"].get("matched_entity"),
            "kg_match_count": len(result.get("kg_results", {}) or {}),
            "rrf_match_count": len(result.get("rrf_results", []) or []),
            "fusion_results": [
                {"path": p, "final_score": f, "rrf_score": r, "kg_score": k, "reasons": rs}
                for p, f, _, r, k, rs in result["fused_results"][:10]
            ],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 人类可读输出
    _print_analysis(analysis)

    if result["rrf_results"]:
        print(f"\n🔍 RRF 结果 ({len(result['rrf_results'])}条):")
        for p, s, _ in result["rrf_results"][:5]:
            print(f"  {s:.3f}  {Path(p).name}")

    kg_results = result.get("kg_results") or {}
    if kg_results:
        print(f"\n🧠 KG 结果 ({len(kg_results)}条):")
        for path, info in sorted(kg_results.items(), key=lambda x: -x[1]["score"])[:5]:
            reasons = "; ".join(info["reasons"][:2])
            print(f"  {info['score']:.1f}  {Path(path).name}  ({reasons})")

    if result["fused_results"]:
        print(f"\n✅ 融合结果 ({len(result['fused_results'])}条):")
        for i, (path, final, _, rrf, kg, reasons) in enumerate(result["fused_results"][:10], 1):
            boost_info = f"KG+{kg:.1f}" if kg > 0 else ""
            reasons_str = f" — {'; '.join(reasons[:2])}" if reasons else ""
            print(f"  {i:2d}. {final:.3f}  {Path(path).name}  (RRF={rrf:.3f} {boost_info}){reasons_str}")
    else:
        print("\n⚠️  无融合结果")


if __name__ == "__main__":
    main()
