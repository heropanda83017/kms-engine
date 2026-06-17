#!/usr/bin/env python3
"""
checkpoint_watchdog.py — 流水线 Checkpoint 健康监控巡检

用法 (cron no_agent):
  python3 scripts/checkpoint_watchdog.py
  输出空 → 无事可报（静默）
  输出文本 → 有中断/过期的 checkpoint，通知用户

用法 (manual):
  python3 scripts/checkpoint_watchdog.py --verbose
  始终输出完整报告
"""
import json
import os
import sys
from pathlib import Path
from _path_setup import KMS_ROOT

# ── 路径 ──
KMS_ENGINE = KMS_ROOT
sys.path.insert(0, str(KMS_ENGINE))
sys.path.insert(0, str(KMS_ENGINE / "scripts"))

# 导入 checkpoint_utils
try:
    from scripts.checkpoint_utils import get_state as _get_state, list_all as _list_all
except ImportError:
    try:
        sys.path.insert(0, str(KMS_ENGINE.parent))
        from kms_engine.scripts.checkpoint_utils import get_state as _get_state, list_all as _list_all
    except ImportError:
        print("ERROR: checkpoint_utils 未找到", file=sys.stderr)
        sys.exit(2)

# 老化阈值（超过 N 小时未更新的 checkpoint 视为"被遗忘"）
STALE_HOURS = 6
STALE_SECONDS = STALE_HOURS * 3600

import time


def _parse_time(ts_str: str) -> float:
    """解析 '2026-06-06T20:27:59' 或 '2026-06-06 20:27:59' → unixtime"""
    ts_str = ts_str.replace("T", " ")
    try:
        import datetime
        dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except (ValueError, ImportError):
        return 0


def check_all(verbose: bool = False) -> list[str]:
    """扫描所有 checkpoint，返回问题列表。"""
    items = _list_all()
    now = time.time()
    lines = []

    for s in items:
        name = s.get("checkpoint_key") or s.get("pipeline", "?")
        status = s.get("status", "?")
        completed = len(s.get("completed_steps", []))
        total = s.get("total_steps", 0)
        updated = s.get("updated_at", "")

        # 计算老化
        ts = _parse_time(updated)
        age_hours = (now - ts) / 3600 if ts > 0 else 0

        # 1. 中断检测：in_progress 且未完成
        if status == "in_progress" and completed < total:
            lines.append(
                f"🔄 checkpoint '{name}' 中断 — {completed}/{total} 步骤完成"
                f"（最后更新 {age_hours:.0f}h 前）"
            )

        # 2. 老化检测：超过阈值
        if age_hours > STALE_HOURS and completed < total:
            lines.append(
                f"⏰ checkpoint '{name}' 已老化 {age_hours:.0f}h — {completed}/{total} 步骤未完成"
            )

    return lines


def auto_repair(issues: list[str], dry_run: bool = True) -> int:
    """自动修复可恢复的问题

    Args:
        issues: check_all() 返回的问题列表
        dry_run: True=仅预览，False=实际修复

    Returns:
        已修复数量
    """
    import re
    from scripts.checkpoint_utils import get_state, clear, start

    repaired = 0
    for issue in issues:
        # 匹配 "checkpoint 'xxx' 中断 — N/M 步骤完成（最后更新 Xh 前）"
        m = re.search(r"'([^']+)'", issue)
        if not m:
            continue
        name = m.group(1)
        state = get_state(name)
        if not state:
            continue
        if state.get("status") == "in_progress":
            if dry_run:
                print(f"  💡 可修复: checkpoint '{name}' → 重置为 ready（clear）")
            else:
                clear(name)
                print(f"  ✅ 已修复: checkpoint '{name}' → 已清除")
                repaired += 1
    return repaired


def main():
    verbose = "--verbose" in sys.argv
    do_repair = "--repair" in sys.argv
    dry_run = "--dry-run" in sys.argv

    if verbose:
        # 全量报告模式
        items = _list_all()
        if not items:
            print("📭 无活跃 checkpoint — 全系统正常")
            return

        print(f"📋 Checkpoint 健康巡检 ({len(items)} 个):")
        print()
        now = time.time()
        for s in items:
            name = s.get("checkpoint_key") or s.get("pipeline", "?")
            status = s.get("status", "?")
            completed = len(s.get("completed_steps", []))
            total = s.get("total_steps", 0)
            updated = s.get("updated_at", "")
            ts = _parse_time(updated)
            age = (now - ts) / 3600 if ts > 0 else 0

            icon = {"completed": "✅", "in_progress": "🔄", "running": "🔄"}.get(status, "⚪")
            print(f"  {icon} {name:40s} {completed}/{total}  {status:12s}  {age:.0f}h 前更新")

        issues = check_all(verbose=False)
        if issues:
            print()
            print(f"⚠️ {len(issues)} 个问题:")
            for line in issues:
                print(f"   {line}")
    else:
        # 静默模式（cron no_agent）— 有问题才输出
        issues = check_all(verbose=False)
        if issues:
            print("⚠️ Checkpoint 健康巡检发现问题:")
            for line in issues:
                print(f"  {line}")

        # 自动修复
        if do_repair and issues:
            if dry_run:
                print()
                print("🔧 以下问题可自动修复（使用 --repair 执行）:")
                auto_repair(issues, dry_run=True)
            else:
                print()
                print("🔧 自动修复中...")
                fixed = auto_repair(issues, dry_run=False)
                if fixed > 0:
                    print(f"  ✅ {fixed} 个 checkpoint 已重置")
                else:
                    print("  ➖ 无可自动修复的问题")
        elif issues and not do_repair:
            print()
            print("💡 使用 --repair 自动修复 或 --dry-run 预览修复计划")


if __name__ == "__main__":
    main()
