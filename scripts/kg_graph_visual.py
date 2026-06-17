#!/usr/bin/env python3
"""kg_graph_visual.py — 笔记级实体关系图（d3.js 力导向）
为单篇笔记自动生成 HTML 实体关系图，嵌入笔记底部。
用法见文件底部 main() 函数。
"""
import json, sys, os, subprocess
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, SCRIPTS_DIR

TYPE_COLORS = {"concept":"#4A90D9","person":"#E67E22","company":"#27AE60","factor":"#8E44AD","indicator":"#F39C12","method":"#1ABC9C","tool":"#E74C3C","domain":"#2C3E50"}
REL_COLORS = {"is_a":"#95A5A6","part_of":"#7F8C8D","uses":"#BDC3C7","related_to":"#D5D8DC","influences":"#A9CCE3","contrasts_with":"#F5B7B1"}
ANCHOR_COLORS = {"key_judgment":"#E74C3C","key_data":"#F39C12","comparison":"#9B59B6","causality":"#3498DB","process_step":"#1ABC9C","metaphor":"#E67E22"}
ANCHOR_LABELS = {"key_judgment":"判断","key_data":"数据","comparison":"对比","causality":"因果","process_step":"流程","metaphor":"隐喻"}
D3_PATH = SCRIPTS_DIR / "d3.v7.min.js"

def _load_d3js():
    if D3_PATH.exists():
        return D3_PATH.read_text(encoding="utf-8")
    return ""

def _build_html(title, d3js, graph_json, type_colors_json, anchors):
    """构建自包含 HTML 图（不使用 f-string，避免模板转义问题）"""
    ttl = title[:50]
    anchor_html = ""
    if anchors:
        anchor_html = '<div class="anchors"><strong>\U0001f4a1 认知锚点</strong> '
        for a in anchors:
            atype = a.get("anchor_type", "")
            color = ANCHOR_COLORS.get(atype, "#95A5A6")
            label = ANCHOR_LABELS.get(atype, atype)
            content = a.get("content", "")
            anchor_html += '<span class="anchor-tag" style="background:%s">%s</span> %s<br>' % (color, label, content)
        anchor_html += "</div>"
    return '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>''' + ttl + '''</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f8f9fa}
#graph{width:100%;height:500px}
.node circle{stroke:#fff;stroke-width:2px;cursor:pointer}
.node text{font-size:11px;pointer-events:none}
.link{stroke-opacity:.6;fill:none}
.link-label{font-size:9px;fill:#666}
.legend{position:absolute;bottom:10px;left:10px;font-size:12px}
.legend-item{display:inline-block;margin-right:12px}
.legend-color{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:4px;vertical-align:middle}
.title{padding:8px 12px;font-size:14px;color:#333;background:#fff;border-bottom:1px solid #eee}
.anchors{padding:8px 12px;font-size:12px;color:#555;background:#fff}
.anchor-tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;margin-right:6px;color:#fff}
</style></head><body>
<div class="title">📊 ''' + ttl + '''</div>
<div id="graph"></div>''' + anchor_html + '''<div class="legend" id="legend"></div>
<script>''' + d3js + '''</script>
<script>
var data = ''' + graph_json + ''';
var typeColors = ''' + type_colors_json + ''';
var w=document.getElementById('graph').clientWidth,h=500;
var svg=d3.select('#graph').append('svg').attr('width',w).attr('height',h);
var g=svg.append('g');
svg.call(d3.zoom().scaleExtent([0.3,3]).on('zoom',function(e){g.attr('transform',e.transform)}));
var sim=d3.forceSimulation(data.nodes).force('link',d3.forceLink(data.edges).id(function(d){return d.id}).distance(80)).force('charge',d3.forceManyBody().strength(-200)).force('center',d3.forceCenter(w/2,h/2)).force('collision',d3.forceCollide(30));
var link=g.append('g').selectAll('line').data(data.edges).join('line').attr('class','link').attr('stroke',function(d){return typeColors[d.type]||'#ccc'}).attr('stroke-width',1.5);
var ll=g.append('g').selectAll('text').data(data.edges).join('text').attr('class','link-label').text(function(d){return d.type}).attr('dx',0).attr('dy',-4);
var node=g.append('g').selectAll('circle').data(data.nodes).join('circle').attr('r',12).attr('fill',function(d){return typeColors[d.type]||'#999'}).call(d3.drag().on('start',function(e,d){if(!e.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y}).on('drag',function(e,d){d.fx=e.x;d.fy=e.y}).on('end',function(e,d){if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null}));
node.append('title').text(function(d){return d.id+' ('+d.type+')'});
var label=g.append('g').selectAll('text').data(data.nodes).join('text').text(function(d){return d.label}).attr('dx',15).attr('dy',4).attr('font-size','11px');
sim.on('tick',function(){link.attr('x1',function(d){return d.source.x}).attr('y1',function(d){return d.source.y}).attr('x2',function(d){return d.target.x}).attr('y2',function(d){return d.target.y});
ll.attr('x',function(d){return(d.source.x+d.target.x)/2}).attr('y',function(d){return(d.source.y+d.target.y)/2});
node.attr('cx',function(d){return d.x}).attr('cy',function(d){return d.y});
label.attr('x',function(d){return d.x}).attr('y',function(d){return d.y})});
var tn={"concept":"\u6982\u5ff5","person":"\u4eba\u7269","company":"\u516c\u53f8","factor":"\u56e0\u5b50","indicator":"\u6307\u6807","method":"\u65b9\u6cd5","tool":"\u5de5\u5177","domain":"\u9886\u57df"};
var lh='';for(var t in typeColors){lh+='<span class="legend-item"><span class="legend-color" style="background:'+typeColors[t]+'"></span>'+(tn[t]||t)+'</span>'}
document.getElementById('legend').innerHTML=lh;
</script></body></html>'''

def generate_graph(note_path, output_dir=None, dry_run=False):
    try:
        from kg_store import get_entities_for_note, get_related_entities, get_anchors_for_note
    except ImportError:
        return {"entities":0,"relations":0,"output":None}
    full_path = Path(note_path)
    if not full_path.exists():
        full_path = WIKI_DIR / note_path
        if not full_path.exists():
            return {"entities":0,"relations":0,"output":None}
    rel_path = str(full_path.relative_to(WIKI_DIR)).replace("\\","/")
    entities = get_entities_for_note(rel_path)
    if not entities:
        return {"entities":0,"relations":0,"output":None}
    entity_names = [e["name"] for e in entities if e.get("name")]
    if not entity_names:
        return {"entities":0,"relations":0,"output":None}
    anchors = get_anchors_for_note(rel_path)
    nodes, seen_nodes, edges, seen_edges = [], set(), [], set()
    for e in entities:
        name = e.get("name","")
        if name and name not in seen_nodes:
            nodes.append({"id":name,"type":e.get("type","concept"),"label":name[:20]})
            seen_nodes.add(name)
    for name in entity_names:
        related = get_related_entities(name)
        for edge in related.get("edges",[]):
            src,tgt,rtype = edge.get("source",""),edge.get("target",""),edge.get("type","related_to")
            if src and tgt and src in seen_nodes and tgt in seen_nodes:
                ek = "%s|%s|%s" % (src,tgt,rtype)
                if ek not in seen_edges:
                    edges.append({"source":src,"target":tgt,"type":rtype})
                    seen_edges.add(ek)
    for e in edges:
        if e["source"] not in seen_nodes:
            nodes.append({"id":e["source"],"type":"concept","label":e["source"][:20]})
            seen_nodes.add(e["source"])
        if e["target"] not in seen_nodes:
            nodes.append({"id":e["target"],"type":"concept","label":e["target"][:20]})
            seen_nodes.add(e["target"])
    if dry_run:
        print("  \U0001f50d %s: %d节点/%d边/%d锚点" % (full_path.name, len(nodes), len(edges), len(anchors)))
        return {"entities":len(nodes),"relations":len(edges),"output":None,"anchors":len(anchors)}
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = full_path.parent / "_kg"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = full_path.stem.replace(" ","-")[:50]
    out_path = out_dir / ("%s-graph.html" % stem)
    d3js = _load_d3js()
    graph_json = json.dumps({"nodes":nodes,"edges":edges}, ensure_ascii=False)
    tc_json = json.dumps(TYPE_COLORS, ensure_ascii=False)
    html = _build_html(full_path.stem, d3js, graph_json, tc_json, anchors)
    out_path.write_text(html, encoding="utf-8")
    return {"entities":len(nodes),"relations":len(edges),"output":str(out_path),"anchors":len(anchors)}

def generate_all():
    from kg_store import _get_conn
    c = _get_conn()
    rows = c.execute("SELECT DISTINCT note_path FROM entity_notes ORDER BY note_path").fetchall()
    total = 0
    for r in rows:
        result = generate_graph(str(WIKI_DIR / r["note_path"]))
        if result["output"]:
            total += 1
    print("\u5b8c\u6210: %d \u7bc7" % total)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.all:
        generate_all()
    elif args.target:
        result = generate_graph(args.target, output_dir=args.output, dry_run=args.dry_run)
        if result["output"]:
            print("  \u2705 \u56fe\u5df2\u751f\u6210: %s" % result["output"])
    else:
        parser.print_help()
