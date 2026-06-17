#!/usr/bin/env python3
"""agent_dashboard.py — Mission Control 看板

借鉴 Sharbel 的 Max HQ 面板。
基于 MessageBus 链路追踪 + Session 历史 + Benchmark 数据，
生成自包含 HTML Dashboard。

用法:
  python agent_dashboard.py                  # 生成 Dashboard
  python agent_dashboard.py --open           # 生成 + 打开浏览器
  python agent_dashboard.py --output /path   # 指定输出路径
"""

import json, sys, os
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import _load_sessions, list_templates
from agent_protocol import MessageBus


# ── 数据采集 ──────────────────────────────────────────

def collect_data() -> dict:
    """收集所有 Dashboard 数据"""
    sessions = _load_sessions()
    templates = list_templates()
    chains = MessageBus._trace_chains
    messages = MessageBus._messages

    # 1. Agent 统计
    agent_stats = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0, "retries": 0})
    for s in sessions:
        name = s.get("template_name", "unknown")
        agent_stats[name]["total"] += 1
        if s.get("status") == "success":
            agent_stats[name]["success"] += 1
        elif s.get("status") == "failed":
            agent_stats[name]["failed"] += 1
        agent_stats[name]["retries"] += s.get("retry_count", 0)

    # 2. 链路追踪统计
    active_chains = 0
    blocked_chains = 0
    completed_chains = 0
    for trace_id, chain in chains.items():
        statuses = [c.get("status", "") for c in chain]
        if "failed" in statuses:
            blocked_chains += 1
        elif all(s == "success" for s in statuses if s):
            completed_chains += 1
        else:
            active_chains += 1

    # 3. 消息统计
    msg_by_type = Counter(m.message_type for m in messages)
    msg_by_hour = Counter()
    for m in messages:
        try:
            h = datetime.fromisoformat(m.timestamp).strftime("%H:00")
            msg_by_hour[h] += 1
        except Exception:
            pass

    # 4. 模板列表
    template_list = [{"name": t["name"], "desc": t["description"]} for t in templates]

    # 5. 最近活动
    recent = sessions[-20:] if len(sessions) > 20 else sessions
    recent_activity = []
    for s in reversed(recent):
        recent_activity.append({
            "time": s.get("created_at", "")[11:19],
            "template": s.get("template_name", ""),
            "goal": s.get("goal", "")[:40],
            "status": s.get("status", ""),
            "retries": s.get("retry_count", 0),
        })

    return {
        "agent_stats": dict(agent_stats),
        "chains": {
            "active": active_chains,
            "blocked": blocked_chains,
            "completed": completed_chains,
            "total": len(chains),
        },
        "messages": {
            "total": len(messages),
            "by_type": dict(msg_by_type),
            "by_hour": dict(sorted(msg_by_hour.items())),
        },
        "templates": template_list,
        "recent_activity": recent_activity,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── HTML 生成 ─────────────────────────────────────────

def generate_html(data: dict) -> str:
    """生成 Dashboard HTML"""
    stats = data["agent_stats"]
    chains = data["chains"]
    msgs = data["messages"]
    templates = data["templates"]
    recent = data["recent_activity"]

    # 计算总览
    total_runs = sum(s["total"] for s in stats.values())
    total_success = sum(s["success"] for s in stats.values())
    total_failed = sum(s["failed"] for s in stats.values())
    success_rate = round(total_success / total_runs * 100, 1) if total_runs > 0 else 0

    # Agent 表格行
    agent_rows = ""
    for name, s in sorted(stats.items(), key=lambda x: -x[1]["total"]):
        rate = round(s["success"] / s["total"] * 100, 1) if s["total"] > 0 else 0
        bar = "█" * min(int(rate / 10), 10)
        agent_rows += f"""<tr>
            <td>{name}</td>
            <td>{s['total']}</td>
            <td>{s['success']}</td>
            <td>{s['failed']}</td>
            <td style="color:{'#27ae60' if rate > 70 else '#e67e22' if rate > 40 else '#e74c3c'}">{rate}% {bar}</td>
            <td>{s['retries']}</td>
        </tr>"""

    # 最近活动行
    activity_rows = ""
    for a in recent:
        icon = "✅" if a["status"] == "success" else "❌" if a["status"] == "failed" else "⏳"
        retry_tag = f" 🔄{a['retries']}" if a["retries"] > 0 else ""
        activity_rows += f"""<tr>
            <td>{a['time']}</td>
            <td>{a['template']}</td>
            <td>{a['goal'][:40]}</td>
            <td>{icon} {a['status']}{retry_tag}</td>
        </tr>"""

    # 消息按小时分布（Chart.js 数据）
    hours = list(msgs.get("by_hour", {}).keys())
    hour_counts = list(msgs.get("by_hour", {}).values())

    # 消息类型分布
    type_labels = json.dumps(list(msgs.get("by_type", {}).keys()), ensure_ascii=False)
    type_counts = json.dumps(list(msgs.get("by_type", {}).values()))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Mission Control — Agent Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}
h1{{font-size:24px;margin-bottom:20px;color:#fff}}
h2{{font-size:18px;margin:20px 0 10px;color:#a0a0c0}}
.card{{background:#16213e;border-radius:12px;padding:20px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-bottom:20px}}
.stat-card{{background:#0f3460;border-radius:10px;padding:15px;text-align:center}}
.stat-card .num{{font-size:32px;font-weight:bold;color:#e94560}}
.stat-card .label{{font-size:13px;color:#a0a0c0;margin-top:5px}}
.stat-card.green .num{{color:#27ae60}}
.stat-card.orange .num{{color:#e67e22}}
.stat-card.blue .num{{color:#3498db}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 10px;border-bottom:2px solid #0f3460;color:#a0a0c0;font-weight:600}}
td{{padding:6px 10px;border-bottom:1px solid #0f3460}}
tr:hover{{background:#0f3460}}
.chart-container{{height:200px;margin:10px 0}}
.footer{{text-align:center;color:#666;font-size:12px;margin-top:30px}}
</style></head><body>
<h1>🎛️ Mission Control</h1>
<p style="color:#888;margin-bottom:20px">Agent Dashboard — {data['generated_at']}</p>

<div class="grid">
    <div class="stat-card green"><div class="num">{total_runs}</div><div class="label">总执行次数</div></div>
    <div class="stat-card green"><div class="num">{success_rate}%</div><div class="label">成功率</div></div>
    <div class="stat-card orange"><div class="num">{total_failed}</div><div class="label">失败次数</div></div>
    <div class="stat-card blue"><div class="num">{chains['active']}</div><div class="label">运行中链路</div></div>
    <div class="stat-card"><div class="num">{chains['blocked']}</div><div class="label">阻塞链路</div></div>
    <div class="stat-card green"><div class="num">{chains['completed']}</div><div class="label">已完成链路</div></div>
    <div class="stat-card blue"><div class="num">{msgs['total']}</div><div class="label">总消息数</div></div>
    <div class="stat-card blue"><div class="num">{len(templates)}</div><div class="label">Agent 模板</div></div>
</div>

<div class="card">
    <h2>📊 消息分布</h2>
    <div class="chart-container"><canvas id="msgChart"></canvas></div>
</div>

<div class="card">
    <h2>📋 Agent 执行统计</h2>
    <table>
        <tr><th>Agent</th><th>总次数</th><th>成功</th><th>失败</th><th>成功率</th><th>重试</th></tr>
        {agent_rows}
    </table>
</div>

<div class="card">
    <h2>🕐 最近活动</h2>
    <table>
        <tr><th>时间</th><th>Agent</th><th>目标</th><th>状态</th></tr>
        {activity_rows}
    </table>
</div>

<div class="footer">Generated by KMS Engine · Data from MessageBus + Session History</div>

<script>
new Chart(document.getElementById('msgChart'), {{
    type: 'bar',
    data: {{
        labels: {json.dumps(hours, ensure_ascii=False)},
        datasets: [{{
            label: '消息数',
            data: {json.dumps(hour_counts)},
            backgroundColor: '#3498db',
            borderColor: '#2980b9',
            borderWidth: 1
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#a0a0c0' }} }},
            y: {{ ticks: {{ color: '#a0a0c0' }}, beginAtZero: true }}
        }}
    }}
}});
</script>
</body></html>"""


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mission Control Dashboard")
    parser.add_argument("--output", default="", help="输出路径")
    parser.add_argument("--open", action="store_true", help="生成后打开浏览器")
    args = parser.parse_args()

    data = collect_data()
    html = generate_html(data)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path("/tmp") / "mission_control.html"

    out_path.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard 已生成: {out_path}")
    print(f"   总执行: {sum(s['total'] for s in data['agent_stats'].values())} 次")
    print(f"   链路: {data['chains']['total']} 条")
    print(f"   消息: {data['messages']['total']} 条")

    if args.open:
        import subprocess
        subprocess.run(["cmd.exe", "/c", "start", "", str(out_path)],
                       capture_output=True)


if __name__ == "__main__":
    main()
