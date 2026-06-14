#!/usr/bin/env python3
"""batch_kg_extract.py — 分批全库扫描，每批 N 篇，自动跳过已提取和超大文件"""
import sys, json, random, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _path_setup import WIKI_DIR
from kg_extract import extract_note, _load_progress

BATCH_SIZE = 10
MAX_FILE_SIZE = 50000  # 50KB
BATCH_INTERVAL = 2  # 批次间隔秒数
RANDOM_SEED = 42  # 保证批次可复现

def main():
    random.seed(RANDOM_SEED)
    progress = _load_progress()
    wiki = WIKI_DIR
    all_md = sorted(wiki.rglob("*.md"))
    all_md = [f for f in all_md if ".obsidian" not in str(f)]

    remaining = []
    for f in all_md:
        rel = str(f.relative_to(wiki)).replace("\\", "/")
        if rel in progress:
            continue
        if f.stat().st_size > MAX_FILE_SIZE:
            continue
        remaining.append(f)

    total_remaining = len(remaining)
    if total_remaining == 0:
        print("✅ 全库扫描完成，无可处理笔记")
        return

    random.shuffle(remaining)
    print(f"📊 待处理: {total_remaining} 篇 (每次{BATCH_SIZE}篇, ~{total_remaining//BATCH_SIZE}批)")

    total_extracted = 0
    total_failed = 0
    batch_num = 0

    while remaining:
        batch_num += 1
        batch = remaining[:BATCH_SIZE]
        remaining = remaining[BATCH_SIZE:]

        extracted = 0
        failed = 0
        for f in batch:
            result = extract_note(f, verbose=False)
            if result:
                extracted += 1
                print(f"  ✅ [{extracted}/{len(batch)}] {f.name} -> {len(result['entities'])}e/{len(result['relations'])}r")
            else:
                failed += 1

        total_extracted += extracted
        total_failed += failed

        # 进度统计
        now_progress = _load_progress()
        print(f"  📈 批{batch_num}: +{extracted}/{failed} | 累计: {len(now_progress)}篇/{total_remaining + len(now_progress)}总")

        if remaining:
            time.sleep(BATCH_INTERVAL)

    # 最终统计
    import datetime
    from kg_store import get_stats
    s = get_stats()
    print(f"\n{'='*50}")
    print(f"🎉 全库扫描完成！")
    print(f"  实体: {s['total_entities']}")
    print(f"  关系: {s['total_relations']}")
    print(f"  笔记: {s['notes_with_entities']}")
    print(f"  跳过(>50KB): 中际旭创/京东方等大笔记")

if __name__ == "__main__":
    main()
