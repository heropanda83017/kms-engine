#!/usr/bin/env python3
"""
backup_system.py — 全体系备份工具 (2026-06-11)

备份范围:
  Profile 层 (4个)   → SOUL + MEMORY + USER + config + .env + scripts + skills + data
  Engine 层 (3个)    → Wiki + KMS + Investment
  API Keys 层 (3个)  → .env 文件

用法:
    python3 backup_system.py                    # 全量备份到 E:/AIGC-KB/备份/
    python3 backup_system.py --dry-run          # 预览模式（不实际复制）
    python3 backup_system.py --restore <时间戳>   # 从备份恢复

备份结构:
    E:/AIGC-KB/备份/
    └── backup-YYYYMMDD_HHMMSS/
        ├── profiles/
        │   ├── ai-investor/
        │   │   ├── SOUL.md / MEMORY.md / USER.md / config.yaml
        │   │   ├── .env / data/
        │   │   ├── scripts/ (42个)
        │   │   ├── prompt-templates/ (8个)
        │   │   ├── rules/ (6个)
        │   │   ├── hooks/ (session_start.sh等)
        │   │   ├── instincts/ (coding-patterns.yaml等)
        │   │   ├── skills-index.json
        │   │   └── cron/
        │   ├── land-of-dream-planning/
        │   │   ├── SOUL.md / MEMORY.md / USER.md / config.yaml / .env
        │   │   └── skills/
        │   └── trade-debt/
        │       ├── SOUL.md / MEMORY.md / USER.md / config.yaml / .env
        │       └── skills/
        ├── engines/
        │   ├── wiki-AIGC-KB/           (245 .md文件)
        │   ├── kms-engine/             (50 脚本)
        │   └── investment-engine/      (157MB, 策略+因子+回测)
        ├── manifest.json               (备份清单: 文件数/大小/时间)
        └── recovery.md                 (恢复指引)
"""
import json, os, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

# ── 路径 ──
HERMES_ROOT = Path.home() / ".hermes" / "profiles"
BACKUP_ROOT = Path("/mnt/e/AIGC-KB/备份")
WIKI_DIR = Path("/mnt/e/AIGC-KB/wiki-AIGC-KB")
KMS_DIR = Path("/mnt/e/AIGC-KB/kms-engine")
IE_DIR = Path("/mnt/e/AIGC-KB/investment-engine")
OUTPUT_DIR = Path("/mnt/e/AIGC-KB/输出")

# ── 需要备份的 profile 名称 ──
PROFILES = ["ai-investor", "land-of-dream-planning", "trade-debt"]


def dry(msg: str, dry_run: bool):
    print(f"  {'[DRY]' if dry_run else '  '} {msg}")


def profile_paths(profile_name: str) -> dict:
    """返回 profile 下需要备份的关键路径"""
    base = HERMES_ROOT / profile_name
    return {
        "SOUL.md": base / "SOUL.md",
        "config.yaml": base / "config.yaml",
        ".env": base / ".env",
        "memories": base / "memories",
        "scripts": base / "scripts",
        "prompt-templates": base / "prompt-templates",
        "rules": base / "rules",
        "hooks": base / "hooks",
        "instincts": base / "instincts",
        "data": base / "data",
        "skill_index": base / "skill_index.json",
        "skills": base / "skills",
        "cron": base / "cron",
    }


def backup(dry_run: bool = False):
    """执行全量备份"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / f"backup-{timestamp}"

    if not dry_run:
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        backup_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "timestamp": timestamp,
        "profiles": {},
        "engines": {},
        "total_size_mb": 0,
    }
    total_size = 0

    print(f"\n{'='*60}")
    print(f"  💾 全体系备份 — {timestamp}")
    print(f"{'='*60}")
    print(f"  目标: {backup_dir}\n")

    # ── 1. Profiles ──
    profiles_dir = backup_dir / "profiles" if not dry_run else None
    for name in PROFILES:
        paths = profile_paths(name)
        profile_size = 0

        if not paths["SOUL.md"].exists():
            dry(f"⚠️   {name}: SOUL.md 不存在, 跳过", dry_run)
            continue

        profile_dest = profiles_dir / name if profiles_dir else None
        if profile_dest and not dry_run:
            profile_dest.mkdir(parents=True, exist_ok=True)

        for key, src_path in paths.items():
            if src_path.exists():
                if src_path.is_dir():
                    # 递归统计大小
                    for f in src_path.rglob("*"):
                        if f.is_file():
                            profile_size += f.stat().st_size
                    if not dry_run:
                        dest = profile_dest / key
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(src_path, dest)
                    dry(f"📁 {name}/{key}/ ({sum(1 for _ in src_path.rglob('*'))} 文件)", dry_run)
                else:
                    sz = src_path.stat().st_size
                    profile_size += sz
                    if not dry_run:
                        shutil.copy2(src_path, profile_dest / f"{key}")
                    dry(f"📄 {name}/{key} ({sz/1024:.1f} KB)", dry_run)

        manifest["profiles"][name] = {
            "size_bytes": profile_size,
            "size_mb": round(profile_size / 1024 / 1024, 2),
        }
        total_size += profile_size

    # ── 2. Engines ──
    engine_map = {
        "wiki-AIGC-KB": WIKI_DIR,
        "output": OUTPUT_DIR,
    }
    engines_dir = backup_dir / "engines" if not dry_run else None
    for name, src in engine_map.items():
        if not src.exists():
            dry(f"⚠️   {name}: 不存在", dry_run)
            continue
        engine_size = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
        file_count = sum(1 for f in src.rglob("*") if f.is_file())
        if not dry_run:
            dest = engines_dir / name
            shutil.copytree(src, dest)
        dry(f"📚 {name}/ ({file_count} 文件, {engine_size/1024/1024:.1f} MB)", dry_run)
        manifest["engines"][name] = {
            "size_bytes": engine_size,
            "size_mb": round(engine_size / 1024 / 1024, 2),
            "files": file_count,
        }
        total_size += engine_size

    # ── 3. Manifest ──
    manifest["total_size_mb"] = round(total_size / 1024 / 1024, 2)
    if not dry_run:
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Write recovery guide
        recovery_md = f"""# 系统恢复指引 — {timestamp}

## 崩溃类型判断

| 症状 | 原因 | 恢复路径 |
|:-----|:-----|:---------|
| WSL 崩了, E:盘还在 | WSL 系统损坏 | 恢复 profiles 到 ~/.hermes/ |
| E: 盘崩了 | 硬盘故障 | 从外部备份恢复 (推荐) |
| 误删/改错 | 操作失误 | git checkout / 从备份恢复单个文件 |

## 恢复步骤

### 1. 恢复 Hermes Profiles
```bash
mkdir -p ~/.hermes/profiles
"""
        # Build profile list as a separate string
        profile_list = '" "'.join(PROFILES)
        recovery_md += f"""for p in {profile_list}; do
    cp -r {backup_dir}/profiles/$p ~/.hermes/profiles/$p
done
```
"""

        recovery_md += f"""
### 2. 恢复 Engine
```bash
# Wiki
cp -r {backup_dir}/engines/wiki-AIGC-KB /mnt/e/AIGC-KB/

# KMS Engine
cp -r {backup_dir}/engines/output/kms-engine /mnt/e/AIGC-KB/

# Investment Engine (含策略+因子+回测)
cp -r "{backup_dir}/engines/output/investment-engine" /mnt/e/AIGC-KB/输出/
```

### 3. 恢复 API Keys
每个 profile 的 .env 文件在备份中。恢复后检查:
```bash
grep -c "***" ~/.hermes/profiles/ai-investor/.env
# 如果都是 ***, 需要重新从各服务商获取
```

### 4. 验证恢复
```bash
python3 ~/.hermes/profiles/ai-investor/scripts/system_health_check.py
```
"""
        (backup_dir / "recovery.md").write_text(recovery_md, encoding="utf-8")

    # ── 4. Summary ──
    print(f"\n{'─'*60}")
    print(f"  📊 备份摘要")
    print(f"  {'─'*40}")
    for name, info in manifest["profiles"].items():
        print(f"  📁 {name:<20s} {info['size_mb']:.2f} MB")
    for name, info in manifest["engines"].items():
        print(f"  📚 {name:<20s} {info['size_mb']:.1f} MB ({info.get('files','?'):,} 文件)")
    print(f"  {'─'*40}")
    print(f"  📦 总计: {manifest['total_size_mb']:.1f} MB")

    if dry_run:
        print(f"\n  [DRY RUN] 未实际执行备份")
    else:
        print(f"\n  ✅ 备份完成: {backup_dir}")
        print(f"  📋 manifest: {backup_dir/'manifest.json'}")
        print(f"  📖 恢复指引: {backup_dir/'recovery.md'}")

    return 0


def restore(timestamp: str):
    """从备份恢复"""
    backup_dir = BACKUP_ROOT / f"backup-{timestamp}"
    if not backup_dir.exists():
        print(f"❌ 备份不存在: {backup_dir}")
        print(f"   可用备份:")
        for b in sorted(BACKUP_ROOT.glob("backup-*")):
            sz = sum(f.stat().st_size for f in b.rglob("*") if f.is_file()) / 1024 / 1024
            print(f"     {b.name} ({sz:.1f} MB)")
        return 1

    print(f"\n{'='*60}")
    print(f"  🔄 从备份恢复: {backup_dir.name}")
    print(f"{'='*60}\n")

    # Dry-run prompt
    print(f"  此操作将覆盖以下文件:")
    for name in PROFILES:
        src = backup_dir / "profiles" / name
        if src.exists():
            print(f"    ~/.hermes/profiles/{name}/")

    print(f"    /mnt/e/AIGC-KB/ (Wiki + Engines)")
    print()
    resp = input("  确认恢复? (yes/no): ")
    if resp.lower() != "yes":
        print("  ❌ 已取消")
        return 1

    # 恢复 profiles
    for name in PROFILES:
        src = backup_dir / "profiles" / name
        if not src.exists():
            continue
        dest = HERMES_ROOT / name
        print(f"  🔄 恢复 {name}...")
        if dest.exists():
            shutil.move(dest, HERMES_ROOT / f"{name}.bak.{timestamp}")
        shutil.copytree(src, dest)
        print(f"    ✅ {name} 已恢复 (旧配置备份为 {name}.bak.{timestamp})")

    # 恢复 engines
    engines_dir = backup_dir / "engines"
    if engines_dir.exists():
        for sub in engines_dir.iterdir():
            if sub.is_dir():
                if sub.name == "wiki-AIGC-KB":
                    dest = WIKI_DIR
                elif sub.name == "output":
                    dest = OUTPUT_DIR
                else:
                    continue
                print(f"  🔄 恢复 {sub.name}...")
                if dest.exists():
                    shutil.move(dest, dest.parent / f"{dest.name}.bak.{timestamp}")
                shutil.copytree(sub, dest)
                print(f"    ✅ {sub.name} 已恢复")

    print(f"\n  ✅ 恢复完成!")
    print(f"  运行健康检查验证: python3 scripts/system_health_check.py")
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全体系备份工具")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--restore", metavar="时间戳", help="从备份恢复")
    args = parser.parse_args()

    if args.restore:
        return restore(args.restore)
    return backup(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
