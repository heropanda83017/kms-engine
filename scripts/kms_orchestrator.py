#!/usr/bin/env python3
"""
KMS Task Orchestrator — 通用编排引擎

借鉴 Agent River SubAgentEngine 的 DAG 拓扑排序 + 并行批次。
声明式定义子任务依赖 → 自动并行执行 → 聚合报告。

用法:
    python3 kms_orchestrator.py health           # 并行执行 6 项健康检查
    python3 kms_orchestrator.py health --dry-run  # 预览任务拓扑
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class TaskDef:
    """声明式任务定义"""
    name: str                           # 任务名称
    func: Callable[..., Any]            # 执行函数
    deps: list[str] = field(default_factory=list)  # 依赖的任务名称列表
    args: tuple = field(default_factory=tuple)      # 函数位置参数
    kwargs: dict = field(default_factory=dict)       # 函数关键字参数


class TaskOrchestrator:
    """通用编排引擎"""

    def __init__(self, max_workers: int = 6):
        self.max_workers = max_workers

    def _topological_sort(self, tasks: dict[str, TaskDef]) -> list[list[str]]:
        """拓扑排序 → 并行批次列表

        Returns:
            [[batch1_task1, batch1_task2], [batch2_task1], ...]
            同一批次的任务可并行执行
        """
        # 计算入度
        in_degree = {name: 0 for name in tasks}
        for name, task in tasks.items():
            for dep in task.deps:
                if dep in tasks:
                    in_degree[name] = in_degree.get(name, 0) + 1

        # Kahn 算法
        batches = []
        queue = [name for name, deg in in_degree.items() if deg == 0]

        while queue:
            batches.append(list(queue))
            next_queue = []
            for name in queue:
                for other_name, other_task in tasks.items():
                    if name in other_task.deps:
                        in_degree[other_name] -= 1
                        if in_degree[other_name] == 0:
                            next_queue.append(other_name)
            queue = next_queue

        # 检查环
        total = sum(len(b) for b in batches)
        if total != len(tasks):
            remaining = set(tasks.keys()) - set(n for b in batches for n in b)
            raise ValueError(f"检测到循环依赖: {remaining}")

        return batches

    def run(self, tasks: list[TaskDef]) -> dict[str, Any]:
        """执行任务列表

        Args:
            tasks: 任务定义列表

        Returns:
            {task_name: result}
        """
        task_map = {t.name: t for t in tasks}
        batches = self._topological_sort(task_map)

        results: dict[str, Any] = {}

        for batch_idx, batch in enumerate(batches):
            print(f"\n  Batch {batch_idx + 1}/{len(batches)} ({len(batch)} 路并行): {', '.join(batch)}")

            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(batch))) as executor:
                future_map = {}
                for name in batch:
                    task = task_map[name]
                    future = executor.submit(task.func, *task.args, **task.kwargs)
                    future_map[future] = name

                for future in as_completed(future_map):
                    name = future_map[future]
                    try:
                        results[name] = future.result()
                        print(f"    ✅ {name}")
                    except Exception as e:
                        results[name] = None
                        print(f"    ❌ {name}: {e}")

        return results

    def visualize(self, tasks: list[TaskDef]) -> str:
        """生成 Mermaid 流程图"""
        lines = ["```mermaid", "graph TD"]
        task_map = {t.name: t for t in tasks}
        for name, task in task_map.items():
            for dep in task.deps:
                if dep in task_map:
                    lines.append(f"  {dep} --> {name}")
        lines.append("```")
        return "\n".join(lines)


# ── 预定义健康检查任务 ─────────────────────────────────────

def _make_health_tasks() -> list[TaskDef]:
    """创建 6 项健康检查任务（无依赖，全并行）"""
    import sys as _sys
    _sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
    from scripts.health_check import (
        find_md_files, build_link_index,
        check_orphan, check_broken_links, check_no_score,
        check_no_fm, check_shell, check_stale
    )

    # 共享数据：文件列表和链接索引
    files = find_md_files()
    link_index = build_link_index(files)

    return [
        TaskDef(name="orphan",       func=check_orphan,       kwargs={"files": files, "link_index": link_index}),
        TaskDef(name="broken-links", func=check_broken_links, kwargs={"files": files}),
        TaskDef(name="no-score",     func=check_no_score,     kwargs={"files": files}),
        TaskDef(name="no-fm",        func=check_no_fm,        kwargs={"files": files}),
        TaskDef(name="shell",        func=check_shell,        kwargs={"files": files}),
        TaskDef(name="stale",        func=check_stale,        kwargs={"files": files}),
    ]


def run_health_parallel() -> dict[str, Any]:
    """并行执行全部 6 项健康检查"""
    import time as _time
    t0 = _time.time()
    tasks = _make_health_tasks()
    orchestrator = TaskOrchestrator()
    results = orchestrator.run(tasks)
    elapsed = _time.time() - t0

    # 聚合报告
    print(f"\n{'='*50}")
    print(f"📊 健康检查报告 (并行, {elapsed:.1f}s)")
    print(f"{'='*50}")
    for name, result in results.items():
        if result is None:
            print(f"  ❌ {name}: 执行失败")
        elif isinstance(result, (list, tuple)):
            count = len(result)
            if count == 0:
                print(f"  ✅ {name}: 0 问题")
            elif count <= 5:
                print(f"  🟡 {name}: {count} 问题")
            else:
                print(f"  🔴 {name}: {count} 问题")
        else:
            print(f"  ℹ️ {name}: {result}")

    return results


def cli():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python3 kms_orchestrator.py <技能名> [--dry-run]")
        print("技能: health")
        return

    skill = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if skill == "health":
        tasks = _make_health_tasks()
        if dry_run:
            print("📋 健康检查任务拓扑（6 项全并行，无依赖）:")
            for t in tasks:
                print(f"  - {t.name}")
            print(f"\n总任务数: {len(tasks)}")
            return

        print("📋 KMS 并行健康检查...")
        t0 = time.time()
        results = run_health_parallel()
        elapsed = time.time() - t0

        # 汇总
        total_issues = sum(
            len(r) for r in results.values()
            if isinstance(r, (list, tuple))
        )
        print(f"\n总计: {total_issues} 问题 | 耗时: {elapsed:.1f}s")
    else:
        print(f"未知技能: {skill}")
        print("可用技能: health")


if __name__ == "__main__":
    cli()
