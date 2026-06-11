#!/usr/bin/env python3
"""
three_layer.py — Generate 3-tier skill index (L1 Always / L2 Resolver / L3 Dormant).

Inspired by GBrain's Always / Resolve / Dormant architecture:
  - L1 (Always-loaded): Injected into every session via SOUL.md. Core identity.
  - L2 (Resolver-routed): Loaded on-demand by keyword/trigger matching.
  - L3 (Dormant): skills-rare/ — cold storage, explicit load only.

Usage:
  python3 three_layer.py                   # Print stats
  python3 three_layer.py --update-index    # Regenerate skill_index.json with layer field
  python3 three_layer.py --resolve "查个股"  # Suggest L2 skills from query
  python3 three_layer.py --validate        # Check all L1 skills exist and are reachable
"""

import json, sys, os, re
from pathlib import Path

BASE_DIR = Path.home() / ".hermes/profiles/ai-investor"
INDEX_PATH = BASE_DIR / "skill_index.json"

# ── L1: Always-loaded — core identity, used >80% of sessions ──
ALWAYS_LOADED = {
    # === 核心身份 ===
    "karpathy-llm-wiki",      # 第二大脑, wiki全文检索
    "ecc-agent-engineering",  # 编码纪律, 三角色流水线
    "kms",                    # 知识管理系统
    "analysis-frameworks",    # 32大投资分析框架
    "stock-research",         # 多市场证券数据
    "investment-analysis",    # 分析工具箱(回测/估值/因子)
    "systematic-learning",    # 系统性知识构建
    "morning-routine",        # 每日早检+简报
    "workflow-generator",     # 5步+多源并行工作流
    
    # === 数据采集 ===
    "financial-news",         # 财经快讯(财联社/雪球/巨潮)
    "aihot",                  # AI实时资讯
    "duckduckgo-search",      # 公开网络搜索
    "arxiv",                  # AI论文检索
    "wechat-article-scraper", # 公众号文章采集
    
    # === 分析 ===
    "investment-report",      # 研报/周报撰写
    "markdown-viewer",        # 图表/架构图可视化
    
    # === 学习 ===
    "youtube-content",        # YouTube 视频→笔记
    "book-note-maker",        # PDF 书籍→笔记
    "systematic-learning",    # 学习路径构建
    
    # === 多模态 ===
    "mmx-cli",                # MiniMax 多模态(视觉/语音/视频/音乐)
    "apikey-image-gen",       # 图像生成
    
    # === 投资编排器 ===
    "daily-review-orchestrator",      # 每日复盘
    "stock-research-orchestrator",    # 个股研究编排
    "strategy-backtest-orchestrator", # 策略回测编排
    "factor-deep-dive-orchestrator",  # 因子拆解编排
    
    # === 工程 ===
    "hermes-operations",      # Hermes操作命令
    "model-provider-integration", # 模型配置
    "data-source-integration",    # 数据源集成
    "self-audit",             # 体系自检
    "design-review",          # 设计审查
    
    # === Mole (surge suppression) ===
    "spike",                  # 快速实验验证
    "plan",                   # 规划模式
    "subagent-driven-development", # 委托子代理
}

# ── L3: Dormant — already in skills-rare/ or should be moved ──
# These are the 29 skills already in skills-rare/ + a few more we should demote
DORMANT = {
    # Already in skills-rare/ (29)
    "apple-notes", "apple-reminders", "findmy", "imessage", "macos-computer-use",
    "architecture-diagram", "ascii-art", "ascii-video",
    "baoyu-article-illustrator", "baoyu-comic", "baoyu-infographic",
    "claude-design", "comfyui", "creative-ideation", "design-md", "excalidraw",
    "humanizer", "manim-video", "p5js", "pixel-art", "popular-web-designs",
    "pretext", "sketch", "songwriting-and-ai-music", "touchdesigner-mcp",
    "minecraft-modpack-server", "pokemon-player",
    "godmode", "openhue",
    
    # Demote from core to dormant (seldom used niche)
    "gif-search", "songsee", "heartmula",
    "audiocraft-audio-generation", "segment-anything-model", "obliteratus",
    "serving-llms-vllm", "evaluating-llms-harness", "weights-and-biases",
    "spotify",
    "node-inspect-debugger", "hermes-s6-container-supervision",
    "red-teaming", "dogfood",
}

def load_skills():
    """Load current skill index."""
    with open(INDEX_PATH) as f:
        return json.load(f)

def build_layer_mapping():
    """Build {skill_name: layer} mapping for all known skills."""
    idx = load_skills()
    layers = {}
    for s in idx["skills"]:
        name = s["name"]
        if name in ALWAYS_LOADED:
            layers[name] = 1
        elif name in DORMANT or s["dir"] == "rare":
            layers[name] = 3
        else:
            layers[name] = 2
    return layers

def update_index():
    """Write layer field into skill_index.json."""
    idx = load_skills()
    layers = build_layer_mapping()
    updated = 0
    for s in idx["skills"]:
        name = s["name"]
        if name in layers:
            s["layer"] = layers[name]
            updated += 1
        else:
            s["layer"] = 2  # default to resolver-routed
    
    idx["layers"] = {
        "L1_always": sum(1 for s in idx["skills"] if s.get("layer") == 1),
        "L2_resolver": sum(1 for s in idx["skills"] if s.get("layer") == 2),
        "L3_dormant": sum(1 for s in idx["skills"] if s.get("layer") == 3),
    }
    
    with open(INDEX_PATH, "w") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Updated {updated} skills with layer info")
    print(f"   L1 (Always): {idx['layers']['L1_always']}")
    print(f"   L2 (Resolver): {idx['layers']['L2_resolver']}")
    print(f"   L3 (Dormant): {idx['layers']['L3_dormant']}")

def resolve(query: str, top_k: int = 5):
    """Given a user query, find top matching L2 skills by keyword."""
    idx = load_skills()
    layers = build_layer_mapping()
    
    # Chinese text needs substring matching, not whitespace split
    # Extract meaningful terms: alphanumeric + CJK bigrams
    raw = query.lower()
    terms = set()
    # Add whole words (English alphanumeric tokens)
    for w in re.findall(r'[a-zA-Z0-9_]+', raw):
        if len(w) >= 2:
            terms.add(w)
    # Add CJK bigrams for Chinese text
    cjk = re.findall(r'[\u4e00-\u9fff]+', raw)
    for chunk in cjk:
        if len(chunk) >= 2:
            terms.add(chunk)
        # Bigrams
        for i in range(len(chunk) - 1):
            terms.add(chunk[i:i+2])
    
    scores = []
    for s in idx["skills"]:
        name = s["name"]
        layer = layers.get(name, 2)
        if layer != 2:
            continue
        
        # Build search text: description + name + tags
        desc = s.get("description", "")
        tags_text = " ".join(s.get("tags", []))
        haystack = f"{desc} {name} {tags_text}".lower()
        
        hits = 0
        for term in terms:
            if term in haystack:
                hits += 1
                # Bonus for exact CJK match in description
                if term in desc.lower():
                    hits += 1
        
        if hits > 0:
            scores.append((hits, name, desc[:80]))
    
    scores.sort(key=lambda x: -x[0])
    print(f"Query: {query}")
    print(f"Top {top_k} L2 matches:")
    if scores:
        for hits, name, desc in scores[:top_k]:
            print(f"  [{hits}] {name:40s} — {desc}")
    else:
        print("  (no L2 matches — user intent likely covered by L1)")

def validate():
    """Check all L1 skills exist in index."""
    idx = load_skills()
    existing = {s["name"] for s in idx["skills"]}
    
    missing = ALWAYS_LOADED - existing
    if missing:
        print(f"❌ L1 skills missing from index: {sorted(missing)}")
    else:
        print(f"✅ All {len(ALWAYS_LOADED)} L1 skills exist in index")
    
    # Check L1 skills for reasonable size
    for s in idx["skills"]:
        if s["name"] in ALWAYS_LOADED and s["size_bytes"] > 20000:
            print(f"⚠️  L1 skill '{s['name']}' is large: {s['size_bytes']/1000:.0f}KB")

def stats():
    """Print layer statistics."""
    idx = load_skills()
    layers = build_layer_mapping()
    
    by_layer = {1: [], 2: [], 3: []}
    for name, layer in layers.items():
        by_layer[layer].append(name)
    
    total_size = sum(s["size_bytes"] for s in idx["skills"])
    l1_size = sum(s["size_bytes"] for s in idx["skills"] if s["name"] in ALWAYS_LOADED)
    
    print(f"Total skills: {len(layers)}")
    print(f"L1 (Always-loaded): {len(by_layer[1])} skills, {l1_size/1000:.0f}KB total")
    print(f"L2 (Resolver-routed): {len(by_layer[2])} skills")
    print(f"L3 (Dormant): {len(by_layer[3])} skills")
    print()
    print("L1 skills:")
    for name in sorted(by_layer[1]):
        size = next((s["size_bytes"] for s in idx["skills"] if s["name"] == name), 0)
        print(f"  {name:40s} {size/1000:>5.0f}KB")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Three-layer skill index manager")
    parser.add_argument("--update-index", action="store_true", help="Regenerate skill_index.json with layer field")
    parser.add_argument("--resolve", nargs="*", help="Match L2 skills from user query")
    parser.add_argument("--validate", action="store_true", help="Check L1 skills exist")
    parser.add_argument("--top-k", type=int, default=5, help="Max L2 matches to show")
    args = parser.parse_args()

    if args.update_index:
        update_index()
    elif args.resolve:
        query = " ".join(args.resolve)
        resolve(query, top_k=args.top_k)
    elif args.validate:
        validate()
    else:
        stats()
        print()
        validate()
