#!/usr/bin/env python3
"""
from _path_setup import KMS_ROOT
Investment MCP Server — 将投资体系暴露为 MCP 工具

协议: JSON-RPC 2.0 over stdio (MCP 2024-11-05 / FastMCP)
SDK: mcp 1.27.2 (FastMCP)

工具:
  - invest_status         → 完整系统摘要 (策略+市场+健康+成本)
  - invest_strategy       → 当前策略锁定状态 + 任务清单
  - invest_market         → 市场分类器结果 (5类市况)
  - invest_health         → 体系健康检查摘要 (30项)
  - invest_cost           → FinOps 成本分析
  - invest_recent_audit   → 最近审计/轨迹记录

安装: 在 ~/.hermes/config.yaml profile 下添加:
  mcp_servers:
    invest:
      transport: stdio
      command: python3
      args:
        - /path/to/investment_mcp_server.py
      enabled: true
"""
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── 路径 ──
PROFILE = Path(os.environ.get(
    'HERMES_PROFILE_DIR',
    Path.home() / '.hermes' / 'profiles' / 'ai-investor'
))
SCRIPTS = PROFILE / 'scripts'
DATA = PROFILE / 'data'
KMS_CONFIG = KMS_ROOT / 'config'
STRATEGY_FILE = KMS_CONFIG / 'strategy_current.json'

mcp = FastMCP("investment", instructions="Investment system: strategy, market, health, cost data")


# ── Helper: read JSON ──
def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


# ── Helper: run local script and capture JSON ──
def run_script(script: str, *args: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / script)] + list(args),
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()[:2000]
    except (OSError, subprocess.TimeoutExpired):
        return "(unavailable)"


# ═══════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════

@mcp.tool()
async def invest_status() -> str:
    """返回投资系统完整状态摘要: 策略锁定 + 市况 + 健康 + 成本"""
    strategy = read_json(STRATEGY_FILE)
    regime = strategy.get('regime', {})
    primary = strategy.get('primary', {})
    tasks = strategy.get('tasks', [])
    completed = sum(1 for t in tasks if t.get('status') == 'completed')
    pending = sum(1 for t in tasks if t.get('status') == 'pending')

    lines = [
        f"📊 投资系统状态 ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC)",
        f"",
        f"🎯 市况: {regime.get('label','未设定')} (置信度 {regime.get('confidence','?')})",
        f"📈 主策略: {primary.get('id','?')} {primary.get('name','?')} ({primary.get('allocation',0)*100:.0f}%)",
        f"📋 任务: {completed}完成 / {pending}待办",
    ]

    # Health check
    health_out = run_script('system_health_check.py', '--json', timeout=20)
    try:
        h = json.loads(health_out)
        lines.append(f"🏥 健康: {h.get('passed',0)}/{h.get('total',30)} 通过")
    except (json.JSONDecodeError, ValueError):
        pass

    # Cost
    cost_out = run_script('cost_budget.py', 'status', timeout=10)
    for line in cost_out.splitlines():
        if 'Total' in line:
            lines.append(f"💰 {line.strip()}")
            break

    return '\n'.join(lines)


@mcp.tool()
async def invest_strategy() -> str:
    """返回当前策略锁定状态 + 任务清单进度"""
    strategy = read_json(STRATEGY_FILE)
    regime = strategy.get('regime', {})
    primary = strategy.get('primary', {})
    secondary = strategy.get('secondary', {})
    tasks = strategy.get('tasks', [])
    updated = strategy.get('updated_at', '从未')

    lines = [
        f"📈 策略锁定 (更新: {updated})",
        f"",
        f"🎯 市场: {regime.get('label','?')} 置信度 {regime.get('confidence','?')}",
        f"",
        f"⚔️ 策略 A  (主): {primary.get('id','?')} {primary.get('name','?')} — {primary.get('conditions','?')}",
        f"        分配: {primary.get('allocation',0)*100:.0f}%",
        f"",
        f"⚔️ 策略 B (次): {secondary.get('id','?')} {secondary.get('name','?')} — {secondary.get('conditions','?')}",
        f"        分配: {secondary.get('allocation',0)*100:.0f}%",
        f"",
        f"📋 任务清单:",
    ]
    for t in tasks:
        icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳"}.get(t.get('status',''), '❓')
        lines.append(f"  {icon} {t.get('id','?')}: {t.get('title','?')} — {t.get('notes','')}")

    return '\n'.join(lines)


@mcp.tool()
async def invest_market() -> str:
    """返回市场分类器结果"""
    cache_dir = KMS_CONFIG / 'cache'
    results = []
    for f in sorted(cache_dir.glob('market_classification_*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            regime = data.get('regime', {})
            signals = data.get('signals', {})
            results.append(f"📊 {f.stem.replace('market_classification_','')}")
            results.append(f"  市况: {regime.get('label','?')}")
            results.append(f"  置信度: {regime.get('confidence','?')}")
            for k, v in list(signals.items())[:5]:
                results.append(f"  {k}: {v}")
        except (OSError, json.JSONDecodeError):
            pass

    if not results:
        # Try running market classifier
        out = run_script('python3', str(SCRIPTS / 'cost_budget.py'), 'status', timeout=10)
        results = ["(无可用的市场分类缓存)", "请先运行 market_daily_pipeline"]

    return '\n'.join(results)


@mcp.tool()
async def invest_health() -> str:
    """返回体系健康检查摘要 (30项)"""
    out = run_script('system_health_check.py', '--json', timeout=20)
    try:
        h = json.loads(out)
        return (
            f"🏥 体系健康检查\n"
            f"通过: {h.get('passed',0)}/{h.get('total',30)}\n"
            f"错误: {h.get('errors',0)}\n"
            f"警告: {h.get('warnings',0)}\n"
            f"状态: {'✅ 健康' if h.get('all_ok') else '⚠️ 有异常'}"
        )
    except (json.JSONDecodeError, ValueError):
        return f"(health check unavailable)\n{out[:500]}"


@mcp.tool()
async def invest_cost() -> str:
    """返回 FinOps 成本分析"""
    out = run_script('cost_budget.py', 'finops', '--days', '7', '--optimize', timeout=15)
    return out or "(cost data unavailable)"


@mcp.tool()
async def invest_recent_events(count: int = 5) -> str:
    """返回最近的审计和轨迹事件"""
    lines = ["📋 最近事件\n"]

    # Audit log
    audit_file = DATA / 'audit_log.jsonl'
    if audit_file.exists():
        entries = []
        for line in audit_file.read_text(encoding='utf-8').splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        entries.sort(key=lambda x: x.get('ts', ''), reverse=True)
        lines.append(f"🔍 审计 (最近 {min(count, len(entries))} 条):")
        for e in entries[:count]:
            ts = e.get('ts', '')[:19]
            lines.append(f"  {ts} | {e.get('user','?')} | {e.get('action','?')} → {e.get('verdict','?')} ({e.get('duration_s',0)}s)")

    # Trajectory
    traj_file = DATA / 'trajectory.jsonl'
    if traj_file.exists():
        entries = []
        for line in traj_file.read_text(encoding='utf-8').splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        entries.sort(key=lambda x: x.get('ts', ''), reverse=True)
        lines.append(f"\n📈 轨迹 (最近 {min(count, len(entries))} 条):")
        for e in entries[:count]:
            ts = e.get('ts', '')[:19]
            lines.append(f"  {ts} | {e.get('role','?')} → {e.get('verdict','?')} ({e.get('duration_s',0)}s)")

    return '\n'.join(lines)


if __name__ == '__main__':
    mcp.run(transport='stdio')
