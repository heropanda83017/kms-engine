"""wiki_maintenance.py — Wiki 自维护系统

功能:
  1. 写前查重: 在创建新笔记前扫描已有笔记，发现重叠→自动合并
  2. 内容成熟度: 跟踪笔记更新频率，多次更新后提示梳理

用法:
    python3 scripts/wiki_maintenance.py check  # 检查所有笔记的健康状态
    python3 scripts/wiki_maintenance.py merge <topic>  # 合并某主题的笔记
    python3 scripts/wiki_maintenance.py audit  # 全量审计
"""

import os
import re
import sys
import json
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("wiki_maintenance")

# Wiki 根目录
WIKI_ROOT = Path(os.environ.get("KMS_WIKI", "/mnt/e/AIGC-KB/wiki-AIGC-KB"))

# 更新追踪文件
TRACKING_FILE = Path(__file__).parent.parent / "data" / "wiki_update_tracking.json"


def _load_tracking() -> dict:
    """加载笔记更新追踪数据"""
    if TRACKING_FILE.exists():
        try:
            return json.loads(TRACKING_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_tracking(data: dict):
    TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _get_all_wiki_files() -> List[Path]:
    """获取所有 wiki markdown 文件"""
    return list(WIKI_ROOT.rglob("*.md"))


def _extract_title(filepath: Path) -> str:
    """从 markdown 第一行提取标题"""
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("# "):
            return line[2:].strip()
    return filepath.stem


def _extract_tags(filepath: Path) -> List[str]:
    """从 YAML frontmatter 提取 tags"""
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^---\ntags:\s*\[([^\]]+)\]", content, re.MULTILINE)
    if match:
        return [t.strip() for t in match.group(1).split(",")]
    return []


def _get_keywords(text: str) -> set:
    """提取关键词（中文+英文词）"""
    # 中文
    cn_words = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    # 英文
    en_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", text.lower()))
    return cn_words | en_words


def _keyword_overlap(keywords1: set, keywords2: set) -> float:
    """计算两个关键词集合的重叠率"""
    if not keywords1 or not keywords2:
        return 0.0
    intersection = keywords1 & keywords2
    return len(intersection) / max(len(keywords1), len(keywords2))


# ═══════════════════════════════════════════════════════════════
# 功能1: 写前查重
# ═══════════════════════════════════════════════════════════════

def find_overlapping_notes(
    new_title: str,
    new_content: str,
    new_tags: List[str] = None,
    threshold: float = 0.3,
) -> List[Dict]:
    """在新笔记写入前，扫描已有笔记查找重叠内容

    参数:
        new_title: 新笔记标题
        new_content: 新笔记完整内容
        new_tags: 新笔记标签
        threshold: 关键词重叠阈值（0-1），超过则视为重叠

    返回:
        [{"path": "相对路径", "title": str, "overlap": float, "action": "merge"|"append"|"单独"}]
    """
    new_keywords = _get_keywords(new_title + " " + new_content)
    if not new_keywords:
        return []

    results = []
    for wf in _get_all_wiki_files():
        if wf.name.startswith("_"):
            continue
        try:
            existing = wf.read_text(encoding="utf-8", errors="ignore")
            existing_keywords = _get_keywords(existing)
            overlap = _keyword_overlap(new_keywords, existing_keywords)

            if overlap >= threshold:
                # 判断是「合并」还是「追加」
                existing_title = _extract_title(wf)
                if new_title == existing_title:
                    action = "append"
                elif overlap >= 0.5:
                    action = "merge"
                else:
                    action = "单独"

                results.append({
                    "path": str(wf.relative_to(WIKI_ROOT)),
                    "title": existing_title,
                    "overlap": round(overlap, 2),
                    "action": action,
                })
        except Exception:
            continue

    return sorted(results, key=lambda x: x["overlap"], reverse=True)


def suggest_consolidation(overlapping: List[Dict]) -> List[Dict]:
    """根据查重结果，建议哪些笔记应该合并"""
    # 按 action 分组
    to_merge = [r for r in overlapping if r["action"] in ("merge", "append")]
    return to_merge


# ═══════════════════════════════════════════════════════════════
# 功能2: 内容成熟度检测
# ═══════════════════════════════════════════════════════════════

def record_update(filepath: str):
    """记录一次笔记更新"""
    tracking = _load_tracking()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if filepath not in tracking:
        tracking[filepath] = {"updates": [], "total_updates": 0}
    
    tracking[filepath]["updates"].append(today)
    tracking[filepath]["total_updates"] += 1
    
    # 只保留最近30天的更新记录
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    tracking[filepath]["updates"] = [
        d for d in tracking[filepath]["updates"] if d >= cutoff
    ]
    
    _save_tracking(tracking)


def check_maturity() -> List[Dict]:
    """检查所有笔记的成熟度

    返回:
        [{"path": str, "updates_30d": int, "total_updates": int,
          "needs_consolidation": bool, "reason": str}]
    """
    tracking = _load_tracking()
    results = []
    
    for filepath, data in tracking.items():
        total = data.get("total_updates", 0)
        recent = len(data.get("updates", []))
        
        needs = False
        reason = ""
        
        if total >= 10:
            needs = True
            reason = f"已更新{total}次，建议检查是否需要拆分或归档"
        elif recent >= 5:
            needs = True
            reason = f"近30天更新{recent}次，内容可能已膨胀需要重组"
        elif total >= 5 and recent >= 3:
            needs = True
            reason = f"更新频繁({recent}/30d, 总计{total})，建议做一次梳理"
        
        results.append({
            "path": filepath,
            "updates_30d": recent,
            "total_updates": total,
            "needs_consolidation": needs,
            "reason": reason,
        })
    
    return sorted(results, key=lambda x: x["total_updates"], reverse=True)


def audit_redundancy() -> List[Dict]:
    """全量审计：扫描所有笔记对，找出高重叠的配对

    返回:
        [{"pair": (str, str), "overlap": float}, ...]
    """
    files = _get_all_wiki_files()
    contents = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            contents[str(f.relative_to(WIKI_ROOT))] = _get_keywords(text)
        except Exception:
            continue

    pairs = []
    paths = list(contents.keys())
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            if i != j:
                overlap = _keyword_overlap(contents[paths[i]], contents[paths[j]])
                if overlap >= 0.4:  # 高重叠阈值
                    pairs.append({
                        "pair": (paths[i], paths[j]),
                        "overlap": round(overlap, 2),
                    })

    return sorted(pairs, key=lambda x: x["overlap"], reverse=True)


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Wiki 自维护系统")
    parser.add_argument("command", choices=["check", "audit", "merge"],
                        help="check=健康检查, audit=全量审计, merge=合并")
    parser.add_argument("--topic", help="合并指定主题")
    args = parser.parse_args()

    if args.command == "check":
        print(f"\n📊 Wiki 笔记成熟度检查\n{'='*40}")
        results = check_maturity()
        needs_work = [r for r in results if r["needs_consolidation"]]
        if needs_work:
            print(f"\n🔴 {len(needs_work)} 条笔记需要梳理：")
            for r in needs_work:
                print(f"  {r['path']}: {r['reason']}")
        else:
            print("\n🟢 所有笔记状态正常")
        print(f"\n共检查 {len(results)} 条追踪记录")

    elif args.command == "audit":
        print(f"\n🔍 Wiki 全量冗余审计\n{'='*40}")
        pairs = audit_redundancy()
        if pairs:
            print(f"\n发现 {len(pairs)} 对高重叠笔记：")
            for p in pairs[:10]:
                print(f"  {p['overlap']:.0%}: {p['pair'][0]} ↔ {p['pair'][1]}")
        else:
            print("\n🟢 未发现高重叠笔记对")

    elif args.command == "merge":
        if not args.topic:
            print("请指定主题: --topic <关键词>")
            sys.exit(1)
        print(f"\n🔗 合并主题: {args.topic}")
        # 查找相关笔记
        related = find_overlapping_notes(args.topic, args.topic,
                                          threshold=0.2)
        if related:
            print(f"找到 {len(related)} 篇相关笔记：")
            for r in related[:5]:
                print(f"  [{r['action']}] ({r['overlap']:.0%}) {r['path']}")
        else:
            print("未找到相关笔记")
