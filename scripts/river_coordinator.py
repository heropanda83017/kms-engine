#!/usr/bin/env python3
"""river_coordinator.py — Agent 河流编排器

将 agent_river.py 的 12 个硬编码 agent 函数重构为 AgentTemplate 编排。

用法:
  python river_coordinator.py run 000725 --name 京东方A    # 运行完整河流
  python river_coordinator.py list                          # 列出河流agent
  python river_coordinator.py status                        # 查看session历史
"""

import json, sys, os, uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import run_template, list_templates, get_template
from _path_setup import WIKI_DIR

# ── Agent 依赖链 ──────────────────────────────────────
# key 依赖 value 的输出
AGENT_DEPENDENCIES = {
    "industry":       ["macro"],
    "screening":      ["macro", "industry"],
    "ck_factor":      ["screening"],
    "deep":           ["screening", "ck_factor"],
    "debate":         ["screening", "deep"],
    "cross_validate": ["screening"],
    "sentiment":      ["macro"],
    "model_panel":    ["screening", "deep"],
    "risk":           ["screening", "deep", "sentiment"],
}

# 执行顺序（拓扑排序：依赖在前）
RIVER_AGENTS = [
    "macro",          # 宏观环境（无依赖）
    "industry",       # 行业扫描
    "screening",      # 标的初筛
    "ck_factor",      # CK因子
    "deep",           # 深度研究
    "debate",         # 多空辩论
    "cross_validate", # 交叉验证
    "sentiment",      # 情绪分析
    "model_panel",    # 模型辩论
    "risk",           # 风控审核
]

# ── 报告路径 ──────────────────────────────────────────
STUDY_DIR = WIKI_DIR / "08-investment" / "个股研究"


def build_context(code: str, name: str, sessions: dict) -> str:
    """构建 agent context（传入股票代码 + 已有 session 结果）"""
    ctx = f"股票代码: {code}\n股票名称: {name or code}\n"
    if sessions:
        ctx += "\n## 已完成的 agent 分析\n\n"
        for agent_name, session in sessions.items():
            if session.status == "success":
                result_preview = str(session.result)[:200] if session.result else "(无结果)"
                ctx += f"### {agent_name}\n{result_preview}\n\n"
            elif session.status == "failed":
                ctx += f"### {agent_name}\n❌ 失败: {session.error}\n\n"
    return ctx


def merge_report(code: str, name: str, sessions: dict) -> str:
    """合并所有 session 为最终报告"""
    lines = [
        f"# 个股研究 | {name or code} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"> Agent 河流 · {len(sessions)}/{len(RIVER_AGENTS)} agent 完成",
        f"",
    ]
    for agent_name in RIVER_AGENTS:
        session = sessions.get(agent_name)
        if not session:
            lines.append(f"---\n## ⏭️ {agent_name} — 未执行（依赖失败）\n")
            continue
        if session.status == "success":
            lines.append(f"---\n## ✅ {agent_name}\n")
            lines.append(str(session.result) if session.result else "(无结果)")
        else:
            lines.append(f"---\n## ❌ {agent_name} — 失败\n")
            lines.append(f"错误: {session.error}\n")
        lines.append("")
    return "\n".join(lines)


def save_report(code: str, name: str, report_md: str) -> str:
    """保存报告到个股研究目录"""
    STUDY_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{code}-{name or 'unknown'}.md"
    filepath = STUDY_DIR / filename
    
    # 追加模式（保留历史）
    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        report_md = existing + "\n\n---\n\n" + report_md
    
    filepath.write_text(report_md, encoding="utf-8")
    return str(filepath)


def run_river(code: str, name: str = "", parallel: bool = False) -> dict:
    """运行完整 Agent 河流

    返回: {
        "code": str,
        "name": str,
        "sessions": {agent_name: Session},
        "failed": [agent_name, ...],
        "skipped": [agent_name, ...],
        "report_path": str,
    }
    """
    print(f"\n{'='*55}")
    print(f"  🌊 Agent 河流 — {name or code}")
    print(f"  {len(RIVER_AGENTS)} 个 agent · {'并行' if parallel else '串行'}")
    print(f"{'='*55}\n")

    sessions = {}
    failed = set()
    skipped = []

    for i, agent_name in enumerate(RIVER_AGENTS, 1):
        # 检查依赖链
        deps = AGENT_DEPENDENCIES.get(agent_name, [])
        missing_deps = [d for d in deps if d in failed]
        if missing_deps:
            print(f"  [{i}/{len(RIVER_AGENTS)}] ⏭️  {agent_name} — 跳过（依赖失败: {missing_deps}）")
            skipped.append(agent_name)
            failed.add(agent_name)
            continue

        print(f"  [{i}/{len(RIVER_AGENTS)}] 🚀 {agent_name}...", end="", flush=True)

        context = build_context(code, name, sessions)
        try:
            session = run_template(agent_name, goal=f"分析{name or code}", context=context)
            sessions[agent_name] = session
            if session.status == "success":
                print(f" ✅")
            else:
                print(f" ❌ {session.error[:60]}")
                failed.add(agent_name)
        except Exception as e:
            print(f" ❌ {e}")
            failed.add(agent_name)

    # 合并 + 保存
    report = merge_report(code, name, sessions)
    report_path = save_report(code, name, report)

    print(f"\n{'='*55}")
    print(f"  ✅ Agent 河流完成")
    print(f"  成功: {len(sessions) - len(failed)}/{len(RIVER_AGENTS)}")
    if failed:
        print(f"  失败: {len(failed)}")
    if skipped:
        print(f"  跳过: {len(skipped)}")
    print(f"  报告: {report_path}")
    print(f"{'='*55}")

    return {
        "code": code,
        "name": name,
        "sessions": sessions,
        "failed": list(failed),
        "skipped": skipped,
        "report_path": report_path,
    }


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent 河流编排器")
    sub = parser.add_subparsers(dest="cmd")

    # run
    p_run = sub.add_parser("run", help="运行完整 Agent 河流")
    p_run.add_argument("code", help="股票代码")
    p_run.add_argument("--name", default="", help="股票名称")
    p_run.add_argument("--parallel", action="store_true", help="并行模式")

    # list
    sub.add_parser("list", help="列出河流 agent")

    # status
    sub.add_parser("status", help="查看 session 历史")

    args = parser.parse_args()

    if args.cmd == "run":
        run_river(args.code, args.name, args.parallel)

    elif args.cmd == "list":
        templates = list_templates()
        print(f"🌊 Agent 河流 ({len(RIVER_AGENTS)} agent):")
        for i, name in enumerate(RIVER_AGENTS, 1):
            t = next((t for t in templates if t["name"] == name), None)
            if t:
                deps = AGENT_DEPENDENCIES.get(name, [])
                dep_str = f" ← {', '.join(deps)}" if deps else " (无依赖)"
                print(f"  [{i:2d}] {name:15s} {t['description'][:50]}{dep_str}")
            else:
                print(f"  [{i:2d}] {name:15s} ⚠️ 未注册")

    elif args.cmd == "status":
        from agent_template import _load_sessions
        sessions = _load_sessions()
        river_sessions = [s for s in sessions if s.get("template_name") in RIVER_AGENTS]
        print(f"📋 河流 Session 历史 ({len(river_sessions)}):")
        for s in river_sessions[-15:]:
            icon = "✅" if s["status"] == "success" else "❌"
            print(f"  {icon} [{s['template_name']}] {s['goal'][:40]}... | {s['status']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
