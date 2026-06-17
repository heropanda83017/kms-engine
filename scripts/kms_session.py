#!/usr/bin/env python3
"""
KMS Session Memory — 跨会话上下文

记录最近搜索、笔记创建、健康检查结果。
每次 kms 命令自动更新，status 命令展示上下文。

数据文件: config/session/kms_session.json
"""

import json
from pathlib import Path
from datetime import datetime


_SESSION_DIR = Path(__file__).resolve().parent.parent / "config" / "session"
_SESSION_PATH = _SESSION_DIR / "kms_session.json"


def _ensure_dir():
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    if _SESSION_PATH.exists():
        try:
            return json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "last_searches": [],
        "recent_notes": [],
        "last_health": None,
        "command_count": 0,
        "search_count": 0,
        "last_updated": None,
    }


def _save(data: dict):
    _ensure_dir()
    data["last_updated"] = datetime.now().isoformat()[:19]
    _SESSION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_search(keyword: str):
    """记录搜索"""
    data = _load()
    data["search_count"] += 1
    # 去重 + 保留最近 5 条
    if keyword in data["last_searches"]:
        data["last_searches"].remove(keyword)
    data["last_searches"].insert(0, keyword)
    data["last_searches"] = data["last_searches"][:5]
    _save(data)


def record_command():
    """记录命令执行"""
    data = _load()
    data["command_count"] += 1
    _save(data)


def record_note(note_name: str):
    """记录笔记创建/修改"""
    data = _load()
    if note_name in data["recent_notes"]:
        data["recent_notes"].remove(note_name)
    data["recent_notes"].insert(0, note_name)
    data["recent_notes"] = data["recent_notes"][:5]
    _save(data)


def record_health(checks: int, issues: int):
    """记录健康检查结果"""
    data = _load()
    data["last_health"] = {"checks": checks, "issues": issues, "date": datetime.now().isoformat()[:10]}
    _save(data)


def get_context() -> str:
    """获取 session 上下文摘要（用于 status 展示）"""
    data = _load()
    parts = ["📋 会话上下文"]

    if data["last_searches"]:
        parts.append(f"  最近搜索: {' → '.join(data['last_searches'][:3])}")
    if data["recent_notes"]:
        parts.append(f"  最近笔记: {', '.join(data['recent_notes'][:3])}")
    if data["last_health"]:
        h = data["last_health"]
        parts.append(f"  上次健康检查: {h['issues']} 问题 ({h['checks']} 项, {h['date']})")
    if data["command_count"]:
        parts.append(f"  总命令数: {data['command_count']} | 搜索: {data['search_count']}")

    # 用户画像
    portrait = load_portrait()
    if portrait:
        interests = portrait.get("interests", [])
        if interests:
            parts.append(f"  🧑 画像: {' · '.join(interests[:4])}")

    parts.append(f"  更新: {data.get('last_updated', '从未')}")
    return "\n".join(parts)


def load_portrait() -> dict:
    """加载用户画像 — 从 wiki 胡盼画像.md 读取结构化信息"""
    wiki_path = Path(__file__).resolve().parent.parent.parent / "wiki-AIGC-KB" / "00-系统" / "胡盼画像.md"
    if not wiki_path.exists():
        return {}

    content = wiki_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return {}

    # 提取 YAML frontmatter
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}

    import re
    fm = content[3:end_idx].strip()

    # 解析兴趣领域
    interests = []
    in_progress = False
    for line in content.split("\n"):
        if "| **AI工程化**" in line:
            interests.append("AI工程化")
        elif "| **多因子量化**" in line:
            interests.append("多因子量化")
        elif "| **知识管理**" in line:
            interests.append("知识管理")
        elif "| **A股投资**" in line:
            interests.append("A股投资")
        elif "| **Agent架构**" in line:
            interests.append("Agent架构")
        elif "| **前沿扫描**" in line:
            interests.append("前沿扫描")

    return {
        "interests": interests,
        "has_portrait": True,
    }


def cli():
    """CLI 入口"""
    print(get_context())


if __name__ == "__main__":
    cli()
