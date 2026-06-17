#!/usr/bin/env python3
"""agent_template.py — Agent 模板定义 + Session 管理

借鉴 Anthropic Managed Agents 的「Agent 模板 vs Session 实例」解耦思想。

用法:
  from agent_template import register_template, run_template, list_templates, get_template

  # 注册模板
  register_template(
      name="analyst",
      system_prompt="你是一个专业的A股分析师...",
      toolsets=["web", "wudao"],
      description="A股股票分析师",
  )

  # 运行模板
  session = run_template("analyst", goal="分析中际旭创", context="2026Q2财报")
  print(session.status, session.result)
"""

import json, os, sys, uuid, logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── 模板存储路径 ──────────────────────────────────────
CONFIG_DIR = Path.home() / ".hermes" / "profiles" / "ai-investor" / "config"
TEMPLATES_FILE = CONFIG_DIR / "agent_templates.json"
SESSIONS_FILE = CONFIG_DIR / "agent_sessions.json"

# ── 数据类 ────────────────────────────────────────────

@dataclass
class AgentTemplate:
    """Agent 模板 — 定义 agent 的静态配置"""
    name: str
    system_prompt: str
    toolsets: list
    model: str = ""
    description: str = ""
    max_retries: int = 3
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class Session:
    """Session 实例 — agent 模板的一次运行"""
    id: str = ""
    template_name: str = ""
    goal: str = ""
    context: str = ""
    status: str = "pending"  # pending/running/success/failed
    result: any = None
    error: str = ""
    created_at: str = ""
    retry_count: int = 0
    history: list = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


# ── 模板存储 ──────────────────────────────────────────

def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_templates() -> dict:
    """从 JSON 文件加载所有模板"""
    _ensure_dir()
    if not TEMPLATES_FILE.exists():
        return {}
    try:
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logging.warning("agent_templates.json 损坏，返回空模板集")
        return {}


def _save_templates(templates: dict):
    """原子写入模板文件"""
    _ensure_dir()
    tmp = TEMPLATES_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(templates, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(TEMPLATES_FILE)


def _load_sessions() -> list:
    """从 JSON 文件加载所有 session 记录"""
    _ensure_dir()
    if not SESSIONS_FILE.exists():
        return []
    try:
        return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_session_record(session: Session):
    """追加一条 session 记录"""
    sessions = _load_sessions()
    sessions.append(asdict(session))
    tmp = SESSIONS_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(SESSIONS_FILE)


# ── 公开 API ──────────────────────────────────────────

def register_template(name: str, system_prompt: str, toolsets: list,
                      model: str = "", description: str = "",
                      max_retries: int = 3) -> AgentTemplate:
    """注册一个 agent 模板（幂等，同名覆盖）"""
    template = AgentTemplate(
        name=name,
        system_prompt=system_prompt,
        toolsets=toolsets,
        model=model,
        description=description,
        max_retries=max_retries,
    )
    templates = _load_templates()
    templates[name] = asdict(template)
    _save_templates(templates)
    return template


def get_template(name: str) -> Optional[AgentTemplate]:
    """获取模板，不存在返回 None"""
    templates = _load_templates()
    data = templates.get(name)
    if not data:
        return None
    return AgentTemplate(**data)


def list_templates() -> list:
    """列出所有已注册模板"""
    templates = _load_templates()
    return [
        {"name": t["name"], "description": t.get("description", ""),
         "toolsets": t.get("toolsets", []), "model": t.get("model", "")}
        for t in templates.values()
    ]


def delete_template(name: str) -> bool:
    """删除模板"""
    templates = _load_templates()
    if name not in templates:
        return False
    del templates[name]
    _save_templates(templates)
    return True


# ── 动态组队 ──────────────────────────────────────────

DYNAMIC_PREFIX = "_dynamic_"
DYNAMIC_TTL_HOURS = 24


def create_dynamic_template(name: str, system_prompt: str,
                            toolsets: list = None, model: str = "",
                            description: str = "") -> AgentTemplate:
    """动态创建 agent 模板（研究主题专用），自动加 _dynamic_ 前缀防冲突"""
    safe_name = f"{DYNAMIC_PREFIX}{name}" if not name.startswith(DYNAMIC_PREFIX) else name
    template = register_template(
        name=safe_name,
        system_prompt=system_prompt,
        toolsets=toolsets or ["web"],
        model=model,
        description=description,
    )
    # 注册到能力注册表
    try:
        from agent_protocol import CapabilityRegistry, AgentCapability
        CapabilityRegistry.register(safe_name, AgentCapability(
            template_name=safe_name,
            description=description,
            toolsets=toolsets or ["web"],
        ))
    except ImportError:
        pass
    return template


def cleanup_expired_dynamics() -> int:
    """清理过期的动态模板，返回删除数量"""
    templates = _load_templates()
    to_delete = []
    now = datetime.now()
    for name, t in templates.items():
        if name.startswith(DYNAMIC_PREFIX):
            try:
                created = datetime.fromisoformat(t.get("created_at", ""))
                age = now - created
                if age > timedelta(hours=DYNAMIC_TTL_HOURS):
                    to_delete.append(name)
            except Exception:
                to_delete.append(name)
    for name in to_delete:
        del templates[name]
        try:
            from agent_protocol import CapabilityRegistry
            CapabilityRegistry._capabilities.pop(name, None)
        except ImportError:
            pass
    if to_delete:
        _save_templates(templates)
    return len(to_delete)


def run_template(name: str, goal: str, context: str = "",
                 toolsets_override: list = None) -> Session:
    """运行一个 agent 模板，返回 Session

    参数:
        name: 模板名称
        goal: 任务目标
        context: 额外上下文
        toolsets_override: 覆盖模板的 toolsets（可选）

    返回:
        Session 对象（status 为 success 或 failed）
    """
    template = get_template(name)
    if not template:
        available = [t["name"] for t in list_templates()]
        raise ValueError(
            f"模板 '{name}' 未注册。可用模板: {available}"
        )

    # 构建完整 context
    full_context = f"{template.system_prompt}\n\n{context}" if context else template.system_prompt
    toolsets = toolsets_override or template.toolsets

    # 创建 session
    session = Session(
        template_name=name,
        goal=goal,
        context=full_context[:500],  # 只存前500字
        status="running",
    )

    try:
        # 调用 delegate_retry_wrapper
        from delegate_retry_wrapper import delegate_with_retry

        result = delegate_with_retry(
            task={"goal": goal},
            context=full_context,
            toolsets=toolsets,
        )
        session.status = "success"
        session.result = str(result)[:1000] if result else ""
    except Exception as e:
        session.status = "failed"
        session.error = str(e)[:500]
        session.retry_count = getattr(e, "last_attempt", 0)

    # 记录 session
    _save_session_record(session)
    return session


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent 模板管理")
    sub = parser.add_subparsers(dest="cmd")

    # register
    p_reg = sub.add_parser("register", help="注册模板")
    p_reg.add_argument("--name", required=True)
    p_reg.add_argument("--prompt", required=True, help="系统提示词")
    p_reg.add_argument("--toolsets", nargs="+", default=[])
    p_reg.add_argument("--model", default="")
    p_reg.add_argument("--desc", default="")

    # list
    sub.add_parser("list", help="列出模板")

    # run
    p_run = sub.add_parser("run", help="运行模板")
    p_run.add_argument("name")
    p_run.add_argument("--goal", required=True)
    p_run.add_argument("--context", default="")

    # delete
    p_del = sub.add_parser("delete", help="删除模板")
    p_del.add_argument("name")

    # sessions
    sub.add_parser("sessions", help="查看 session 历史")

    args = parser.parse_args()

    if args.cmd == "register":
        t = register_template(args.name, args.prompt, args.toolsets,
                              args.model, args.desc)
        print(f"✅ 模板 '{t.name}' 已注册 (toolsets={t.toolsets})")

    elif args.cmd == "list":
        templates = list_templates()
        if not templates:
            print("📭 无已注册模板")
        else:
            print(f"📋 已注册模板 ({len(templates)}):")
            for t in templates:
                tools = ", ".join(t["toolsets"]) if t["toolsets"] else "(默认)"
                model = t["model"] or "(默认)"
                print(f"  [{t['name']}] {t['description']}")
                print(f"     toolsets: {tools} | model: {model}")

    elif args.cmd == "run":
        session = run_template(args.name, args.goal, args.context)
        print(f"  Session: {session.id[:8]}...")
        print(f"  Status: {session.status}")
        if session.status == "success":
            print(f"  Result: {str(session.result)[:200]}")
        else:
            print(f"  Error: {session.error}")

    elif args.cmd == "delete":
        ok = delete_template(args.name)
        print(f"{'✅ 已删除' if ok else '❌ 模板不存在'}: {args.name}")

    elif args.cmd == "sessions":
        sessions = _load_sessions()
        print(f"📋 Session 历史 ({len(sessions)}):")
        for s in sessions[-10:]:
            status_icon = "✅" if s["status"] == "success" else "❌"
            print(f"  {status_icon} [{s['template_name']}] {s['goal'][:40]}...")
            print(f"     {s['status']} | retry={s['retry_count']} | {s.get('created_at','')[:16]}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
