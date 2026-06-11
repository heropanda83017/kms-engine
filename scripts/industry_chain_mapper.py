#!/usr/bin/env python3
"""
Industry Chain Mapper — Phase 2: Interactive d3.js HTML
Usage:
  python3 industry_chain_mapper.py /tmp/chain.json --output chart.html
Options:
  --format html      输出交互式HTML（默认）
  --format markdown  输出Markdown报告
"""

import json, sys
from pathlib import Path
from datetime import datetime

# ===== 实时数据（2026-06-04 收盘）=====
ENRICHMENT = {
    "002466": {"name": "天齐锂业", "close": 59.46, "pe": 45.59, "pb": 2.20, "mv": 1018.68, "turnover": 2.92, "trend_15d": -15.26, "flow": "-4.25亿"},
    "002460": {"name": "赣锋锂业", "close": 66.79, "pe": 36.79, "pb": 3.01, "mv": 1400.38, "turnover": 3.47, "trend_15d": -17.49, "flow": "--"},
    "603799": {"name": "华友钴业", "close": 51.30, "pe": 13.23, "pb": 1.96, "mv": 973.02, "turnover": 3.16, "trend_15d": -14.70, "flow": "-6.36亿"},
    "002738": {"name": "中矿资源", "close": 57.80, "pe": 50.21, "pb": 3.36, "mv": 417.02, "turnover": 3.85, "trend_15d": None, "flow": "--"},
    "002756": {"name": "永兴材料", "close": 60.00, "pe": 33.73, "pb": 2.49, "mv": 323.46, "turnover": 3.33, "trend_15d": None, "flow": "--"},
    "300450": {"name": "先导智能", "close": 46.88, "pe": 48.93, "pb": 4.39, "mv": 784.88, "turnover": 3.00, "trend_15d": None, "flow": "--"},
    "688006": {"name": "杭可科技", "close": 33.87, "pe": 53.71, "pb": 3.76, "mv": 204.46, "turnover": 3.76, "trend_15d": None, "flow": "--"},
    "300769": {"name": "德方纳米", "close": 61.82, "pe": None, "pb": 3.32, "mv": 173.21, "turnover": 6.51, "trend_15d": None, "flow": "--"},
    "300073": {"name": "当升科技", "close": 52.60, "pe": 35.85, "pb": 1.93, "mv": 286.30, "turnover": 2.33, "trend_15d": None, "flow": "--"},
    "688005": {"name": "容百科技", "close": 32.36, "pe": None, "pb": 2.98, "mv": 231.29, "turnover": 6.44, "trend_15d": None, "flow": "--"},
    "603659": {"name": "璞泰来", "close": 28.40, "pe": 23.64, "pb": 2.97, "mv": 608.84, "turnover": 2.85, "trend_15d": None, "flow": "--"},
    "835185": {"name": "贝特瑞", "close": None, "pe": None, "pb": None, "mv": None, "turnover": None, "trend_15d": None, "flow": "--"},
    "002709": {"name": "天赐材料", "close": 49.40, "pe": 35.13, "pb": 5.45, "mv": 1007.05, "turnover": 6.04, "trend_15d": None, "flow": "--"},
    "300037": {"name": "新宙邦", "close": 78.30, "pe": 43.79, "pb": 5.55, "mv": 590.29, "turnover": 9.60, "trend_15d": None, "flow": "--"},
    "002812": {"name": "恩捷股份", "close": 64.37, "pe": 167.75, "pb": 2.47, "mv": 632.20, "turnover": 3.41, "trend_15d": None, "flow": "--"},
    "300568": {"name": "星源材质", "close": 15.58, "pe": 1107.38, "pb": 2.15, "mv": 209.66, "turnover": 6.37, "trend_15d": None, "flow": "--"},
    "300750": {"name": "宁德时代", "close": 408.20, "pe": 23.91, "pb": 5.25, "mv": 18885.89, "turnover": 1.01, "trend_15d": -2.79, "flow": "-33.05亿"},
    "002594": {"name": "比亚迪", "close": 93.44, "pe": 30.92, "pb": 3.67, "mv": 8519.11, "turnover": 0.91, "trend_15d": -2.01, "flow": "-8.43亿"},
    "300014": {"name": "亿纬锂能", "close": 59.66, "pe": 28.95, "pb": 2.70, "mv": 1296.59, "turnover": 3.76, "trend_15d": -10.76, "flow": "--"},
    "002074": {"name": "国轩高科", "close": 30.66, "pe": 24.15, "pb": 1.92, "mv": 556.24, "turnover": 1.99, "trend_15d": -16.69, "flow": "--"},
}


def pe_color(pe, pe_percentile=None):
    """Node fill color. If pe_percentile available, use historical percentile.
    Otherwise fallback to absolute PE thresholds (backward compat)."""
    if pe_percentile is not None:
        if pe_percentile < 20.0: return "#22c55e"   # green — 低估区
        if pe_percentile < 50.0: return "#eab308"   # yellow — 合理区
        if pe_percentile < 80.0: return "#f97316"   # orange — 偏高区
        return "#ef4444"                              # red — 高估区
    # Fallback: absolute PE thresholds
    if pe is None: return "#9ca3af"  # gray
    if pe < 15: return "#22c55e"
    if pe < 30: return "#eab308"
    if pe < 60: return "#f97316"
    return "#ef4444"


def pe_label(pe, pe_percentile=None):
    """Text label for PE. If pe_percentile available, attach it."""
    if pe_percentile is not None:
        if pe_percentile < 20.0: return f"PE {pe:.1f} (↓{pe_percentile:.0f}%分位) 🟢"
        if pe_percentile < 50.0: return f"PE {pe:.1f} ({pe_percentile:.0f}%分位) 🟡"
        if pe_percentile < 80.0: return f"PE {pe:.1f} (↑{pe_percentile:.0f}%分位) 🟠"
        return f"PE {pe:.1f} (⚠{pe_percentile:.0f}%分位) 🔴"
    # Fallback
    if pe is None: return "亏损"
    if pe < 15: return f"PE {pe:.1f} 🟢"
    if pe < 30: return f"PE {pe:.1f} 🟡"
    if pe < 60: return f"PE {pe:.1f} 🟠"
    return f"PE {pe:.1f} 🔴"


def border_color(trend_15d):
    """Node border (stroke) color based on 15d momentum.
    Uses blue→purple palette, independent from green→red fill palette."""
    if trend_15d is None: return "#1e293b"  # invisible (same as bg)
    if trend_15d >= 10.0: return "#3b82f6"  # blue — 强动量上行
    if trend_15d >= 3.0:  return "#0ea5e9"  # sky — 温和上涨
    if trend_15d > -3.0:  return "#94a3b8"  # gray — 横盘
    if trend_15d > -10.0: return "#8b5cf6"  # purple — 温和下跌
    return "#9333ea"                          # violet — 强下跌


def build_graph_data(data):
    """Build nodes + edges for d3.js"""
    nodes, edges = [], []
    code_idx = {}

    for seg in data['segments']:
        for co in seg['companies']:
            e = ENRICHMENT.get(co['code'], {})
            idx = len(nodes)
            code_idx[co['code']] = idx
            nodes.append({
                "id": co['code'],
                "name": co['name'],
                "code": co['code'],
                "segment": seg['name'],
                "position": seg.get('type', seg.get('position', 'midstream')),
                "segIdx": [s['name'] for s in data['segments']].index(seg['name']),
                "mv": e.get('mv') or 100,
                "pe": e.get('pe'),
                "pe_percentile": e.get('pe_percentile'),
                "pb": e.get('pb'),
                "close": e.get('close'),
                "turnover": e.get('turnover'),
                "reason": co.get('reason', ''),
                "desc": seg.get('description', ''),
                "trend_15d": e.get('trend_15d'),
                "flow": e.get('flow', '--'),
                "color": pe_color(e.get('pe'), e.get('pe_percentile')),
                "border": border_color(e.get('trend_15d')),
                "label": f"{co['name']}({co['code']})"
            })

    # 上下游边：上游→中游→下游
    order = {'upstream': 0, 'midstream': 1, 'downstream': 2}
    for n in nodes:
        for m in nodes:
            if order.get(m['position'], -1) - order.get(n['position'], -1) == 1:
                edges.append({"source": n['code'], "target": m['code'], "type": "supply"})

    return nodes, edges


def generate_html(data):
    nodes, edges = build_graph_data(data)
    graph_json = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    industry = data['industry']
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 内嵌 d3.js，零网络依赖
    d3_path = Path(__file__).parent / 'd3.v7.min.js'
    if not d3_path.exists():
        print(f"❌ 缺少依赖文件: {d3_path}", file=sys.stderr)
        print("   请从 https://d3js.org/d3.v7.min.js 下载并放到脚本同目录", file=sys.stderr)
        sys.exit(1)
    d3_inline = d3_path.read_text(encoding='utf-8')

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>产业链图谱 — {industry}</title>
<script>D3_INLINE</script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0f172a; color: #e2e8f0; overflow: hidden; height: 100vh; }}

#header {{ position: fixed; top: 0; left: 0; right: 0; z-index: 100;
           display: flex; align-items: center; gap: 16px;
           padding: 12px 24px; background: rgba(15,23,42,0.95); backdrop-filter: blur(8px);
           border-bottom: 1px solid #1e293b; }}
#header h1 {{ font-size: 18px; font-weight: 600; color: #f1f5f9; white-space: nowrap; }}
#header .subtitle {{ font-size: 12px; color: #64748b; margin-left: 8px; }}

#search-box {{ flex: 1; max-width: 300px; padding: 6px 12px; border-radius: 6px;
               border: 1px solid #334155; background: #1e293b; color: #e2e8f0;
               font-size: 13px; outline: none; }}
#search-box:focus {{ border-color: #3b82f6; }}

.btn {{ padding: 6px 16px; border-radius: 6px; border: 1px solid #334155;
        background: #1e293b; color: #e2e8f0; font-size: 13px; cursor: pointer;
        transition: all 0.2s; white-space: nowrap; }}
.btn:hover {{ background: #334155; border-color: #475569; }}
.btn-primary {{ background: #2563eb; border-color: #2563eb; color: white; }}
.btn-primary:hover {{ background: #3b82f6; }}

#graph-container {{ position: fixed; top: 56px; left: 0; right: 380px; bottom: 0; }}
#graph-container svg {{ width: 100%; height: 100%; }}

#side-panel {{ position: fixed; top: 56px; right: 0; width: 380px; bottom: 0;
               background: #1e293b; border-left: 1px solid #334155;
               overflow-y: auto; padding: 20px; display: none; }}
#side-panel.visible {{ display: block; }}

#side-panel .close-btn {{ float: right; cursor: pointer; font-size: 20px;
                          color: #64748b; padding: 4px; line-height: 1; }}
#side-panel .close-btn:hover {{ color: #f1f5f9; }}

#side-panel h2 {{ font-size: 20px; margin-bottom: 4px; }}
#side-panel .code {{ color: #64748b; font-size: 13px; }}

.metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 16px 0; }}
.metric {{ background: #0f172a; border-radius: 8px; padding: 12px; }}
.metric .label {{ font-size: 11px; color: #64748b; text-transform: uppercase; }}
.metric .value {{ font-size: 18px; font-weight: 700; margin-top: 4px; }}
.metric .sub {{ font-size: 11px; color: #64748b; margin-top: 2px; }}

#side-panel .reason {{ background: #0f172a; border-radius: 8px; padding: 12px;
                       margin-top: 12px; font-size: 13px; line-height: 1.6;
                       color: #94a3b8; }}

#legend {{ position: fixed; bottom: 20px; left: 24px; z-index: 50;
           display: flex; gap: 16px; padding: 8px 16px;
           background: rgba(15,23,42,0.9); border-radius: 8px;
           border: 1px solid #1e293b; font-size: 12px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; }}
.legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

.tooltip {{ position: absolute; padding: 8px 12px; background: rgba(15,23,42,0.95);
            border: 1px solid #334155; border-radius: 6px; font-size: 12px;
            pointer-events: none; opacity: 0; transition: opacity 0.15s; }}
.tooltip.visible {{ opacity: 1; }}

text {{ font-size: 11px; fill: #94a3b8; pointer-events: none; }}
.link {{ stroke: #334155; stroke-width: 1.5; stroke-opacity: 0.6; fill: none; }}

@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }}
                     to {{ opacity: 1; transform: translateY(0); }} }}
#graph-container {{ animation: fadeIn 0.5s ease-out; }}

@media print {{
  #header, #legend, #side-panel {{ display: none !important; }}
  #graph-container {{ right: 0 !important; }}
  body {{ background: white; }}
  svg text {{ fill: #333 !important; }}
}}
</style>
</head>
<body>

<div id="header">
  <h1>🔋 {industry} 产业链 <span class="subtitle">{now}</span></h1>
  <input id="search-box" type="text" placeholder="搜索公司名称或代码..." oninput="filterNodes(this.value)">
  <button class="btn" onclick="resetZoom()">重置视图</button>
  <button class="btn btn-primary" onclick="exportPNG()">📷 导出PNG</button>
</div>

<div id="graph-container"><svg id="graph"></svg></div>
<div id="side-panel"></div>

<div id="legend">
  <div class="legend-title" style="font-weight:600;margin-right:8px">PE分位</div>
  <div class="legend-item"><span class="legend-dot" style="background:#22c55e"></span>低估 &lt;20%</div>
  <div class="legend-item"><span class="legend-dot" style="background:#eab308"></span>合理 20-50%</div>
  <div class="legend-item"><span class="legend-dot" style="background:#f97316"></span>偏高 50-80%</div>
  <div class="legend-item"><span class="legend-dot" style="background:#ef4444"></span>高估 &gt;80%</div>
  <div class="legend-item"><span class="legend-dot" style="background:#9ca3af"></span>亏损</div>
  <div class="legend-sep" style="width:1px;height:20px;background:#334155;margin:0 8px"></div>
  <div class="legend-title" style="font-weight:600;margin-right:8px">动量边框</div>
  <div class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span>强上行</div>
  <div class="legend-item"><span class="legend-dot" style="background:#0ea5e9"></span>温和涨</div>
  <div class="legend-item"><span class="legend-dot" style="background:#94a3b8"></span>横盘</div>
  <div class="legend-item"><span class="legend-dot" style="background:#8b5cf6"></span>温和跌</div>
  <div class="legend-item"><span class="legend-dot" style="background:#9333ea"></span>强下跌</div>
  <div class="legend-item" style="color:#64748b;margin-left:4px">节点大小 = 市值</div>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
// CDN fallback
if (typeof d3 === 'undefined') document.write('<div style=padding:40px;text-align:center;font-size:18px;color:#ef4444>⚠️ d3.js 未能加载，请刷新重试</div>');
const GRAPH_DATA = {graph_json};

// d3.js force simulation
const width = document.getElementById('graph-container').clientWidth;
const height = document.getElementById('graph-container').clientHeight;

const svg = d3.select('#graph')
  .attr('width', width).attr('height', height);

const g = svg.append('g');

// Zoom
svg.call(d3.zoom().scaleExtent([0.3, 4]).on('zoom', (e) => {{
  g.attr('transform', e.transform);
}}));

const {{ nodes, edges }} = GRAPH_DATA;

// Position bias by segment
const posOrder = {{ upstream: 0, midstream: 1, downstream: 2 }};
nodes.forEach(n => {{
  const p = posOrder[n.position] || 0;
  n.fx = width * (0.2 + p * 0.3);
  n.fy = null; // let y float
}});

const simulation = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(edges).id(d => d.id).distance(120))
  .force('charge', d3.forceManyBody().strength(-300))
  .force('center', d3.forceCenter(width/2, height/2))
  .force('y', d3.forceY(height/2).strength(0.05))
  .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 5))
  .on('tick', ticked);

// Edges
const link = g.append('g').selectAll('.link')
  .data(edges).join('line')
  .attr('class', 'link')
  .attr('marker-end', 'url(#arrow)');

// Arrowhead def
svg.append('defs').append('marker')
  .attr('id', 'arrow').attr('viewBox', '0 -5 10 10')
  .attr('refX', 20).attr('refY', 0)
  .attr('markerWidth', 6).attr('markerHeight', 6)
  .attr('orient', 'auto')
  .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#475569');

function nodeRadius(d) {{
  const mv = d.mv || 100;
  return 6 + Math.sqrt(mv / 100) * 2.5;
}}

// Nodes
const node = g.append('g').selectAll('.node')
  .data(nodes).join('g')
  .attr('class', 'node')
  .call(d3.drag()
    .on('start', (e, d) => {{
      if (!e.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x; d.fy = d.y;
    }})
    .on('drag', (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on('end', (e, d) => {{
      if (!e.active) simulation.alphaTarget(0);
      // Keep fixed position after drag
    }})
  );

node.append('circle')
  .attr('r', d => nodeRadius(d))
  .attr('fill', d => d.color)
  .attr('stroke', d => d.border || '#1e293b')
  .attr('stroke-width', 3)
  .style('cursor', 'pointer');

node.append('text')
  .attr('dy', d => nodeRadius(d) + 14)
  .attr('text-anchor', 'middle')
  .text(d => d.name.length > 6 ? d.name.slice(0,4)+'..' : d.name);

node.append('text')
  .attr('dy', d => nodeRadius(d) + 28)
  .attr('text-anchor', 'middle')
  .attr('font-size', '9px')
  .attr('fill', '#64748b')
  .text(d => d.code);

// Hover tooltip
const tooltip = d3.select('#tooltip');
node.on('mouseover', (e, d) => {{
    const peStr = d.pe ? `${{d.pe.toFixed(1)}}` : '亏损';
    const mvStr = d.mv ? `${{d.mv.toFixed(0)}}亿` : '--';
    const trendStr = d.trend_15d !== null && d.trend_15d !== undefined ? ` | 15d: ${{d.trend_15d > 0 ? '+' : ''}}${{d.trend_15d.toFixed(1)}}%` : '';
    const pctStr = d.pe_percentile !== undefined && d.pe_percentile !== null ? ` (${{d.pe_percentile.toFixed(0)}}%分位)` : '';
    tooltip
      .html(`<b>${{d.name}}</b> ${{d.code}}<br>${{d.segment}}<br>PE ${{d.pe ? d.pe.toFixed(1) : '--'}}${{pctStr}} | 市值 ${{mvStr}}${{trendStr}}`)
      .classed('visible', true);
  }})
  .on('mousemove', (e) => {{
    tooltip.style('left', (e.offsetX + 15) + 'px')
           .style('top', (e.offsetY - 10) + 'px');
  }})
  .on('mouseout', () => tooltip.classed('visible', false));

// Click → side panel
node.on('click', (e, d) => showPanel(d));

function ticked() {{
  link
    .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
}}

// Side panel
function showPanel(d) {{
  const panel = document.getElementById('side-panel');
  panel.classList.add('visible');
  const peStr = d.pe ? peColorStr(d.pe, d.pe_percentile) : '<span style="color:#9ca3af">亏损</span>';
  const pbStr = d.pb ? d.pb.toFixed(2) : '--';
  const closeStr = d.close ? `${{d.close.toFixed(2)}}` : '--';
  const mvStr = d.mv ? `${{d.mv.toFixed(0)}}亿` : '--';
  const turnStr = d.turnover ? `${{d.turnover.toFixed(1)}}%` : '--';
  const trend = d.trend_15d;
  const trendArrow = trend !== null && trend !== undefined ? (trend > 0 ? '↗' : '↘') : '--';
  const trendPct = trend !== null && trend !== undefined ? `${{Math.abs(trend).toFixed(1)}}%` : '';
  const trendColor = trend !== null && trend !== undefined ? (trend > 0 ? '#22c55e' : '#ef4444') : '#64748b';
  const flowStr = d.flow && d.flow !== '--' ? d.flow : '--';

  panel.innerHTML = `
    <span class="close-btn" onclick="hidePanel()">✕</span>
    <h2>${{d.name}}</h2>
    <div class="code">${{d.code}} · ${{d.segment}}</div>
    <div class="metric-grid">
      <div class="metric"><div class="label">收盘价</div><div class="value">¥${{closeStr}}</div><div class="sub">2026-06-04</div></div>
      <div class="metric"><div class="label">PE(TTM)</div><div class="value">${{peStr}}</div></div>
      <div class="metric"><div class="label">PB</div><div class="value">${{pbStr}}</div><div class="sub">市净率</div></div>
      <div class="metric"><div class="label">总市值</div><div class="value">${{mvStr}}</div></div>
      <div class="metric"><div class="label">15日趋势</div><div class="value" style="font-size:16px"><span style="color:${{trendColor}}">${{trendArrow}} ${{trendPct}}</span></div><div class="sub">近15个交易日</div></div>
      <div class="metric"><div class="label">主力资金</div><div class="value" style="font-size:14px">${{flowStr}}</div><div class="sub">2026-06-04 净流入</div></div>
    </div>
    <div class="reason" style="margin-top:8px"><b>📊 估值分析</b><br>
      PE: ${{d.pe ? d.pe.toFixed(1) : '--'}} ${{d.pe_percentile !== undefined && d.pe_percentile !== null ? `(3年 ${{d.pe_percentile.toFixed(0)}}% 分位)` : ''}}<br>
      估值状态: ${{peValuationStr(d.pe, d.pe_percentile)}}<br>
      动量信号: ${{borderLabel(d.trend_15d)}}
    </div>
    <div class="reason"><b>核心逻辑：</b><br>${{d.reason || '--'}}</div>
    <div style="margin-top:16px">
      <a href="https://stock.quicktiny.cn/quote/${{d.code}}" target="_blank" class="btn" style="display:inline-block;text-decoration:none">查看行情 ›</a>
    </div>
  `;
}}

function peColorStr(pe, pe_percentile) {{
  const hasPct = pe_percentile !== undefined && pe_percentile !== null;
  const pctInfo = hasPct ? ` (${{pe_percentile.toFixed(0)}}%分位)` : '';
  if (hasPct) {{
    if (pe_percentile < 20.0) return `<span style="color:#22c55e">${{pe.toFixed(1)}}${{pctInfo}} (低估)</span>`;
    if (pe_percentile < 50.0) return `<span style="color:#eab308">${{pe.toFixed(1)}}${{pctInfo}} (合理)</span>`;
    if (pe_percentile < 80.0) return `<span style="color:#f97316">${{pe.toFixed(1)}}${{pctInfo}} (偏高)</span>`;
    return `<span style="color:#ef4444">${{pe.toFixed(1)}}${{pctInfo}} (高估)</span>`;
  }}
  if (pe < 15) return `<span style="color:#22c55e">${{pe.toFixed(1)}} (低估15)</span>`;
  if (pe < 30) return `<span style="color:#eab308">${{pe.toFixed(1)}} (合理15-30)</span>`;
  if (pe < 60) return `<span style="color:#f97316">${{pe.toFixed(1)}} (偏高30-60)</span>`;
  return `<span style="color:#ef4444">${{pe.toFixed(1)}} (高估>60)</span>`;
}}

function peValuationStr(pe, pe_percentile) {{
  const hasPct = pe_percentile !== undefined && pe_percentile !== null;
  if (hasPct) {{
    if (pe_percentile < 20) return '<span style="color:#22c55e">🟢 低估区</span>';
    if (pe_percentile < 50) return '<span style="color:#eab308">🟡 合理区</span>';
    if (pe_percentile < 80) return '<span style="color:#f97316">🟠 偏高区</span>';
    return '<span style="color:#ef4444">🔴 高估区</span>';
  }}
  if (pe < 15) return '<span style="color:#22c55e">🟢 低估</span>';
  if (pe < 30) return '<span style="color:#eab308">🟡 合理</span>';
  if (pe < 60) return '<span style="color:#f97316">🟠 偏高</span>';
  return '<span style="color:#ef4444">🔴 高估</span>';
}}

function borderLabel(trend) {{
  if (trend === null || trend === undefined) return '<span style="color:#64748b">-- 无数据</span>';
  if (trend >= 10) return '<span style="color:#3b82f6">🔵 强上行 (+' + trend.toFixed(1) + '%)</span>';
  if (trend >= 3) return '<span style="color:#0ea5e9">🟦 温和上行 (+' + trend.toFixed(1) + '%)</span>';
  if (trend > -3) return '<span style="color:#94a3b8">⬜ 横盘 (' + trend.toFixed(1) + '%)</span>';
  if (trend > -10) return '<span style="color:#8b5cf6">🟪 温和下跌 (' + trend.toFixed(1) + '%)</span>';
  return '<span style="color:#9333ea">🟣 强下跌 (' + trend.toFixed(1) + '%)</span>';
}}
}}

function hidePanel() {{
  document.getElementById('side-panel').classList.remove('visible');
}}

// Search filter
function filterNodes(query) {{
  const q = query.toLowerCase().trim();
  node.style('opacity', d => {{
    if (!q) return 1;
    return d.name.includes(q) || d.code.includes(q) || d.segment.includes(q) ? 1 : 0.15;
  }});
  link.style('opacity', d => {{
    if (!q) return 1;
    return d.source.name.includes(q) || d.target.name.includes(q) ||
           d.source.code.includes(q) || d.target.code.includes(q) ? 1 : 0.05;
  }});
}}

// Reset zoom
function resetZoom() {{
  svg.transition().duration(500).call(d3.zoom().transform, d3.zoomIdentity);
}}

// Export PNG
function exportPNG() {{
  // Temporarily show all hidden nodes
  const canvas = document.createElement('canvas');
  const w = document.getElementById('graph-container').clientWidth;
  const h = document.getElementById('graph-container').clientHeight;
  canvas.width = w * 2; canvas.height = h * 2;
  const ctx = canvas.getContext('2d');
  ctx.scale(2, 2);
  ctx.fillStyle = '#0f172a'; ctx.fillRect(0, 0, w, h);

  // Serialize SVG to XML
  const svgEl = document.querySelector('#graph');
  const svgData = new XMLSerializer().serializeToString(svgEl);
  const img = new Image();
  const blob = new Blob([svgData], {{ type: 'image/svg+xml;charset=utf-8' }});
  const url = URL.createObjectURL(blob);

  img.onload = function() {{
    ctx.drawImage(img, 0, 0, w, h);
    URL.revokeObjectURL(url);
    const link = document.createElement('a');
    link.download = '{{industry}}_产业链_{now.replace(":","-").replace(" ","_")}.png';
    link.href = canvas.toDataURL('image/png');
    link.click();
  }};
  img.src = url;
}}

// Resize handler
window.addEventListener('resize', () => {{
  const w = document.getElementById('graph-container').clientWidth;
  const h = document.getElementById('graph-container').clientHeight;
  svg.attr('width', w).attr('height', h);
}});
</script>
</body>
</html>'''
    html = html.replace('D3_INLINE', d3_inline)
    return html


def generate_markdown(data):
    """Generate Markdown report"""
    industry = data['industry']
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f"# 产业链图谱: {industry} | 实时数据版", ""]
    lines.append(f"> 数据: Wudao MCP | 估值日期: 2026-06-04 收盘")
    lines.append("")
    
    total_mv = sum((ENRICHMENT.get(c['code'], {}).get('mv') or 0)
                   for seg in data['segments']
                   for c in seg['companies'])
    
    lines.append("## 总览")
    lines.append(f"- 覆盖环节: {len(data['segments'])} 个")
    lines.append(f"- 上市公司: {sum(len(s['companies']) for s in data['segments'])} 家")
    lines.append(f"- 合计市值: **{total_mv:.0f}亿** (约{total_mv/10000:.2f}万亿)")
    lines.append("")
    
    # Mermaid
    lines.append("## 产业链结构图")
    lines.append("")
    lines.append("```mermaid")
    lines.append("flowchart TD")
    for idx, seg in enumerate(data['segments']):
        sid = f"S{idx}"
        lines.append(f"    subgraph {sid}[{seg['name']}]")
        for i, co in enumerate(seg['companies']):
            e = ENRICHMENT.get(co['code'], {})
            mv_str = f" {e.get('mv', 0):.0f}亿" if e.get('mv') else ""
            lines.append(f"        {sid}_{i}[\"{co['name']}({co['code']}){mv_str}\"]")
        lines.append("    end")
    pos_sids = {}
    for idx, seg in enumerate(data['segments']):
        pos_sids.setdefault(seg.get('type', seg.get('position', 'midstream')), []).append(f"S{idx}")
    for i, (src_pos, dst_pos) in enumerate([('upstream','midstream'),('midstream','downstream')]):
        for s in pos_sids.get(src_pos, []):
            for d in pos_sids.get(dst_pos, []):
                lines.append(f"    {s} -->|供应| {d}")
    lines.append("```")
    lines.append("")
    
    # Data tables
    lines.append("## 上市公司实时数据")
    lines.append("*2026-06-04 收盘*")
    for seg in data['segments']:
        lines.append(f"\n### {seg['name']}\n")
        lines.append(f"*{seg.get('desc', seg.get('description', ''))}*\n")
        lines.append("| PE/动量 | 代码 | 股价 | PE(TTM) | PB | 市值(亿) | 换手率 |")
        lines.append("|:---:|:----:|:----:|:----:|:---:|:-------:|:----:|")
        for co in seg['companies']:
            e = ENRICHMENT.get(co['code'], {})
            pe = e.get('pe')
            pe_percentile = e.get('pe_percentile')
            pe_str = pe_label(pe, pe_percentile) if pe else "亏损"
            pb_str = f"{e['pb']:.2f}" if e.get('pb') else "-"
            close_str = f"{e['close']:.2f}" if e.get('close') else "--"
            turn_str = f"{e['turnover']:.1f}%" if e.get('turnover') else "--"
            mv_val = e.get('mv')
            mv_str = f"{mv_val:.0f}" if mv_val else "--"
            # Dual signal: fill signal (PE percentile) + border signal (trend)
            if pe_percentile is not None:
                fill_signal = '🟢' if pe_percentile < 20 else '🟡' if pe_percentile < 50 else '🟠' if pe_percentile < 80 else '🔴'
            else:
                fill_signal = '🟢' if pe and pe < 15 else '🟡' if pe and pe < 30 else '🟠' if pe and pe < 60 else '🔴' if pe else '⚪'
            trend = e.get('trend_15d')
            if trend is not None:
                border_signal = '🔵' if trend >= 10 else '🟦' if trend >= 3 else '⬜' if trend > -3 else '🟪' if trend > -10 else '🟣'
            else:
                border_signal = ''
            signal = f"{fill_signal}{border_signal}" if border_signal else fill_signal
            lines.append(f"| {signal} | {co['code']} | {close_str} | {pe_str} | {pb_str} | {mv_str} | {turn_str} |")
    
    total_n = sum(len(s['companies']) for s in data['segments'])
    lines.append(f"\n**合计: {total_n} 家上市公司 | 总市值 {total_mv:.0f}亿**\n")
    lines.append("---\n")
    lines.append(f"*生成: {now} | 数据: Wudao MCP | 风险提示: 仅供研究，不构成投资建议*")
    
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 industry_chain_mapper.py <chain.json> --output <file> [--format html|markdown] [--enrich enrichment.json]")
        sys.exit(1)

    json_path = sys.argv[1]
    data = json.loads(Path(json_path).read_text(encoding='utf-8'))

    # Load external enrichment if provided
    global ENRICHMENT
    if '--enrich' in sys.argv:
        idx = sys.argv.index('--enrich')
        if idx + 1 < len(sys.argv):
            enrich_path = sys.argv[idx + 1]
            external = json.loads(Path(enrich_path).read_text(encoding='utf-8'))
            # Merge: code → data dict (supports both list[dict] and dict formats)
            ENRICHMENT = {}
            if isinstance(external, dict):
                ENRICHMENT.update(external)
            else:
                for item in external:
                    code = item.get('code')
                    if code:
                        ENRICHMENT[code] = item
            print(f"📦 加载外部丰富数据: {len(ENRICHMENT)} 条")

    fmt = 'html'
    if '--format' in sys.argv:
        idx = sys.argv.index('--format')
        if idx + 1 < len(sys.argv):
            fmt = sys.argv[idx + 1]

    if fmt == 'html':
        report = generate_html(data)
    else:
        report = generate_markdown(data)

    out_idx = sys.argv.index('--output') if '--output' in sys.argv else -1
    if out_idx >= 0 and out_idx + 1 < len(sys.argv):
        out_path = Path(sys.argv[out_idx + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding='utf-8')
        print(f"✅ {fmt.upper()}报告已保存: {out_path}")
    else:
        print(report)


if __name__ == '__main__':
    main()
