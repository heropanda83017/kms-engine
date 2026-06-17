#!/usr/bin/env python3
"""
from _path_setup import WIKI_DIR
health_check.py — KMS 第二大脑健康检查引擎

第二大脑健康管理系统 (08-investment/00-系统/第二大脑健康管理系统.md) 的 Layer 2 实现。
检测指标:
  1. orphan       — 孤立文件 (0 incoming wiki links)
  2. broken-links — 断裂链接 ([[target]] 目标文件不存在)
  3. no-score     — 无 score 字段的文件
  4. no-fm        — 无 frontmatter 的文件
  5. shell        — 空壳文件 (body < 200 字)

用法:
  python health_check.py                    # 全部检查, 终端输出
  python health_check.py --check orphan     # 单项检查
  python health_check.py --fix              # 自动修复低风险问题 (空壳删除)
  python health_check.py --report           # 生成 Markdown 报告
  python health_check.py --watch            # 持续监控 (每 30 分钟)
"""

import os, re, sys, json, time, argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

WIKI = WIKI_DIR


# ── 检查项 ─────────────────────────────────────────────

def find_md_files() -> list[Path]:
    """获取所有 wiki .md 文件 (排除 .bak / archive)"""
    files = []
    for f in sorted(WIKI.rglob("*.md")):
        if ".bak" in str(f) or "/archive/" in str(f):
            continue
        files.append(f)
    return files


def build_link_index(files: list[Path]) -> dict[str, set[str]]:
    """
    构建 wiki 链接索引。
    - targets: {target_stem: [source_relpath, ...]}
    - 用于检测孤立文件: 某文件 stem 出现在 targets 中则非孤立
    """
    targets = defaultdict(set)
    for f in files:
        rel = str(f.relative_to(WIKI))
        content = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'\[\[([^\]]+)\]\]', content):
            link_raw = m.group(1)
            link_clean = link_raw.split("#")[0].split("|")[0].strip()
            if link_clean.startswith("http"):
                continue
            targets[link_clean].add(rel)
    return dict(targets)


def check_orphan(files: list[Path], link_index: dict) -> list[dict]:
    """检测孤立文件 (0 incoming wiki links)"""
    orphans = []
    for f in files:
        rel = str(f.relative_to(WIKI))
        stem = f.stem
        # 检查该文件是否被任何其他文件引用
        incoming = set()
        for target, sources in link_index.items():
            if stem in target or target in stem or target == stem:
                incoming.update(sources)
        # 排除自引用
        incoming = {s for s in incoming if s != rel}
        if not incoming:
            orphans.append({
                "path": rel,
                "size_kb": f.stat().st_size // 1024,
                "incoming": 0,
            })
    return orphans


def check_broken_links(files: list[Path]) -> list[dict]:
    """检测断裂链接"""
    # Build set of all existing stems
    all_stems = set()
    all_paths = set()
    for f in files:
        rel = str(f.relative_to(WIKI))
        all_stems.add(f.stem)
        all_paths.add(rel)

    broken = []
    for f in files:
        rel = str(f.relative_to(WIKI))
        content = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'\[\[([^\]]+)\]\]', content):
            link_raw = m.group(1)
            link_clean = link_raw.split("#")[0].split("|")[0].strip()
            if link_clean.startswith("http"):
                continue
            # Check all possible match forms
            exists = False
            check_forms = [link_clean, link_clean + ".md"]
            for cf in check_forms:
                if cf in all_stems or cf in all_paths:
                    exists = True
                    break
                # Check as partial path
                for ap in all_paths:
                    if cf in ap:
                        exists = True
                        break
                if exists:
                    break
            # Check relative to parent
            if not exists:
                test_path = (f.parent / link_clean).resolve()
                if test_path.exists() or test_path.with_suffix(".md").exists():
                    exists = True

            if not exists:
                broken.append({
                    "source": rel,
                    "target": link_raw,
                })
    return broken


def check_no_score(files: list[Path]) -> list[dict]:
    """检测无 score 字段的文件"""
    no_score = []
    for f in files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        if content.startswith("---"):
            fm_end = content.index("---", 3)
            fm = content[3:fm_end]
            if "score:" not in fm:
                no_score.append({
                    "path": str(f.relative_to(WIKI)),
                    "size_kb": f.stat().st_size // 1024,
                })
        else:
            # No frontmatter at all = also no score
            no_score.append({
                "path": str(f.relative_to(WIKI)),
                "size_kb": f.stat().st_size // 1024,
            })
    return no_score


def check_no_fm(files: list[Path]) -> list[dict]:
    """检测无 frontmatter 的文件"""
    no_fm = []
    for f in files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("---"):
            no_fm.append({
                "path": str(f.relative_to(WIKI)),
                "size_kb": f.stat().st_size // 1024,
            })
    return no_fm


def check_shell(files: list[Path]) -> list[dict]:
    """检测空壳文件 (body < 200 字)"""
    shells = []
    for f in files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            body = parts[2] if len(parts) >= 3 else parts[1] if len(parts) == 2 else content
        body_text = re.sub(r'\s+', '', body)  # strip whitespace
        if len(body_text) < 200:
            shells.append({
                "path": str(f.relative_to(WIKI)),
                "chars": len(body_text),
            })
    return shells


def check_stale(files: list[Path], months: int = 6) -> list[dict]:
    """检测过期知识: 6个月未更新 + 0入链 = 可归档标记

    使用 frontmatter 中的 updated 字段, 若无则用文件 mtime。
    同时检测入链数: 0入链 + 过期 = 双倍过期 (建议归档)
    """
    from datetime import datetime, timezone
    cutoff = datetime.now(timezone.utc).timestamp() - months * 30 * 86400
    now = datetime.now(timezone.utc)

    # Build incoming link index
    incoming = defaultdict(set)
    for f in files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        src = str(f.relative_to(WIKI))
        for m in re.finditer(r'\[\[([^\]]+)\]\]', content):
            target = m.group(1).split("#")[0].split("|")[0].strip()
            if not target.startswith("http"):
                incoming[target].add(src)

    stale_items = []
    for f in files:
        rel = str(f.relative_to(WIKI))
        content = f.read_text(encoding="utf-8", errors="ignore")

        # 1. 读取最后更新日期
        updated_str = None
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm = content[3:end]
                for line in fm.strip().split("\n"):
                    if line.strip().startswith("updated:"):
                        updated_str = line.split(":", 1)[1].strip().strip("'\"")
                        break

        # 2. 计算是否过期
        is_stale = False
        last_updated = ""
        if updated_str:
            try:
                updated_dt = datetime.fromisoformat(updated_str)
                if hasattr(updated_dt, 'tzinfo') and updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                last_updated = updated_dt.strftime("%Y-%m-%d")
                is_stale = updated_dt.timestamp() < cutoff
            except (ValueError, TypeError):
                pass
        else:
            # Fallback to file mtime
            mtime = f.stat().st_mtime
            last_updated = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
            is_stale = mtime < cutoff

        if not is_stale:
            continue

        # 3. 计算入链数
        stem = f.stem
        sources = set()
        for t, srcs in incoming.items():
            if stem == t or stem in t or t in stem:
                sources.update(srcs)
        sources.discard(rel)
        in_degree = len(sources)

        stale_items.append({
            "path": rel,
            "size_kb": f.stat().st_size // 1024,
            "last_updated": last_updated,
            "in_degree": in_degree,
            "stale_level": "🔴 双倍过期" if in_degree == 0 else "🟡 过期",
        })

    return stale_items


# ── 报告 ─────────────────────────────────────────────

def generate_report(files: list[Path],
                    orphans: list,
                    broken: list,
                    no_score: list,
                    no_fm: list,
                    shells: list) -> str:
    """生成 Markdown 报告"""
    icon = "🟢" if len(broken) == 0 and len(orphans) <= 5 and len(no_fm) == 0 else "🟡" if len(broken) < 50 else "🔴"
    report = f"""# KMS 健康检查报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
> 总文件数: {len(files)}

## 摘要

| 指标 | 数量 | 状态 |
|:----|:----|:----:|
| 孤立文件 (0引用) | {len(orphans)} | {"🔴" if len(orphans) > 5 else "🟡" if len(orphans) > 0 else "✅"} |
| 断裂链接 | {len(broken)} | {"🔴" if len(broken) > 50 else "🟡" if len(broken) > 0 else "✅"} |
| 无 score 字段 | {len(no_score)} | {"🔴" if len(no_score) > 10 else "🟡" if len(no_score) > 0 else "✅"} |
| 无 frontmatter | {len(no_fm)} | {"🔴" if len(no_fm) > 0 else "✅"} |
| 空壳文件 | {len(shells)} | {"🔴" if len(shells) > 0 else "✅"} |

## 详细信息

### 孤立文件 Top 10
"""
    for o in sorted(orphans, key=lambda x: -x["size_kb"])[:10]:
        report += f"- 🏝️ `{o['path']}` ({o['size_kb']}KB)\n"

    report += "\n### 断裂链接 Top 10\n"
    # Group by target for readability
    target_groups = defaultdict(list)
    for b in broken:
        target_groups[b["target"]].append(b["source"])
    for target, sources in sorted(target_groups.items(), key=lambda x: -len(x[1]))[:10]:
        report += f"- ❌ `[[{target}]]` → {len(sources)} 个文件\n"
        for s in sources[:3]:
            report += f"  - `{s}`\n"

    report += f"\n### 无 score 文件 ({len(no_score)})\n"
    if len(no_score) <= 20:
        for ns in no_score:
            report += f"- `{ns['path']}`\n"
    else:
        report += f"共 {len(no_score)} 个, 运行 `kms score --batch` 批量回溯\n"

    report += f"\n### 无 frontmatter 文件 ({len(no_fm)})\n"
    for nf in no_fm:
        report += f"- ⚠️ `{nf['path']}`\n"

    report += f"\n### 空壳文件 ({len(shells)})\n"
    for s in shells:
        report += f"- 📄 `{s['path']}` ({s['chars']}字)\n"

    return report


# ── CLI ─────────────────────────────────────────────

def main(cli_args: list[str] | None = None):
    parser = argparse.ArgumentParser(description="KMS 第二大脑健康检查")
    parser.add_argument("--check", choices=["orphan", "broken-links", "no-score", "no-fm", "shell", "stale"],
                        help="单项检查")
    parser.add_argument("--months", type=int, default=6, help="过期检测月数阈值 (默认6个月)")
    parser.add_argument("--fix", action="store_true", help="自动修复低风险问题")
    parser.add_argument("--report", action="store_true", help="生成 Markdown 报告")
    parser.add_argument("--watch", action="store_true", help="持续监控 (每 30 分钟)")
    args = parser.parse_args(args=cli_args)

    files = find_md_files()
    link_index = build_link_index(files)

    checks = {
        "orphan": lambda: check_orphan(files, link_index),
        "broken-links": lambda: check_broken_links(files),
        "no-score": lambda: check_no_score(files),
        "no-fm": lambda: check_no_fm(files),
        "shell": lambda: check_shell(files),
        "stale": lambda: check_stale(files, months=args.months),
    }

    if args.watch:
        print("📡 持续监控模式 (每 30 分钟)")
        while True:
            for name, fn in checks.items():
                result = fn()
                print(f"  {name}: {len(result)}")
            print(f"  --- {datetime.now().strftime('%H:%M')} ---")
            time.sleep(1800)
        return

    if args.check:
        result = checks[args.check]()
        print(f"📊 {args.check}: {len(result)}")
        for item in result[:10]:
            print(f"  {json.dumps(item, ensure_ascii=False)}")
        if len(result) > 10:
            print(f"  ... 还有 {len(result)-10} 个")
        return

    # 全部检查
    print("📋 KMS 健康检查...")
    t0 = time.time()
    results = {name: fn() for name, fn in checks.items()}
    elapsed = time.time() - t0
    t = len(files)

    # Summary line (machine parseable)
    print(f"HEALTH|{t}|orphan={len(results['orphan'])}|broken={len(results['broken-links'])}|noscore={len(results['no-score'])}|nofm={len(results['no-fm'])}|shell={len(results['shell'])}|stale={len(results['stale'])}|{elapsed:.1f}s")

    # Human readable
    icons = {
        "orphan": "🔴" if len(results["orphan"]) > 5 else "🟡",
        "broken-links": "🔴" if len(results["broken-links"]) > 50 else "🟡",
        "no-score": "🔴" if len(results["no-score"]) > 10 else "🟡",
        "no-fm": "🔴" if len(results["no-fm"]) > 0 else "✅",
        "shell": "🔴" if len(results["shell"]) > 0 else "✅",
        "stale": "🔴" if len(results["stale"]) > 10 else "🟡",
    }
    for name, items in results.items():
        print(f"  {icons[name]} {name}: {len(items)}")

    if args.report:
        report = generate_report(
            files,
            orphans=results.get("orphan", []),
            broken=results.get("broken-links", []),
            no_score=results.get("no-score", []),
            no_fm=results.get("no-fm", []),
            shells=results.get("shell", []),
        )
        report_path = WIKI / "08-investment" / "00-系统" / f"健康检查报告_{datetime.now().strftime('%Y%m%d')}.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"\n📄 报告已生成: {report_path.relative_to(WIKI)}")

    # Fix
    if args.fix:
        print("\n🔧 自动修复:")
        # Delete shells (safe: body < 200 chars)
        shells = results["shell"]
        if shells:
            for s in shells:
                if s["chars"] < 50:  # Only auto-delete truly empty files
                    p = WIKI / s["path"]
                    p.unlink()
                    print(f"  🗑️ 删除空壳: {s['path']}")
        else:
            print("  无空壳文件")

        # Report on what could be auto-fixed for broken links
        bl = results["broken-links"]
        if bl:
            print(f"  ⚠️  断裂链接 {len(bl)} 处 — 需人工判断, 不自动修复")


if __name__ == "__main__":
    main()
