#!/usr/bin/env python3
"""task_graph.py — DAG 任务图编排引擎

借鉴 Anthropic Coordinator 的 DAG 调度理念。
支持：拓扑排序、并行执行、条件路由、超时控制、Mermaid 可视化。

用法:
  from task_graph import TaskGraph

  dag = TaskGraph()
  dag.add_node("macro")
  dag.add_node("industry", depends_on=["macro"])
  dag.add_node("sentiment", depends_on=["macro"])
  dag.run(code="000725")
  dag.visualize()  # → Mermaid 流程图
"""

import json, sys, uuid, time, logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable, Optional
from collections import defaultdict, deque

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import run_template, list_templates


@dataclass
class TaskNode:
    """DAG 中的一个节点"""
    name: str
    depends_on: list = None
    toolsets: list = None
    condition: Callable = None
    parallel_group: str = ""
    timeout: int = 300
    description: str = ""

    def __post_init__(self):
        if self.depends_on is None:
            self.depends_on = []


class TaskGraph:
    """DAG 任务图"""

    def __init__(self):
        self.nodes: dict[str, TaskNode] = {}
        self.results: dict[str, any] = {}

    def add_node(self, name: str, depends_on: list = None,
                 toolsets: list = None, condition: Callable = None,
                 parallel_group: str = "", timeout: int = 300,
                 description: str = ""):
        """添加节点"""
        self.nodes[name] = TaskNode(
            name=name, depends_on=depends_on or [],
            toolsets=toolsets, condition=condition,
            parallel_group=parallel_group, timeout=timeout,
            description=description,
        )

    def add_edge(self, from_name: str, to_name: str):
        """添加依赖边"""
        if from_name not in self.nodes:
            self.nodes[from_name] = TaskNode(name=from_name)
        if to_name not in self.nodes:
            self.nodes[to_name] = TaskNode(name=to_name)
        if from_name not in self.nodes[to_name].depends_on:
            self.nodes[to_name].depends_on.append(from_name)

    def validate(self) -> bool:
        """验证 DAG（无环检查）"""
        visited = set()
        rec_stack = set()

        def dfs(node_name):
            visited.add(node_name)
            rec_stack.add(node_name)
            node = self.nodes.get(node_name)
            if node:
                for dep in node.depends_on:
                    if dep not in visited:
                        if dfs(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            rec_stack.discard(node_name)
            return False

        for name in self.nodes:
            if name not in visited:
                if dfs(name):
                    raise ValueError(f"DAG 检测到环！节点: {name}")
        return True

    def _topological_sort(self) -> list:
        """拓扑排序"""
        in_degree = defaultdict(int)
        for name, node in self.nodes.items():
            if name not in in_degree:
                in_degree[name] = 0
            for dep in node.depends_on:
                in_degree[name] += 1

        queue = deque([n for n in self.nodes if in_degree[n] == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for name, n in self.nodes.items():
                if node in n.depends_on:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        if len(result) != len(self.nodes):
            raise ValueError("DAG 有环或存在孤立节点")

        return result

    def _parallel_batches(self, topo_order: list) -> list:
        """将拓扑排序结果分组为并行批次"""
        batches = []
        remaining = set(topo_order)
        executed = set()

        while remaining:
            batch = []
            for name in list(remaining):
                node = self.nodes[name]
                # 所有依赖都已执行
                if all(dep in executed for dep in node.depends_on):
                    batch.append(name)
            if not batch:
                raise ValueError("无法继续调度：存在未满足的依赖")
            for name in batch:
                remaining.remove(name)
                executed.add(name)
            batches.append(batch)

        return batches

    def _session_to_dict(self, session) -> dict:
        """将 Session 对象转为 dict（供条件函数使用）"""
        if session is None:
            return {"status": "failed", "result": None, "error": "未执行"}
        if isinstance(session, dict):
            return session
        return {
            "status": getattr(session, "status", "unknown"),
            "result": getattr(session, "result", None),
            "error": getattr(session, "error", ""),
            "retry_count": getattr(session, "retry_count", 0),
        }

    def _run_node(self, node: TaskNode, code: str, name: str,
                  context: str, results: dict) -> dict:
        """执行单个节点"""
        # 检查条件
        if node.condition:
            dep_results = {}
            for d in node.depends_on:
                dep_results[d] = self._session_to_dict(results.get(d))
            try:
                if not node.condition(dep_results):
                    return {"status": "skipped", "reason": "条件不满足"}
            except Exception as e:
                logging.warning(f"条件函数异常: {e}，视为不满足")
                return {"status": "skipped", "reason": f"条件异常: {e}"}

        # 执行 agent
        try:
            session = run_template(
                node.name,
                goal=f"分析{name or code}",
                context=context,
                toolsets_override=node.toolsets,
            )
            return self._session_to_dict(session)
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def run(self, code: str = "", name: str = "",
            context: str = "", verbose: bool = True) -> dict:
        """执行 DAG

        返回: {node_name: {"status": str, "result": any, ...}}
        """
        self.validate()
        topo_order = self._topological_sort()
        batches = self._parallel_batches(topo_order)
        self.results = {}

        total = len(topo_order)
        completed = 0

        if verbose:
            print(f"\n{'='*55}")
            print(f"  📋 DAG 任务图 — {len(batches)} 批 / {total} 节点")
            print(f"{'='*55}\n")

        for batch_idx, batch in enumerate(batches, 1):
            if verbose:
                names = ", ".join(batch)
                print(f"  📦 批 {batch_idx}: [{names}]")

            for node_name in batch:
                node = self.nodes[node_name]
                completed += 1
                if verbose:
                    print(f"    [{completed}/{total}] 🚀 {node_name}...", end="", flush=True)

                result = self._run_node(node, code, name, context, self.results)
                self.results[node_name] = result

                if verbose:
                    status = result.get("status", "unknown")
                    if status == "success":
                        print(f" ✅")
                    elif status == "skipped":
                        print(f" ⏭️  {result.get('reason', '')}")
                    else:
                        print(f" ❌ {result.get('error', '')[:50]}")

        if verbose:
            success = sum(1 for r in self.results.values() if r.get("status") == "success")
            skipped = sum(1 for r in self.results.values() if r.get("status") == "skipped")
            failed = sum(1 for r in self.results.values() if r.get("status") == "failed")
            print(f"\n{'='*55}")
            print(f"  ✅ DAG 完成: {success} 成功 / {skipped} 跳过 / {failed} 失败")
            print(f"{'='*55}")

        return self.results

    def visualize(self) -> str:
        """生成 Mermaid 流程图"""
        lines = ["```mermaid", "graph TD"]
        for name, node in self.nodes.items():
            for dep in node.depends_on:
                lines.append(f"    {dep} --> {name}")
        lines.append("```")
        return "\n".join(lines)

    def summary(self) -> dict:
        """返回 DAG 摘要"""
        return {
            "node_count": len(self.nodes),
            "nodes": [
                {"name": n.name, "depends_on": n.depends_on,
                 "has_condition": n.condition is not None,
                 "parallel_group": n.parallel_group}
                for n in self.nodes.values()
            ],
        }


# ── 标准河流 DAG ─────────────────────────────────────

def create_river_dag() -> TaskGraph:
    """创建标准 Agent 河流 DAG"""
    dag = TaskGraph()

    # 第一层：无依赖
    dag.add_node("macro", parallel_group="a",
                 description="宏观环境评估")

    # 第二层：依赖 macro，可并行
    dag.add_node("industry", depends_on=["macro"], parallel_group="b",
                 description="行业扫描")
    dag.add_node("sentiment", depends_on=["macro"], parallel_group="b",
                 description="情绪分析")

    # 第三层：依赖 industry+sentiment
    dag.add_node("screening", depends_on=["industry", "sentiment"],
                 description="标的初筛")

    # 第四层：依赖 screening，可并行
    dag.add_node("ck_factor", depends_on=["screening"], parallel_group="c",
                 description="CK Chokepoint 因子")
    dag.add_node("cross_validate", depends_on=["screening"], parallel_group="c",
                 description="交叉验证")

    # 第五层：条件路由 — 评分>40才进 deep
    dag.add_node("deep", depends_on=["screening", "ck_factor"],
                 condition=lambda r: (
                     r.get("screening", {}).get("result") or {}).get("score", 0) > 40
                     if isinstance(r.get("screening", {}).get("result"), dict)
                     else True,
                 description="深度研究")

    # 第六层：依赖 deep
    dag.add_node("debate", depends_on=["screening", "deep"],
                 description="多空辩论")
    dag.add_node("model_panel", depends_on=["screening", "deep"],
                 description="模型辩论面板")

    # 第七层：最终风控
    dag.add_node("risk", depends_on=["screening", "deep", "sentiment"],
                 description="风控审核")

    return dag


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="DAG 任务图编排引擎")
    sub = parser.add_subparsers(dest="cmd")

    # run
    p_run = sub.add_parser("run", help="运行 DAG")
    p_run.add_argument("code", help="股票代码")
    p_run.add_argument("--name", default="", help="股票名称")
    p_run.add_argument("--dag", default="river", help="DAG 名称 (默认 river)")

    # visualize
    sub.add_parser("visualize", help="生成 Mermaid 流程图")

    # validate
    sub.add_parser("validate", help="验证 DAG 无环")

    args = parser.parse_args()

    if args.cmd == "run":
        dag = create_river_dag()
        dag.run(code=args.code, name=args.name)

    elif args.cmd == "visualize":
        dag = create_river_dag()
        print(dag.visualize())

    elif args.cmd == "validate":
        dag = create_river_dag()
        try:
            dag.validate()
            print("✅ DAG 验证通过（无环）")
            s = dag.summary()
            print(f"   节点数: {s['node_count']}")
            for n in s["nodes"]:
                deps = f" ← {', '.join(n['depends_on'])}" if n["depends_on"] else " (无依赖)"
                cond = " [条件]" if n["has_condition"] else ""
                grp = f" (组:{n['parallel_group']})" if n["parallel_group"] else ""
                print(f"   {n['name']}{deps}{cond}{grp}")
        except ValueError as e:
            print(f"❌ {e}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
