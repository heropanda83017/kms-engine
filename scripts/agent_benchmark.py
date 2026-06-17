#!/usr/bin/env python3
"""agent_benchmark.py — Agent 评估体系

系统化的 agent benchmark，量化衡量 agent 的成功率、效率、稳定性。

用法:
  python agent_benchmark.py run              # 运行 benchmark
  python agent_benchmark.py report           # 查看最新报告
  python agent_benchmark.py compare <a> <b>  # 对比两次运行
  python agent_benchmark.py history          # 查看历史趋势
"""

import json, sys, time, os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import run_template, list_templates, _load_sessions


# ── 配置 ──────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".hermes" / "profiles" / "ai-investor" / "config"
BENCHMARK_FILE = CONFIG_DIR / "agent_benchmark_results.json"

# ── 测试用例 ──────────────────────────────────────────

BENCHMARK_TASKS = [
    # 单 agent 基础测试
    {"name": "macro_basic", "template": "macro", "goal": "评估当前A股宏观环境"},
    {"name": "industry_basic", "template": "industry", "goal": "分析半导体行业"},
    {"name": "screening_basic", "template": "screening", "goal": "初筛中际旭创"},
    {"name": "sentiment_basic", "template": "sentiment", "goal": "分析茅台市场情绪"},
    {"name": "risk_basic", "template": "risk", "goal": "风控审核中际旭创"},
    # 对话测试
    {"name": "groupchat_debate", "type": "groupchat",
     "agents": ["bull", "bear", "judge"], "topic": "中际旭创是否值得买入",
     "rounds": 2},
]


# ── 评估运行 ──────────────────────────────────────────

def run_benchmark(tasks: list = None) -> dict:
    """运行 benchmark 测试"""
    if tasks is None:
        tasks = BENCHMARK_TASKS

    results = []
    total = len(tasks)
    success = 0
    total_duration = 0
    total_retries = 0
    total_chars = 0
    reflection_count = 0

    print(f"\n{'='*55}")
    print(f"  📊 Agent Benchmark — {total} 个测试")
    print(f"{'='*55}\n")

    for i, task in enumerate(tasks, 1):
        print(f"  [{i}/{total}] {task['name']}...", end="", flush=True)
        t0 = time.time()

        try:
            if task.get("type") == "groupchat":
                # GroupChat 测试
                from group_chat import GroupChat
                chat = GroupChat(
                    topic=task["topic"],
                    agents=task["agents"],
                    max_rounds=task.get("rounds", 2),
                )
                chat.run(verbose=False)
                duration = time.time() - t0
                result = {
                    "name": task["name"],
                    "status": "success",
                    "duration": round(duration, 2),
                    "messages": len(chat.history),
                    "retries": 0,
                    "chars": sum(len(m.content or "") for m in chat.history),
                }
                success += 1
            else:
                # 单 agent 测试
                session = run_template(
                    task["template"],
                    goal=task["goal"],
                )
                duration = time.time() - t0
                status = session.status if hasattr(session, "status") else "unknown"
                retries = session.retry_count if hasattr(session, "retry_count") else 0
                chars = len(str(getattr(session, "result", "") or ""))
                result = {
                    "name": task["name"],
                    "status": status,
                    "duration": round(duration, 2),
                    "retries": retries,
                    "chars": chars,
                }
                if status == "success":
                    success += 1
                if retries > 0:
                    reflection_count += 1

            total_duration += result["duration"]
            total_retries += result.get("retries", 0)
            total_chars += result.get("chars", 0)
            results.append(result)

            icon = "✅" if result["status"] == "success" else "❌"
            print(f" {icon} ({result['duration']:.1f}s)")

        except Exception as e:
            duration = time.time() - t0
            result = {
                "name": task["name"],
                "status": "failed",
                "duration": round(duration, 2),
                "error": str(e)[:100],
            }
            results.append(result)
            print(f" ❌ {str(e)[:50]}")

    # 汇总
    report = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "success": success,
        "failed": total - success,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "avg_duration": round(total_duration / total, 2) if total > 0 else 0,
        "avg_retries": round(total_retries / total, 2) if total > 0 else 0,
        "total_chars": total_chars,
        "reflection_rate": round(reflection_count / max(total - success, 1) * 100, 1),
        "results": results,
    }

    # 保存
    _save_report(report)

    print(f"\n{'='*55}")
    print(f"  ✅ Benchmark 完成")
    print(f"  成功率: {report['success_rate']}% ({success}/{total})")
    print(f"  平均耗时: {report['avg_duration']}s")
    print(f"  平均重试: {report['avg_retries']}")
    print(f"  反思率: {report['reflection_rate']}%")
    print(f"{'='*55}")

    return report


def _save_report(report: dict):
    """保存 benchmark 报告"""
    BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    reports = []
    if BENCHMARK_FILE.exists():
        try:
            reports = json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    reports.append(report)
    tmp = BENCHMARK_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BENCHMARK_FILE)


def _load_reports() -> list:
    """加载所有 benchmark 报告"""
    if not BENCHMARK_FILE.exists():
        return []
    try:
        return json.loads(BENCHMARK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def show_report(report: dict = None):
    """显示 benchmark 报告"""
    if report is None:
        reports = _load_reports()
        if not reports:
            print("📭 无 benchmark 数据，请先运行 `benchmark run`")
            return
        report = reports[-1]

    print(f"\n{'='*55}")
    print(f"  📊 Benchmark 报告 — {report['timestamp'][:16]}")
    print(f"{'='*55}")
    print(f"  成功率:     {report['success_rate']}% ({report['success']}/{report['total']})")
    print(f"  平均耗时:   {report['avg_duration']}s")
    print(f"  平均重试:   {report['avg_retries']}")
    print(f"  总字符:     {report['total_chars']:,}")
    print(f"  反思率:     {report['reflection_rate']}%")
    print(f"\n  逐项结果:")
    for r in report.get("results", []):
        icon = "✅" if r["status"] == "success" else "❌"
        retries = f" (重试{r['retries']}次)" if r.get("retries", 0) > 0 else ""
        print(f"    {icon} {r['name']}: {r['status']} ({r['duration']:.1f}s){retries}")


def show_history():
    """显示历史趋势"""
    reports = _load_reports()
    if not reports:
        print("📭 无历史数据")
        return

    print(f"\n{'='*55}")
    print(f"  📈 Benchmark 历史趋势 ({len(reports)} 次)")
    print(f"{'='*55}")
    print(f"  {'时间':<20s} {'成功率':>8s} {'耗时':>8s} {'重试':>6s}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*6}")
    for r in reports:
        time_str = r["timestamp"][5:16]
        rate = f"{r['success_rate']}%"
        dur = f"{r['avg_duration']}s"
        ret = f"{r['avg_retries']}"
        print(f"  {time_str:<20s} {rate:>8s} {dur:>8s} {ret:>6s}")


def compare(a_idx: int = -2, b_idx: int = -1):
    """对比两次 benchmark 运行"""
    reports = _load_reports()
    if len(reports) < 2:
        print("❌ 需要至少 2 次 benchmark 才能对比")
        return

    a = reports[a_idx]
    b = reports[b_idx]

    print(f"\n{'='*55}")
    print(f"  📊 Benchmark 对比")
    print(f"{'='*55}")
    print(f"  {'指标':<20s} {'之前':>12s} {'当前':>12s} {'变化':>10s}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*10}")

    metrics = [
        ("成功率", "success_rate", "%", True),
        ("平均耗时", "avg_duration", "s", False),
        ("平均重试", "avg_retries", "", False),
        ("反思率", "reflection_rate", "%", True),
    ]
    for label, key, unit, higher_better in metrics:
        va = a.get(key, 0)
        vb = b.get(key, 0)
        diff = vb - va
        if isinstance(va, float):
            diff_str = f"{diff:+.1f}{unit}"
        else:
            diff_str = f"{diff:+}{unit}"
        arrow = "🟢" if (higher_better and diff > 0) or (not higher_better and diff < 0) else "🔴"
        print(f"  {label:<20s} {va:>10.1f}{unit} {vb:>10.1f}{unit} {arrow} {diff_str:>8s}")


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent 评估体系")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="运行 benchmark")
    sub.add_parser("report", help="查看最新报告")
    sub.add_parser("history", help="查看历史趋势")

    p_compare = sub.add_parser("compare", help="对比两次运行")
    p_compare.add_argument("a", nargs="?", type=int, default=-2, help="索引1")
    p_compare.add_argument("b", nargs="?", type=int, default=-1, help="索引2")

    args = parser.parse_args()

    if args.cmd == "run":
        run_benchmark()
    elif args.cmd == "report":
        show_report()
    elif args.cmd == "history":
        show_history()
    elif args.cmd == "compare":
        compare(args.a, args.b)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
