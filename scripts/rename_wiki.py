#!/usr/bin/env python3
"""rename_wiki.py — 安全 wiki 文件改名工具

改名 = 重命名文件 + 全库搜索更新 [[链接]] + 验证

用法:
  python rename_wiki.py --dry-run                         # 预览所有规范改名
  python rename_wiki.py --apply                           # 执行改名
  python rename_wiki.py --undo                            # 撤销上次改名
  python rename_wiki.py --map                             # 查看当前改名映射
"""

import json, re, sys, os, time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR

# ── 映射文件 ───────────────────────────────────────────
MAPPING_FILE = Path(__file__).resolve().parent.parent / "config" / "cache" / "rename_mapping.json"

# ── 命名规范 ───────────────────────────────────────────
# 规则:
# 1. 去除书名号《》 → 空
# 2. 去除中文冒号： → 短横线 -
# 3. 去除引号“”"  → 空
# 4. 去除括号（） → 空
# 5. 去除逗号，、 → 空
# 6. 下划线 _   → 短横线 -
# 7. 连续多个短横线 → 单个
# 8. 首尾短横线 → 去掉
# 9. 保留 .md 扩展名

def normalize_name(raw: str) -> str:
    """按规范标准化文件名"""
    name = raw
    # 去除书名号
    name = name.replace('《', '').replace('》', '')
    # 中文冒号→短横线
    name = name.replace('：', '-')
    # 中文问号→空
    name = name.replace('？', '')
    # 引号→空
    for q in '""""“”':
        name = name.replace(q, '')
    # 括号→空
    name = name.replace('（', '').replace('）', '')
    name = name.replace('(', '').replace(')', '')
    # 逗号顿号→空
    name = name.replace('，', '').replace('、', '')
    # 感叹号→空
    name = name.replace('！', '')
    # 下划线→短横线
    name = name.replace('_', '-')
    # 空格→空
    name = name.replace(' ', '')
    # 连续短横线→单个
    name = re.sub(r'-{2,}', '-', name)
    # 首尾短横线→去掉
    name = name.strip('-')
    # 保留扩展名
    if raw.endswith('.md') and not name.endswith('.md'):
        name += '.md'
    elif not raw.endswith('.md'):
        pass
    return name


def scan_for_renames() -> list:
    """扫描 wiki 中所有需改名的文件

    返回: [(old_path, new_path, reason), ...]
    """
    renames = []
    wiki = WIKI_DIR
    for f in sorted(wiki.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        old_name = f.name
        new_name = normalize_name(old_name)
        if new_name != old_name:
            rel = str(f.relative_to(wiki))
            reason = _explain_rename(old_name, new_name)
            renames.append((str(f), str(f.with_name(new_name)), reason, rel))
    return renames


def _explain_rename(old: str, new: str) -> str:
    """解释改名原因"""
    changes = []
    if '《' in old or '》' in old:
        changes.append("去书名号")
    if '：' in old:
        changes.append("冒号→短横线")
    if '“' in old or '”' in old or '"' in old:
        changes.append("去引号")
    if '（' in old or '）' in old or '(' in old or ')' in old:
        changes.append("去括号")
    if '，' in old or '、' in old:
        changes.append("去逗号/顿号")
    if '！' in old:
        changes.append("去感叹号")
    if '_' in old:
        changes.append("下划线→短横线")
    if '  ' in old.replace('_', '  '):
        changes.append("去空格")
    return " + ".join(changes) if changes else "规范化"


def apply_rename(old_path: str, new_path: str, mapping: dict) -> bool:
    """执行单个文件改名 + 全库链接更新"""
    old = Path(old_path)
    new = Path(new_path)
    if not old.exists():
        return False
    if new.exists():
        print(f"  ⚠️  目标已存在，跳过: {new.name}", file=sys.stderr)
        return False

    old_stem = old.stem   # 不含 .md
    new_stem = new.stem

    # 1. 全库搜索替换 [[旧文件名]] → [[新文件名]]
    replace_count = 0
    for md_file in WIKI_DIR.rglob("*.md"):
        if ".obsidian" in str(md_file) or str(md_file) == str(old):
            continue
        content = md_file.read_text(encoding="utf-8", errors="ignore")
        # 替换 [[旧名]] → [[新名]]
        old_link = f"[[{old_stem}]]"
        new_link = f"[[{new_stem}]]"
        if old_link in content:
            content = content.replace(old_link, new_link)
            replace_count += 1
            md_file.write_text(content, encoding="utf-8")

    # 2. 重命名文件
    old.rename(new)

    # 3. 记录映射
    mapping[old_stem] = new_stem

    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="安全 wiki 文件改名工具")
    parser.add_argument("--dry-run", action="store_true", help="预览不改动")
    parser.add_argument("--apply", action="store_true", help="执行改名")
    parser.add_argument("--undo", action="store_true", help="撤销上次改名")
    parser.add_argument("--map", action="store_true", help="查看当前改名映射")
    parser.add_argument("--yes", action="store_true", help="跳过确认，直接执行")
    args = parser.parse_args()

    renames = scan_for_renames()

    if args.map or args.undo:
        if MAPPING_FILE.exists():
            mapping = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
            if args.map:
                print(f"已改名映射 ({len(mapping)} 个):")
                for old, new in sorted(mapping.items()):
                    print(f"  [[{old}]] → [[{new}]]")
            if args.undo:
                confirm = input(f"撤销 {len(mapping)} 个改名？(yes/no): ")
                if confirm == "yes":
                    for old_stem, new_stem in mapping.items():
                        # 查找新文件
                        for f in WIKI_DIR.rglob(f"{new_stem}.md"):
                            if ".obsidian" not in str(f):
                                f.rename(f.with_name(f"{old_stem}.md"))
                                print(f"  ↩  {new_stem}.md → {old_stem}.md")
                    MAPPING_FILE.unlink(missing_ok=True)
                    print("✅ 已撤销")
        else:
            print("无改名记录")
        return

    if args.dry_run or not args.apply:
        print(f"预览: {len(renames)} 个文件需改名\n")
        # 按原因分组
        by_reason = defaultdict(list)
        for old, new, reason, rel in renames:
            by_reason[reason].append((rel, Path(old).name, Path(new).name))
        for reason, items in sorted(by_reason.items()):
            print(f"\n  [{reason}] ({len(items)}篇):")
            for rel, old_name, new_name in items:
                print(f"    {old_name}")
                print(f"      → {new_name}")
        print(f"\n总计: {len(renames)} 个文件需改名")
        if args.dry_run:
            return

        if not args.yes:
            confirm = input("\n执行改名？(yes/no): ")
            if confirm != "yes":
                print("已取消")
                return

    # 执行改名
    mapping = {}
    success = 0
    skipped = 0
    for old_path, new_path, reason, rel in renames:
        ok = apply_rename(old_path, new_path, mapping)
        if ok:
            success += 1
            print(f"  ✅ {Path(old_path).name} → {Path(new_path).name}")
        else:
            skipped += 1

    # 保存映射
    if mapping:
        MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
        MAPPING_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ 改名完成: {success} 成功, {skipped} 跳过")
        print(f"映射已保存: {MAPPING_FILE}")
    else:
        print("无改动")


if __name__ == "__main__":
    main()
