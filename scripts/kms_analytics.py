#!/usr/bin/env python3
"""
KMS Usage Analytics — 使用模式追踪

记录搜索关键词和命令执行，帮助了解 KMS 使用情况。
数据仅本地存储于 SQLite，不发送到外部。

用法:
    python3 kms_analytics.py report       # 查看使用报告
    python3 kms_analytics.py report --days 7  # 最近 7 天
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta


class UsageTracker:
    """使用追踪器"""

    def __init__(self):
        self._db_path = Path(__file__).resolve().parent.parent / "config" / "analytics" / "kms_usage.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    command TEXT NOT NULL,
                    detail TEXT,
                    duration REAL,
                    result_count INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    result_count INTEGER
                )
            """)
            conn.commit()

    def log_command(self, command: str, detail: str = None, duration: float = None):
        """记录命令执行"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO usage_log (timestamp, command, detail, duration) VALUES (?, ?, ?, ?)",
                [datetime.now().isoformat(), command, detail, duration]
            )
            conn.commit()

    def log_search(self, keyword: str, result_count: int = 0):
        """记录搜索"""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO search_log (timestamp, keyword, result_count) VALUES (?, ?, ?)",
                [datetime.now().isoformat(), keyword, result_count]
            )
            conn.commit()

    def report(self, days: int = 7) -> dict:
        """生成使用报告"""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(str(self._db_path)) as conn:
            # 命令统计
            cmd_rows = conn.execute(
                "SELECT command, COUNT(*) as cnt, ROUND(AVG(duration), 1) as avg_dur "
                "FROM usage_log WHERE timestamp > ? GROUP BY command ORDER BY cnt DESC",
                [since]
            ).fetchall()

            # 搜索关键词统计
            search_rows = conn.execute(
                "SELECT keyword, COUNT(*) as cnt FROM search_log "
                "WHERE timestamp > ? GROUP BY keyword ORDER BY cnt DESC LIMIT 10",
                [since]
            ).fetchall()

            # 总览
            total_cmds = conn.execute(
                "SELECT COUNT(*) FROM usage_log WHERE timestamp > ?", [since]
            ).fetchone()[0]
            total_searches = conn.execute(
                "SELECT COUNT(*) FROM search_log WHERE timestamp > ?", [since]
            ).fetchone()[0]

        return {
            "period_days": days,
            "total_commands": total_cmds,
            "total_searches": total_searches,
            "top_commands": [{"command": r[0], "count": r[1], "avg_duration": r[2]} for r in cmd_rows[:10]],
            "top_keywords": [{"keyword": r[0], "count": r[1]} for r in search_rows],
        }


def report(days: int = 7):
    """打印使用报告"""
    tracker = UsageTracker()
    data = tracker.report(days=days)

    print(f"\n📊 KMS 使用报告 (最近 {data['period_days']} 天)")
    print(f"{'='*50}")
    print(f"总命令数: {data['total_commands']}")
    print(f"总搜索数: {data['total_searches']}")
    print()

    if data["top_commands"]:
        print("🔧 常用命令:")
        for c in data["top_commands"]:
            dur = f" | 平均 {c['avg_duration']}s" if c["avg_duration"] else ""
            print(f"  {c['command']}: {c['count']} 次{dur}")
        print()

    if data["top_keywords"]:
        print("🔍 高频搜索词:")
        for k in data["top_keywords"]:
            print(f"  「{k['keyword']}」: {k['count']} 次")
        print()

    return data


def cli():
    if len(sys.argv) < 2 or sys.argv[1] == "report":
        days = 7
        for arg in sys.argv[2:]:
            if arg.startswith("--days"):
                parts = arg.split("=") if "=" in arg else [arg, ""]
                d_str = parts[1] if len(parts) > 1 else ""
                if not d_str:
                    idx = sys.argv.index(arg)
                    if idx + 1 < len(sys.argv):
                        d_str = sys.argv[idx + 1]
                days = int(d_str) if d_str.isdigit() else 7
        report(days=days)
    else:
        print(f"用法: python3 kms_analytics.py report [--days N]")


if __name__ == "__main__":
    cli()
