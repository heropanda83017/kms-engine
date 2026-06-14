#!/usr/bin/env python3
"""
workflow_orchestrator.py — 面向 AI agent 的运行时 Workflow Orchestrator v2

不是 CLI 工具，是 agent 在 execute_code 中调用的高层 API。
用法示例（含 fan-out）：

    from workflow_orchestrator import plan, step, fail, complete, status, list_all, cancel

    # P0-1 并行 fan-out (parallel_groups 标注可并行的步骤组)
    plan("5票分析", [
        {"id": "茅台", "name": "贵州茅台"},
        {"id": "宁德", "name": "宁德时代"},
        {"id": "比亚迪", "name": "比亚迪"},
        {"id": "汇总", "name": "汇总对比", "depends_on": ["茅台","宁德","比亚迪"]},
    ], parallel_groups=[["茅台", "宁德", "比亚迪"]])

    # P0-2 失败标记 (agent 收到异常后标记, 然后 retry 或跳过)
    fail("5票分析", "茅台", error="API 超时")
    step("5票分析", "茅台")  # 重试成功

    # P0-3 聚合输出
    complete("5票分析", aggregate=True)  # 自动生成对比表

特点：
- fan-out 由 agent 调度 delegate_task 实现，orchestrator 只做标记和可视化
- 输出是格式化好的 Markdown 字符串，agent 可直接嵌入响应
- 中断恢复：第二次执行自动跳过已完成步骤
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 路径 ──
KMS_ENGINE = Path("/mnt/e/AIGC-KB/kms-engine")
for p in [str(KMS_ENGINE), str(KMS_ENGINE / "scripts")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.checkpoint_utils import (
    start as _cp_start,
    step_done as _cp_step_done,
    mark_complete as _cp_mark_complete,
    get_state as _cp_get_state,
    resume_from as _cp_resume_from,
    clear as _cp_clear,
    list_all as _cp_list,
)

# ── 格式化 ──

def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _progress_bar(completed: int, total: int, width: int = 12) -> str:
    filled = int(width * completed / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {completed}/{total}"


def _step_name(step_id: str, steps_plan: list) -> str:
    for s in steps_plan:
        if isinstance(s, dict) and s.get("id") == step_id:
            return s.get("name", step_id)
    return step_id


def _find_step(step_id: str, steps_plan: list) -> Optional[dict]:
    for s in steps_plan:
        if isinstance(s, dict) and s.get("id") == step_id:
            return s
    return None


def _build_parallel_sections(steps_plan: list,
                              parallel_groups: Optional[list[list[str]]] = None,
                              completed: Optional[set] = None) -> str:
    """构建带并行分组的 step 列表输出。

    parallel_groups 中每组内的步骤显示为并行（用 ⟷ 标记），
    不在组内的步骤按顺序显示。
    """
    if not parallel_groups:
        # 无并行组 — 简单列表
        lines = []
        for s in steps_plan:
            sid = s.get("id", "")
            name = s.get("name", sid)
            if completed is not None:
                icon = "✅" if sid in completed else "⬜"
                lines.append(f"   {icon} {name}")
            else:
                lines.append(f"   ⬜ {name}")
        return "\n".join(lines)

    # 有并行组 — 分组显示
    grouped_ids = set()
    for g in parallel_groups:
        grouped_ids.update(g)

    lines = []
    for s in steps_plan:
        sid = s.get("id", "")
        name = s.get("name", sid)
        icon = "✅" if completed is not None and sid in completed else "⬜"

        # 检查是否在某个并行组中，且是该组的第一个
        in_parallel = any(sid in g for g in parallel_groups)
        is_first_in_group = any(g and g[0] == sid for g in parallel_groups)

        if is_first_in_group:
            # 找到这个组
            group = next(g for g in parallel_groups if g and g[0] == sid)
            group_names = " ⟷ ".join(
                _step_name(i, steps_plan) for i in group
            )
            lines.append(f"   {icon} ⟷ {group_names}")
        elif not in_parallel:
            lines.append(f"   {icon} {name}")

    return "\n".join(lines)


def _build_aggregate_table(steps_plan: list, step_outputs: dict,
                           max_fields: int = 6) -> str:
    """从 step_outputs 生成对比表。

    自动检测所有 output 中的公共字段作为列，
    对非公共字段作补充说明。
    """
    # 收集所有输出
    outputs = {}
    for s in steps_plan:
        sid = s.get("id", "")
        name = s.get("name", sid)
        out = step_outputs.get(sid, {})
        if out:
            outputs[name] = out

    if not outputs:
        return ""

    # 检测公共字段
    all_keys = set()
    for out in outputs.values():
        all_keys.update(out.keys())
    # 排除 status 和 agent 内部字段
    skip_keys = {"status", "error", "retry_count", "started_at", "completed_at"}
    visible_keys = [k for k in all_keys if k not in skip_keys]

    if not visible_keys:
        return ""

    # 最多显示 6 个字段
    visible_keys = visible_keys[:max_fields]

    # 构建表头
    header = f"| 步骤 | {' | '.join(visible_keys)} |"
    sep = f"| --- |{' | '.join(['---'] * len(visible_keys))} |"

    rows = []
    for name, out in outputs.items():
        vals = []
        for k in visible_keys:
            v = out.get(k)
            if v is None:
                vals.append("—")
            elif isinstance(v, float):
                vals.append(f"{v:.2f}")
            elif isinstance(v, (int, str)):
                vals.append(str(v))
            else:
                vals.append(json.dumps(v, ensure_ascii=False)[:30])
        rows.append(f"| {name} | {' | '.join(vals)} |")

    return "\n".join([header, sep] + rows)


# ── 公开 API ──

def plan(workflow_name: str, steps: list,
         metadata: Optional[dict] = None,
         parallel_groups: Optional[list[list[str]]] = None) -> str:
    """创建一个 workflow（幂等）。自动检测中断恢复。

    Args:
        workflow_name: 工作流唯一标识。
        steps: 步骤列表。每项可以是 str 或 dict（支持 id/name/depends_on）。
        metadata: 附加元数据。
        parallel_groups: 并行组。每组内的步骤可同时执行。
                        e.g. [["茅台","宁德"], ["比亚迪"]] 表示前两步并行后串行。

    Returns:
        格式化的状态字符串。
    """
    # 统一 step 格式
    steps_plan = []
    for s in steps:
        if isinstance(s, str):
            steps_plan.append({"id": s, "name": s})
        elif isinstance(s, dict):
            steps_plan.append(s)
        else:
            steps_plan.append({"id": str(s), "name": str(s)})

    total = len(steps_plan)

    # 保存 parallel_groups 到 metadata
    meta = dict(metadata or {})
    if parallel_groups:
        meta["parallel_groups"] = parallel_groups

    # 检查中断恢复
    resume_idx = _cp_resume_from(workflow_name)
    state = _cp_get_state(workflow_name)
    completed = set(state.get("completed_steps", [])) if state else set()

    _cp_start(workflow_name, total, steps_plan=steps_plan, metadata=meta)

    if resume_idx > 0:
        bar = _progress_bar(len(completed), total)
        lines = [
            f"🔄 **{workflow_name}** — 检测到中断恢复",
            f"   {bar}  跳过 {len(completed)} 步",
        ]
        for s in steps_plan:
            sid = s.get("id", "")
            name = s.get("name", sid)
            if sid in completed:
                lines.append(f"   ✅ {name} — 已完成")
            else:
                lines.append(f"   ⏳ {name} — 待执行")
        return "\n".join(lines)

    else:
        bar = _progress_bar(0, total)
        sections = _build_parallel_sections(
            steps_plan, parallel_groups, completed=None
        )
        total_info = f"   {bar}"
        if parallel_groups:
            total_info += f"  |  ⟷ = 并行"
        return (
            f"📋 **{workflow_name}** — 工作流已创建\n"
            f"{total_info}\n"
            f"{sections}"
        )


def step(workflow_name: str, step_id: str,
         output: Optional[dict] = None) -> str:
    """标记一步完成。

    Returns:
        格式化的进度字符串。
    """
    state = _cp_step_done(workflow_name, step_id, output=output)
    total = state.get("total_steps", 0)
    completed = len(state.get("completed_steps", []))
    steps_plan = state.get("steps_plan", [])

    display_name = _step_name(step_id, steps_plan)
    bar = _progress_bar(completed, total)

    return f"✅ **{completed}/{total}** {display_name} 完成\n   {bar}"


def fail(workflow_name: str, step_id: str,
         error: str = "unknown error") -> str:
    """标记一步失败。记录错误信息但不阻塞 workflow。
    agent 可在 fail 后 retry（重新 step）或由后续 complete() 处理。

    Returns:
        格式化的失败状态字符串。
    """
    state = _cp_step_done(workflow_name, step_id, output={
        "status": "failed", "error": error,
    })
    total = state.get("total_steps", 0)
    completed = len(state.get("completed_steps", []))
    steps_plan = state.get("steps_plan", [])

    display_name = _step_name(step_id, steps_plan)
    bar = _progress_bar(completed, total)

    return f"❌ **{step_id}** 失败: {error}\n   {bar}\n   💡 调 `step()` 重试或调 `complete()` 跳过"


def complete(workflow_name: str, aggregate: bool = False) -> str:
    """标记整个 workflow 完成。可选自动生成聚合对比表。

    Args:
        workflow_name: 工作流名称。
        aggregate: 是否从 step_outputs 自动生成聚合对比表。

    Returns:
        格式化的完成状态字符串（含对比表）。
    """
    state = _cp_mark_complete(workflow_name)
    total = state.get("total_steps", 0)
    steps_plan = state.get("steps_plan", [])
    step_outputs = state.get("step_outputs", {})
    bar = _progress_bar(total, total)

    lines = [f"🎉 **{workflow_name}** — 全部 {total} 步完成\n   {bar}"]

    # 聚合输出
    if aggregate and step_outputs:
        table = _build_aggregate_table(steps_plan, step_outputs)
        if table:
            lines.append("\n### 聚合对比\n")
            lines.append(table)

    # 检查失败步骤
    failed = []
    for sid, out in step_outputs.items():
        if isinstance(out, dict) and out.get("status") == "failed":
            name = _step_name(sid, steps_plan)
            err = out.get("error", "unknown")
            failed.append(f"   ❌ {name}: {err}")
    if failed:
        lines.append("\n### ⚠️ 失败步骤\n")
        lines.extend(failed)

    return "\n".join(lines)


def status(workflow_name: str) -> str:
    """查看 workflow 状态（含并行信息）。"""
    state = _cp_get_state(workflow_name)
    if not state:
        return f"📭 Workflow **{workflow_name}** 不存在"

    s = state.get("status", "?")
    completed = len(state.get("completed_steps", []))
    total = state.get("total_steps", 0)
    steps_plan = state.get("steps_plan", [])
    meta = state.get("metadata", {})
    parallel_groups = meta.get("parallel_groups") if isinstance(meta, dict) else None
    bar = _progress_bar(completed, total)

    icon = {"completed": "✅", "in_progress": "🔄", "running": "🔄"}.get(s, "⚪")
    lines = [f"{icon} **{workflow_name}** — {s}  {bar}"]

    if steps_plan:
        done = set(state.get("completed_steps", []))
        sections = _build_parallel_sections(steps_plan, parallel_groups, done)
        if sections:
            lines.append(sections)

    return "\n".join(lines)


def list_all() -> str:
    """列出所有活跃 workflow。"""
    items = _cp_list()
    if not items:
        return "📭 无活跃 workflow"

    lines = [f"📋 **{len(items)} 个活跃 workflow**"]
    for i, s in enumerate(items, 1):
        name = s.get("checkpoint_key") or s.get("pipeline", "?")
        status_s = s.get("status", "?")
        completed = len(s.get("completed_steps", []))
        total = s.get("total_steps", 0)
        bar = _progress_bar(completed, total)
        icon = {"completed": "✅", "in_progress": "🔄"}.get(status_s, "⚪")
        lines.append(f"{i}. {icon} **{name}**  {bar}")

    return "\n".join(lines)


def cancel(workflow_name: str) -> str:
    """取消（删除）一个 workflow。"""
    _cp_clear(workflow_name)
    return f"🗑️ **{workflow_name}** 已取消"


# ── CLI (备选, 主要用于测试) ──

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Workflow Orchestrator CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan")
    p.add_argument("name")
    p.add_argument("steps", nargs="+")
    p.add_argument("--parallel", nargs="*", action="append")

    p2 = sub.add_parser("step")
    p2.add_argument("name")
    p2.add_argument("step_id")

    p3 = sub.add_parser("fail")
    p3.add_argument("name")
    p3.add_argument("step_id")
    p3.add_argument("--error", default="unknown error")

    sub.add_parser("list")
    p4 = sub.add_parser("status")
    p4.add_argument("name")

    p5 = sub.add_parser("complete")
    p5.add_argument("name")
    p5.add_argument("--aggregate", action="store_true")

    args = parser.parse_args()
    if args.cmd == "plan":
        pgs = None
        if args.parallel:
            pgs = [list(g) for g in args.parallel if g]
        print(plan(args.name, args.steps, parallel_groups=pgs))
    elif args.cmd == "step":
        print(step(args.name, args.step_id))
    elif args.cmd == "fail":
        print(fail(args.name, args.step_id, error=args.error))
    elif args.cmd == "status":
        print(status(args.name))
    elif args.cmd == "list":
        print(list_all())
    elif args.cmd == "complete":
        print(complete(args.name, aggregate=args.aggregate))
