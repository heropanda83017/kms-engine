#!/usr/bin/env python3
"""
investment_dashboard.py — 全局投资Dashboard (P4-2)

生成自包含 HTML 看板，聚合：
- 市场环境快照 (strategy_current.json)
- 指数行情
- 信号详情
- 策略锁定状态
- 期货信号摘要 (如可用)

用法:
    python3 scripts/investment_dashboard.py                                     # 默认 -> dashboard.html
    python3 scripts/investment_dashboard.py --output /path/to/dashboard.html    # 指定路径
    python3 scripts/investment_dashboard.py --watch                            # 持续监听模式
"""

import json, sys
from datetime import datetime
from pathlib import Path

KMS_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = KMS_ROOT / "scripts"
CONFIG_DIR = KMS_ROOT / "config"
CACHE_DIR = CONFIG_DIR / "cache"
DASHBOARD_DIR = Path("/mnt/e/AIGC-KB/wiki-AIGC-KB/08-investment/01-数据源与工具/dashboard")

sys.path.insert(0, str(SCRIPTS_DIR))


def load_strategy() -> dict:
    """加载策略锁定状态"""
    sf = CONFIG_DIR / "strategy_current.json"
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_latest_cache() -> dict:
    """加载最新市场分类缓存"""
    lf = CACHE_DIR / "market_classification_latest.json"
    if not lf.exists():
        return {}
    try:
        return json.loads(lf.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_futures_status() -> dict:
    """加载期货信号摘要"""
    futures_file = Path("/mnt/e/AIGC-KB/kms-engine/futures_output") / "latest_signals.json"
    if not futures_file.exists():
        return {}
    try:
        return json.loads(futures_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def generate_html(strategy: dict, cache: dict, futures: dict) -> str:
    """生成自包含HTML看板"""
    r = strategy.get("regime", {})
    primary = strategy.get("primary", {})
    secondary = strategy.get("secondary", {})
    track_b = strategy.get("track_b", {})
    updated = strategy.get("updated_at", "从未")
    
    cls_data = cache.get("classification", {})
    cls_regime = cls_data.get("regime", {})
    index_data = cache.get("index_data", {})
    signals = cls_data.get("signals", {})
    
    # 构建指数行情表格行
    index_rows = ""
    for name, d in sorted(index_data.items()):
        if "close" in d:
            pct = d.get("pct_1d", 0)
            cls_pct = "up" if pct > 0 else ("down" if pct < 0 else "")
            pct_60d = d.get("pct_60d", 0)
            cls_60d = "up" if pct_60d > 0 else ("down" if pct_60d < 0 else "")
            index_rows += f"""
            <tr>
                <td>{name}</td>
                <td>{d['close']}</td>
                <td class="{cls_pct}">{pct:+.2f}%</td>
                <td class="{cls_60d}">{pct_60d:+.2f}%</td>
            </tr>"""
    
    # 信号详情行
    signal_rows = ""
    for k, v in signals.items():
        signal_rows += f"<tr><td>{k}</td><td>{v}</td></tr>"
    
    # 期货信号
    futures_html = ""
    if futures:
        signals_f = futures.get("signals", [])
        if signals_f:
            futures_html += "<h2>📈 期货信号摘要</h2><table><tr><th>合约</th><th>方向</th><th>置信度</th></tr>"
            for s in signals_f[:5]:
                dir_cls = "up" if s.get("direction") == "long" else "down"
                futures_html += f"<tr><td>{s.get('contract','?')}</td><td class='{dir_cls}'>{s.get('direction','?')}</td><td>{s.get('confidence',0)}</td></tr>"
            futures_html += "</table>"

    # ── P1-6: 策略 A/B 对比 ──
    # 主策略(S3) vs 次策略(S2/TrackB) 并排展示
    ab_tasks = strategy.get("tasks", [])
    tasks_rows = ""
    for t in ab_tasks:
        status_icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳"}.get(t.get("status", ""), "❓")
        tasks_rows += f"<tr><td>{status_icon}</td><td>{t.get('id','')}</td><td>{t.get('title','')}</td><td>{t.get('status','')}</td><td>{t.get('notes','')}</td></tr>"

    ab_html = f"""
    <h2>⚔️ 策略 A/B 对比</h2>
    <table>
        <tr><th>维度</th><th>策略 A（主）</th><th>策略 B（次/TrackB）</th></tr>
        <tr><td>策略ID</td><td class="up">{primary.get('id','')}</td><td class="up">{secondary.get('id','')}</td></tr>
        <tr><td>策略名称</td><td><b>{primary.get('name','')}</b></td><td><b>{secondary.get('name','')}</b></td></tr>
        <tr><td>条件</td><td>{primary.get('conditions','')}</td><td>{secondary.get('conditions','')}</td></tr>
        <tr><td>分配</td><td>{primary.get('allocation',0)*100:.0f}%</td><td>{secondary.get('allocation',0)*100:.0f}%</td></tr>
    </table>
    <h2>📋 任务清单 (prd.json)</h2>
    <table>
        <tr><th>状态</th><th>ID</th><th>任务</th><th>状态</th><th>备注</th></tr>
        {tasks_rows}
    </table>
    """
    
    # 构建完整HTML
    label = r.get("label", "未设定")
    conf = r.get("confidence", 0)
    conf_pct = f"{conf*100:.0f}%" if isinstance(conf, (int, float)) else "?"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📊 投资Dashboard — {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0d1117; color: #c9d1d9; padding: 20px; }}
.container {{ max-width: 960px; margin: 0 auto; }}
h1 {{ color: #58a6ff; font-size: 1.5em; margin-bottom: 8px; }}
h2 {{ color: #58a6ff; font-size: 1.2em; margin-top: 24px; margin-bottom: 8px;
       border-bottom: 1px solid #30363d; padding-bottom: 6px; }}
.top-meta {{ color: #8b949e; font-size: 0.85em; margin-bottom: 20px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 12px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.status {{ font-size: 1.1em; }}
.up {{ color: #3fb950; }}
.down {{ color: #f85149; }}
.neutral {{ color: #d29922; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
th {{ text-align: left; color: #8b949e; font-weight: 500; font-size: 0.8em; padding: 4px 8px; border-bottom: 1px solid #30363d; }}
td {{ padding: 4px 8px; font-size: 0.9em; border-bottom: 1px solid #21262d; }}
.key {{ color: #8b949e; font-size: 0.85em; }}
.tag {{ display: inline-block; background: #1f6feb22; color: #58a6ff; border: 1px solid #1f6feb44; border-radius: 12px; padding: 2px 10px; font-size: 0.75em; }}
.footer {{ margin-top: 20px; color: #484f58; font-size: 0.75em; text-align: center; }}
</style>
</head>
<body>
<div class="container">
<h1>📊 投资Dashboard</h1>
<div class="top-meta">更新于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

<div class="grid">
    <div class="card">
        <h2>🏷️ 市场环境</h2>
        <div class="status">{label}</div>
        <div>置信度: <strong>{conf_pct}</strong> | 更新: {updated[:19] if len(updated) > 19 else updated}</div>
        <div style="margin-top: 6px;"><span class="key">锁定人:</span> {strategy.get('locked_by', '?')}</div>
    </div>
    <div class="card">
        <h2>🎯 策略配置</h2>
        <div>主策略: <strong>{primary.get('name', '?')}</strong> ({primary.get('allocation', 0)*100:.0f}%)</div>
        <div>辅策略: {secondary.get('name', '?')} ({secondary.get('allocation', 0)*100:.0f}%)</div>
        <div>Track B: {track_b.get('name', '?')} ({track_b.get('allocation', 0)*100:.0f}%)</div>
    </div>
</div>

<div class="card">
    <h2>📈 指数行情</h2>
    <table>
        <tr><th>指数</th><th>收盘</th><th>日涨跌</th><th>60日涨跌</th></tr>
        {index_rows}
    </table>
</div>

<div class="card">
    <h2>📡 信号详情</h2>
    <table>
        <tr><th>信号</th><th>值</th></tr>
        {signal_rows}
    </table>
</div>

{futures_html}

{ab_html}

<div class="card">
    <h2>🛠️ 快速命令</h2>
    <div style="font-family: monospace; font-size: 0.85em; color: #8b949e;">
        python3 scripts/market_daily_pipeline.py<br>
        python3 scripts/session_health.py<br>
        python3 scripts/strategy_lock.py
    </div>
</div>

<div class="footer">
    自动生成 by investment_dashboard.py | {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
</div>
</body>
</html>"""


def main():
    import argparse
    ap = argparse.ArgumentParser(description="全局投资Dashboard生成器")
    ap.add_argument("--output", default=str(DASHBOARD_DIR / "dashboard.html"),
                    help="输出HTML路径")
    ap.add_argument("--watch", action="store_true", help="持续监听模式(每60s刷新)")
    args = ap.parse_args()
    
    strategy = load_strategy()
    cache = load_latest_cache()
    futures = load_futures_status()
    
    html = generate_html(strategy, cache, futures)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard: {output_path}")
    print(f"   大小: {len(html)} 字节")
    
    if args.watch:
        import time
        print("   持续监听中(Ctrl+C退出)...")
        try:
            while True:
                time.sleep(60)
                strategy = load_strategy()
                cache = load_latest_cache()
                futures = load_futures_status()
                html = generate_html(strategy, cache, futures)
                output_path.write_text(html, encoding="utf-8")
                print(f"   🔄 刷新 {datetime.now().strftime('%H:%M:%S')}")
        except KeyboardInterrupt:
            print("\n   监听停止")


if __name__ == "__main__":
    main()
