#!/usr/bin/env python3
"""agent_sandbox.py — Agent 沙盒环境

借鉴 Anthropic Managed Agents 的沙盒解耦思想。
每个 agent 在隔离的临时目录中执行，执行完后自动清理。

用法:
  from agent_sandbox import SandboxManager

  async with SandboxManager() as sm:
      sandbox = sm.create("session_001")
      # 在 sandbox.work_dir 中执行 agent
      # 自动清理
"""

import os, sys, shutil, uuid, logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

# ── 配置 ──────────────────────────────────────────────
SANDBOX_ROOT = Path("/tmp") / "agent_sandboxes"
MAX_AGE_HOURS = 24


@dataclass
class Sandbox:
    """Agent 沙盒环境"""
    session_id: str
    work_dir: Path
    env: dict = field(default_factory=dict)
    created_at: str = ""
    cleaned: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.env:
            self.env = {**os.environ, "SANDBOX_ID": self.session_id}


class SandboxManager:
    """沙盒管理器"""

    _sandboxes: dict[str, Sandbox] = {}

    @classmethod
    def create(cls, session_id: str = "") -> Sandbox:
        """创建沙盒"""
        sid = session_id or str(uuid.uuid4())[:12]
        work_dir = SANDBOX_ROOT / sid
        work_dir.mkdir(parents=True, exist_ok=True)

        sandbox = Sandbox(
            session_id=sid,
            work_dir=work_dir,
        )
        cls._sandboxes[sid] = sandbox
        return sandbox

    @classmethod
    def get(cls, session_id: str) -> Optional[Sandbox]:
        """获取沙盒"""
        return cls._sandboxes.get(session_id)

    @classmethod
    def cleanup(cls, session_id: str):
        """清理指定沙盒"""
        sandbox = cls._sandboxes.pop(session_id, None)
        if sandbox and not sandbox.cleaned:
            try:
                if sandbox.work_dir.exists():
                    shutil.rmtree(sandbox.work_dir)
                sandbox.cleaned = True
            except Exception as e:
                logging.warning(f"沙盒清理失败 {session_id}: {e}")

    @classmethod
    def cleanup_all(cls):
        """清理所有沙盒"""
        for sid in list(cls._sandboxes.keys()):
            cls.cleanup(sid)

    @classmethod
    def cleanup_expired(cls, max_age_hours: int = MAX_AGE_HOURS) -> int:
        """清理过期沙盒，返回清理数量"""
        now = datetime.now()
        expired = []
        for sid, sandbox in cls._sandboxes.items():
            if sandbox.cleaned:
                expired.append(sid)
                continue
            try:
                age = now - datetime.fromisoformat(sandbox.created_at)
                if age > timedelta(hours=max_age_hours):
                    expired.append(sid)
            except Exception:
                expired.append(sid)
        for sid in expired:
            cls.cleanup(sid)
        return len(expired)

    @classmethod
    def cleanup_stale_dirs(cls) -> int:
        """清理磁盘上残留的沙盒目录（非内存管理）"""
        if not SANDBOX_ROOT.exists():
            return 0
        count = 0
        now = datetime.now()
        for d in SANDBOX_ROOT.iterdir():
            if d.is_dir():
                try:
                    mtime = datetime.fromtimestamp(d.stat().st_mtime)
                    if now - mtime > timedelta(hours=MAX_AGE_HOURS):
                        shutil.rmtree(d)
                        count += 1
                except Exception:
                    pass
        return count

    @classmethod
    def stats(cls) -> dict:
        """沙盒统计"""
        return {
            "active": len(cls._sandboxes),
            "root": str(SANDBOX_ROOT),
            "max_age_hours": MAX_AGE_HOURS,
        }


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent 沙盒管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("create", help="创建沙盒")
    sub.add_parser("stats", help="沙盒统计")
    sub.add_parser("cleanup", help="清理所有沙盒")
    sub.add_parser("cleanup-stale", help="清理残留沙盒目录")

    args = parser.parse_args()

    if args.cmd == "create":
        s = SandboxManager.create()
        print(f"✅ 沙盒已创建: {s.session_id}")
        print(f"   工作目录: {s.work_dir}")

    elif args.cmd == "stats":
        s = SandboxManager.stats()
        print(f"📊 沙盒统计:")
        print(f"   活跃: {s['active']}")
        print(f"   根目录: {s['root']}")
        print(f"   过期阈值: {s['max_age_hours']}小时")

    elif args.cmd == "cleanup":
        SandboxManager.cleanup_all()
        print("✅ 所有沙盒已清理")

    elif args.cmd == "cleanup-stale":
        count = SandboxManager.cleanup_stale_dirs()
        print(f"✅ 清理了 {count} 个残留沙盒目录")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
