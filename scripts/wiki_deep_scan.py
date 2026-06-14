#!/usr/bin/env python3
"""wiki_deep_scan.py — KMS 深度扫描 + 自动清理

覆盖 12 维健康扫描，支持 dry-run 预览和 apply 执行。

用法:
  python wiki_deep_scan.py                    # 全量扫描（只报告，不执行）
  python wiki_deep_scan.py --apply            # 扫描 + 执行 P0 清理
  python wiki_deep_scan.py --apply-p0         # 只执行 P0 清理
  python wiki_deep_scan.py --apply-all        # 执行全部清理（含 P0/P1/P2）
  python wiki_deep_scan.py --json             # JSON 输出
"""

import json, sys, re, shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR

# ── 阈值设定 ───────────────────────────────────────────
SHELL_FILE_CHARS = 50       # <50字正文 → 空壳
LARGE_FILE_LINES = 500      # >500行 → 大文件
HUGE_FILE_LINES = 2000      # >2000行 → 超大型
MIN_INCOMING_LINKS = 1      # 孤岛阈值（入链数）
STALE_KEYWORDS = [          # 过时引用关键词
    "blackhorse", "data-source-hub", "DSH_", "dsh_", "黑马量化",
    "Whoosh", "xwechat", "旧系统",
]

# ── 目录规范映射 ───────────────────────────────────────
DIR_DOMAIN_MAP = {
    "00-系统": ["concept", "domain", "method"],
    "00-个人": ["person", "concept"],
    "01-theory": ["concept", "domain", "method"],
    "02-AI核心": ["concept", "domain", "method", "tool"],
    "03-工具篇": ["tool", "method"],
    "04-tools": ["tool", "method"],
    "05-读书笔记": ["concept", "method", "person", "company", "domain"],
    "06-应用篇": ["concept"],
    "07-practices": ["method", "tool", "concept"],
    "08-investment": ["factor", "indicator", "company", "method", "concept", "tool"],
    "导航": [],
}


# ════════════════════════════════════════════════════════
# 12 维扫描
# ════════════════════════════════════════════════════════

def scan_shell_files() -> list:
    """① 空壳文件 — 正文 <50 字"""
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        body = _extract_body(content)
        if len(body.strip()) < SHELL_FILE_CHARS:
            rel = str(f.relative_to(WIKI_DIR))
            result.append({"path": rel, "chars": len(body.strip()), "size_kb": round(f.stat().st_size / 1024, 1)})
    return result


def scan_temp_files() -> list:
    """② 临时/残留文件"""
    result = []
    for f in sorted(WIKI_DIR.rglob("*")):
        if ".obsidian" in str(f) or not f.is_file():
            continue
        # .bak, .tmp, 日志文件
        if f.suffix in (".bak", ".tmp", ".log", ".swp"):
            rel = str(f.relative_to(WIKI_DIR))
            result.append({"path": rel, "suffix": f.suffix, "size_kb": round(f.stat().st_size / 1024, 1)})
        # Windows 桌面配置文件
        if f.name in ("desktop.ini", "Thumbs.db"):
            rel = str(f.relative_to(WIKI_DIR))
            result.append({"path": rel, "suffix": f.suffix, "size_kb": round(f.stat().st_size / 1024, 1)})
    return result


def scan_empty_dirs() -> list:
    """③ 空目录 — 没有 .md 文件的目录"""
    result = []
    for d in sorted(WIKI_DIR.rglob("*")):
        if ".obsidian" in str(d) or not d.is_dir():
            continue
        md_files = list(d.rglob("*.md"))
        if not md_files:
            rel = str(d.relative_to(WIKI_DIR))
            if rel:  # 不是根目录
                result.append({"path": rel})
    return result


def scan_no_frontmatter() -> list:
    """④ 无 frontmatter 的笔记"""
    import yaml
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        stripped = content.lstrip()
        if not stripped.startswith("---"):
            rel = str(f.relative_to(WIKI_DIR))
            result.append({"path": rel, "size_kb": round(f.stat().st_size / 1024, 1)})
        else:
            end = stripped.find("---", 3)
            if end == -1:
                rel = str(f.relative_to(WIKI_DIR))
                result.append({"path": rel, "reason": "frontmatter未闭合"})
            else:
                raw_fm = stripped[3:end].strip()
                try:
                    fm = yaml.safe_load(raw_fm) or {}
                    missing = []
                    for field in ("title", "type", "domain", "tags"):
                        if field not in fm or not fm[field]:
                            missing.append(field)
                    if missing:
                        rel = str(f.relative_to(WIKI_DIR))
                        result.append({"path": rel, "missing": missing})
                except Exception:
                    rel = str(f.relative_to(WIKI_DIR))
                    result.append({"path": rel, "reason": "frontmatter解析失败"})
    return result


def scan_empty_tags() -> list:
    """⑤ frontmatter tags 为空"""
    import yaml
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        stripped = content.lstrip()
        if stripped.startswith("---"):
            end = stripped.find("---", 3)
            if end != -1:
                raw_fm = stripped[3:end].strip()
                try:
                    fm = yaml.safe_load(raw_fm) or {}
                    tags = fm.get("tags", [])
                    if not tags or (isinstance(tags, list) and len(tags) == 0):
                        rel = str(f.relative_to(WIKI_DIR))
                        result.append({"path": rel})
                except Exception:
                    pass
    return result


def scan_broken_links() -> list:
    """⑥ 断裂链接 — [[目标]] 文件不存在"""
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        links = re.findall(r'\[\[([^\]]+)\]\]', content)
        f_rel = str(f.relative_to(WIKI_DIR))
        for link in links:
            target = link.split("|")[0].strip()
            if target.endswith(".md"):
                target = target[:-3]
            # 跳过外部链接（含 / 的路径）
            if "/" in target or "\\" in target:
                continue
            # 检查文件是否存在
            found = list(WIKI_DIR.rglob(f"{target}.md"))
            if not found:
                # 检查是否是目录名引用
                dir_target = WIKI_DIR / target
                if not dir_target.exists() or not dir_target.is_dir():
                    result.append({"source": f_rel, "target": target, "link": link})
    return result


def scan_orphans(incoming_links: dict = None) -> list:
    """⑦ 孤岛笔记 — 0 入链"""
    if incoming_links is None:
        incoming_links = _build_link_graph()
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f) or f.name in ("CHANGELOG.md", "EVOLUTION.md"):
            continue
        rel = str(f.relative_to(WIKI_DIR))
        if incoming_links.get(rel, 0) == 0:
            result.append({"path": rel, "size_kb": round(f.stat().st_size / 1024, 1)})
    return result


def scan_old_references() -> list:
    """⑧ 过时引用 — 含旧系统关键词"""
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore").lower()
        matched = [kw for kw in STALE_KEYWORDS if kw.lower() in content]
        if matched:
            rel = str(f.relative_to(WIKI_DIR))
            result.append({"path": rel, "keywords": matched, "size_kb": round(f.stat().st_size / 1024, 1)})
    return result


def scan_large_files() -> list:
    """⑨ 大文件 — 需精华摘要"""
    result = []
    has_kg = True
    try:
        from kg_store import get_entities_for_note
    except ImportError:
        has_kg = False

    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f) or f.name in ("CHANGELOG.md", "EVOLUTION.md"):
            continue
        lines = f.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
        if lines >= LARGE_FILE_LINES:
            rel = str(f.relative_to(WIKI_DIR))
            entities = []
            if has_kg and rel:
                try:
                    entities = get_entities_for_note(rel)
                except Exception:
                    pass
            result.append({
                "path": rel,
                "lines": lines,
                "level": "huge" if lines >= HUGE_FILE_LINES else "large",
                "entities": [e.get("name", "") for e in entities[:5]],
            })
    return result


def _extract_body(content):
    """⑩ 低质量笔记 — 短内容 + 无 frontmatter + 孤岛"""
    content_scores = {}
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        body = _extract_body(content)
        rel = str(f.relative_to(WIKI_DIR))
        content_scores[rel] = len(body.strip())
    return content_scores


def scan_naming_issues() -> list:
    """⑪ 命名违规 — 仍含下划线或特殊字符"""
    result = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        name = f.name
        issues = []
        if "_" in name:
            issues.append("含下划线")
        for ch in "《》（）！？，、：；“”":
            if ch in name:
                issues.append(f"含特殊字符「{ch}」")
        if issues:
            rel = str(f.relative_to(WIKI_DIR))
            result.append({"path": rel, "issues": issues})
    return result


def scan_near_duplicates_by_name() -> list:
    """⑫ 近似文件名 — 可能重复"""
    files_by_stem = defaultdict(list)
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f):
            continue
        stem = f.stem.lower()
        # 去日期前缀比较
        clean = re.sub(r"^\d{8}-", "", stem)
        files_by_stem[clean].append(str(f.relative_to(WIKI_DIR)))
    return {k: v for k, v in files_by_stem.items() if len(v) > 1}


# ════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════

def _extract_body(content: str) -> str:
    """提取 frontmatter 后的正文"""
    stripped = content.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            return stripped[end + 3:].strip()
    return stripped


def _build_link_graph() -> dict:
    """构建入链图"""
    titles = {}
    for f in WIKI_DIR.rglob("*.md"):
        if ".obsidian" in str(f):
            continue
        rel = str(f.relative_to(WIKI_DIR))
        content = f.read_text(encoding="utf-8", errors="ignore")
        # 取文件名（不含扩展名）作为标题
        titles[rel] = f.stem

    incoming = defaultdict(int)
    for f in WIKI_DIR.rglob("*.md"):
        if ".obsidian" in str(f):
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        f_rel = str(f.relative_to(WIKI_DIR))
        for link_rel, title in titles.items():
            if link_rel == f_rel:
                continue
            if f"[[{title}]]" in content or f"[[{title}|" in content:
                incoming[link_rel] += 1
    return incoming


# ════════════════════════════════════════════════════════
# 清理执行
# ════════════════════════════════════════════════════════

def clean_shell_files(items: list, dry_run: bool = True) -> int:
    """删除空壳文件"""
    count = 0
    for item in items:
        path = WIKI_DIR / item["path"]
        if dry_run:
            print(f"  [DRY-RUN] 删除空壳: {item['path']} ({item['chars']}字)")
        else:
            path.unlink()
            print(f"  ✅ 删除空壳: {item['path']}")
        count += 1
    return count


def clean_temp_files(items: list, dry_run: bool = True) -> int:
    """删除临时文件"""
    count = 0
    for item in items:
        path = WIKI_DIR / item["path"]
        if dry_run:
            print(f"  [DRY-RUN] 删除临时: {item['path']}")
        else:
            path.unlink()
            print(f"  ✅ 删除临时: {item['path']}")
        count += 1
    return count


def clean_empty_dirs(items: list, dry_run: bool = True) -> int:
    """删除空目录"""
    count = 0
    for item in items:
        path = WIKI_DIR / item["path"]
        if not path.exists():
            continue
        if dry_run:
            print(f"  [DRY-RUN] 删除空目录: {item['path']}")
        else:
            try:
                path.rmdir()
                print(f"  ✅ 删除空目录: {item['path']}")
            except OSError:
                print(f"  ⚠️  目录非空: {item['path']}")
        count += 1
    return count


# ════════════════════════════════════════════════════════
# CLi
# ════════════════════════════════════════════════════════

def print_report(results: dict):
    s = results["summary"]
    dt = results["details"]

    print(f"\n{'='*58}")
    print(f"  📊 KMS 深度扫描报告 — {results['scanned_at']}")
    print(f"{'='*58}")
    print(f"\n📈 概览: {s['total_notes']} 篇笔记 | {s['total_dirs']} 个目录")
    print(f"     {s['total_lines']:,} 行 | 平均 {s['avg_lines']} 行/篇")
    print(f"\n🚩 12 维健康检查:")

    for dim, title, emoji in [
        ("shell_files", "空壳文件", "①"),
        ("temp_files", "临时文件", "②"),
        ("empty_dirs", "空目录", "③"),
        ("no_frontmatter", "无frontmatter", "④"),
        ("empty_tags", "tags为空", "⑤"),
        ("broken_links", "断裂链接", "⑥"),
        ("orphans", "孤岛笔记", "⑦"),
        ("old_refs", "过时引用", "⑧"),
        ("large_files", "需精减大文件", "⑨"),
        ("low_quality", "低质量(<200字)", "⑩"),
        ("naming_issues", "命名违规", "⑪"),
        ("near_dupes", "近似文件名", "⑫"),
    ]:
        count = len(dt.get(dim, []))
        flag = "🔴" if count > 10 else ("🟡" if count > 0 else "✅")
        print(f"  {emoji} {flag} {title}: {count}")

    # 逐项详情
    if dt.get("shell_files"):
        print(f"\n{'─'*58}\n① 空壳文件 (<50字):")
        for item in dt["shell_files"][:10]:
            print(f"    {item['path']} ({item['chars']}字)")

    if dt.get("temp_files"):
        print(f"\n{'─'*58}\n② 临时文件:")
        for item in dt["temp_files"][:10]:
            print(f"    {item['path']}")

    if dt.get("empty_dirs"):
        print(f"\n{'─'*58}\n③ 空目录:")
        for item in dt["empty_dirs"][:10]:
            print(f"    {item['path']}/")

    if dt.get("no_frontmatter"):
        print(f"\n{'─'*58}\n④ 无 frontmatter:")
        for item in dt["no_frontmatter"][:10]:
            extra = f" — 缺: {', '.join(item.get('missing', []))}" if "missing" in item else ""
            extra = extra or (f" — {item.get('reason', '')}" if "reason" in item else "")
            print(f"    {item['path']}{extra}")

    if dt.get("old_refs"):
        print(f"\n{'─'*58}\n⑧ 过时引用:")
        for item in dt["old_refs"][:10]:
            print(f"    {item['path']} → {', '.join(item['keywords'])}")

    if dt.get("large_files"):
        print(f"\n{'─'*58}\n⑨ 大文件:")
        for item in dt["large_files"][:8]:
            icon = "🔴" if item["level"] == "huge" else "🟡"
            ents = f" ({', '.join(item['entities'][:3])})" if item.get("entities") else ""
            print(f"    {icon} {item['path']} ({item['lines']}行){ents}")

    if dt.get("naming_issues"):
        print(f"\n{'─'*58}\n⑪ 命名违规:")
        for item in dt["naming_issues"][:10]:
            print(f"    {item['path']} → {', '.join(item['issues'])}")

    if dt.get("near_dupes"):
        print(f"\n{'─'*58}\n⑫ 近似文件名:")
        for stem, paths in list(dt["near_dupes"].items())[:10]:
            print(f"    「{stem}」:")
            for p in paths:
                print(f"      - {p}")

    print(f"\n{'='*58}")
    print(f"  清理建议: --apply (P0) | --apply-all (全部)")
    print(f"{'='*58}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KMS 深度扫描 + 自动清理")
    parser.add_argument("--apply", action="store_true", help="执行 P0 清理（空壳/临时/空目录）")
    parser.add_argument("--apply-all", action="store_true", help="执行全部清理（含P1/P2）")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--dry-run", action="store_true", help="预览不执行")
    args = parser.parse_args()

    # 执行扫描
    print("🔄 正在深度扫描... (12维)")
    shell_files = scan_shell_files()
    temp_files = scan_temp_files()
    empty_dirs = scan_empty_dirs()
    no_fm = scan_no_frontmatter()
    empty_tags = scan_empty_tags()
    broken = scan_broken_links()
    # 孤岛检测需要入链图，先构建
    link_graph = _build_link_graph()
    orphans = scan_orphans(link_graph)
    old_refs = scan_old_references()
    large = scan_large_files()
    naming = scan_naming_issues()
    near_dupes = scan_near_duplicates_by_name()

    # 低质量：正文 <200 字
    quality_scores = scan_low_quality()
    low_quality = [{"path": p, "chars": c} for p, c in sorted(quality_scores.items()) if 0 < c < 200]

    # 总计
    all_md = [f for f in WIKI_DIR.rglob("*.md") if ".obsidian" not in str(f)]
    total_lines = sum(
        f.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
        for f in all_md
    )
    total_dirs = len([d for d in WIKI_DIR.rglob("*") if d.is_dir() and ".obsidian" not in str(d)])

    results = {
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "total_notes": len(all_md),
            "total_dirs": total_dirs,
            "total_lines": total_lines,
            "avg_lines": round(total_lines / len(all_md), 1) if all_md else 0,
        },
        "details": {
            "shell_files": shell_files,
            "temp_files": temp_files,
            "empty_dirs": empty_dirs,
            "no_frontmatter": no_fm,
            "empty_tags": empty_tags,
            "broken_links": broken,
            "orphans": orphans,
            "old_refs": old_refs,
            "large_files": large,
            "low_quality": low_quality,
            "naming_issues": naming,
            "near_dupes": near_dupes,
        },
    }

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print_report(results)

    # 执行清理
    should_apply = args.apply or args.apply_all
    dry_run = not should_apply or args.dry_run

    if should_apply:
        print(f"\n{'='*58}")
        print(f"  {'🧹 DRY-RUN 模式' if dry_run else '🔧 执行清理'}")
        print(f"{'='*58}")

        # P0: 安全清理
        print(f"\n📦 P0 — 删除空壳文件 ({len(shell_files)}个)")
        clean_shell_files(shell_files, dry_run=dry_run)

        print(f"\n📦 P0 — 删除临时文件 ({len(temp_files)}个)")
        clean_temp_files(temp_files, dry_run=dry_run)

        print(f"\n📦 P0 — 删除空目录 ({len(empty_dirs)}个)")
        clean_empty_dirs(empty_dirs, dry_run=dry_run)

        if not dry_run:
            print(f"\n✅ P0 清理完成")
            # 重新扫描验证
            print(f"\n🔄 清理后重新扫描...")
            remaining_shell = len(scan_shell_files())
            remaining_temp = len(scan_temp_files())
            remaining_dirs = len(scan_empty_dirs())
            print(f"  剩余空壳: {remaining_shell} | 临时: {remaining_temp} | 空目录: {remaining_dirs}")

    if args.apply_all and not dry_run:
        # P1/P2: 需要谨慎的清理
        print(f"\n⚠️  apply-all 模式需要手动确认每项操作")


if __name__ == "__main__":
    main()
