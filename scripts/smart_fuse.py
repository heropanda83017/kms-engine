#!/usr/bin/env python3
"""智能笔记融合引擎

基于 TF-IDF + 标签 + 域 多维相似度，为新笔记找到最佳融合目标。

用法:
  python scripts/smart_fuse.py <新笔记路径>          # 找融合候选
  python scripts/smart_fuse.py <路径> --merge <目标>   # 执行融合
  python scripts/smart_fuse.py --scan                 # 全库扫描孤岛
  python scripts/smart_fuse.py --watch                # 监听模式
"""

import sys, re, math, json, shutil
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR

# ─── Tokenizer ─────────────────────────────────────────────
def tokenize(text):
    """中文 + 英文分词"""
    # 中文: 2-4字滑动窗口
    chinese = re.findall(r"[\\u4e00-\\u9fff]{2,4}", text)
    # 英文: 单词
    english = re.findall(r"[a-zA-Z][a-zA-Z0-9_#+.-]{1,}", text.lower())
    # 数字+单位: "32次", "7.6KB"
    numbers = re.findall(r"\\d+[a-zA-Z%]*", text)
    return chinese + english + numbers

def build_tfidf(notes):
    """构建 TF-IDF 模型 (纯 Python, 无外部依赖)"""
    # term -> document frequency
    df = Counter()
    note_terms = {}
    
    for path, content in notes:
        terms = tokenize(content)
        note_terms[path] = terms
        for term in set(terms):
            df[term] += 1
    
    N = len(notes)
    idf = {term: math.log(N / (1 + freq)) + 1 for term, freq in df.items()}
    
    # Build TF-IDF vectors
    vectors = {}
    for path, terms in note_terms.items():
        tf = Counter(terms)
        max_tf = max(tf.values()) if tf else 1
        vec = {}
        for term, count in tf.items():
            vec[term] = (count / max_tf) * idf.get(term, 1)
        vectors[path] = vec
    
    return vectors, idf

def cosine_similarity(vec1, vec2):
    """余弦相似度"""
    common = set(vec1.keys()) & set(vec2.keys())
    if not common:
        return 0.0
    
    dot = sum(vec1[t] * vec2[t] for t in common)
    norm1 = math.sqrt(sum(v * v for v in vec1.values()))
    norm2 = math.sqrt(sum(v * v for v in vec2.values()))
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def parse_frontmatter(content):
    """从内容提取 frontmatter"""
    fm = {"title": "", "type": "reference", "domain": "", "tags": [], "source": ""}
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            for line in content[3:end].strip().split("\\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key == "tags":
                        val = val.strip("[]")
                        fm["tags"] = [t.strip().strip("'\"") for t in val.split(",") if t.strip()]
                    elif key in ("title", "type", "domain", "source"):
                        fm[key] = val
    return fm

def strip_frontmatter(content):
    """去除 frontmatter 只保留正文"""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].strip()
    return content.strip()

# ─── 融合引擎 ─────────────────────────────────────────────
def find_fusion_candidates(new_note_path, top_n=5, min_score=0.15):
    """为新笔记找到最佳融合候选"""
    # 读取新笔记
    new_content = new_note_path.read_text(encoding="utf-8", errors="ignore")
    new_fm = parse_frontmatter(new_content)
    new_body = strip_frontmatter(new_content)
    new_terms = tokenize(new_body)
    
    # 扫描所有 wiki 笔记
    existing = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f) or f == new_note_path:
            continue
        if f.name == "图谱索引.md":
            continue
        # 跳过 historical 笔记（过时存档，不参与融合）
        raw = f.read_text(encoding="utf-8", errors="ignore")
        if "status: historical" in raw.split("---")[1] if "---" in raw else "":
            continue
        existing.append((f, raw))
    
    if not existing:
        return []
    
    # 构建 TF-IDF（仅基于现有笔记）
    notes_for_tfidf = [(f, strip_frontmatter(c)) for f, c in existing]
    vectors, idf = build_tfidf(notes_for_tfidf)
    
    # 新笔记的 TF-IDF 向量
    new_tf = Counter(new_terms)
    max_tf = max(new_tf.values()) if new_tf else 1
    new_vec = {}
    for term, count in new_tf.items():
        new_vec[term] = (count / max_tf) * idf.get(term, 1)
    
    # 计算每篇现有笔记的相似度
    scores = []
    for (f, content) in existing:
        rel = str(f.relative_to(WIKI_DIR))
        fm = parse_frontmatter(content)
        
        # --- 维度 1: 内容相似度 (权重 0.5) ---
        path_key = f
        if path_key in vectors:
            content_sim = cosine_similarity(new_vec, vectors[path_key])
        else:
            content_sim = 0.0
        
        # --- 维度 2: 标签重叠 (权重 0.3) ---
        tag_sim = 0.0
        if new_fm["tags"] and fm["tags"]:
            common_tags = set(new_fm["tags"]) & set(fm["tags"])
            if common_tags:
                tag_sim = len(common_tags) / max(len(new_fm["tags"]), len(fm["tags"]))
        
        # --- 维度 3: 域匹配 (权重 0.2) ---
        domain_match = 1.0 if new_fm["domain"] == fm["domain"] and new_fm["domain"] else 0.0
        
        # --- 综合评分 ---
        total = content_sim * 0.5 + tag_sim * 0.3 + domain_match * 0.2
        
        if total >= min_score:
            scores.append({
                "path": rel,
                "title": fm["title"] or f.stem,
                "domain": fm["domain"],
                "tags": fm["tags"],
                "content_sim": round(content_sim, 3),
                "tag_sim": round(tag_sim, 3),
                "domain_match": domain_match,
                "total_score": round(total, 3),
            })
    
    scores.sort(key=lambda x: -x["total_score"])
    return scores[:top_n]

def merge_notes(source_path, target_path, check_only=False):
    """将 source 的内容融合到 target"""
    source_content = source_path.read_text(encoding="utf-8", errors="ignore")
    target_content = target_path.read_text(encoding="utf-8", errors="ignore")
    target_fm = parse_frontmatter(target_content)
    
    # 提取 source 正文（去 frontmatter 和标题）
    body = strip_frontmatter(source_content)
    # 去掉 H1 标题
    body = re.sub(r"^# .+\\n?", "", body).strip()
    
    if not body or len(body) < 20:
        return False, "正文太短"
    
    # 去重检查：正文前 100 字
    dedup_key = body[:100].strip()
    if dedup_key in target_content:
        return False, "内容已存在"
    
    if check_only:
        return True, "可融合"
    
    # 融合标记
    source_rel = str(source_path.relative_to(WIKI_DIR)).replace("\\\\", "/")
    block = f"\\n\\n---\\n### 相关内容整合\\n\\n{body}\\n\\n> 整合自 [{source_path.name}]({source_rel}) | {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}\\n"
    
    target_content += block
    target_path.write_text(target_content, encoding="utf-8")
    
    # source 备份后删除
    bak = source_path.with_suffix(source_path.suffix + ".bak")
    if not bak.exists():
        shutil.move(str(source_path), str(bak))
    
    return True, "融合成功"

def scan_orphans():
    """扫描孤岛笔记（0 入链）"""
    orphans = []
    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f) or f.name == "图谱索引.md":
            continue
        # 跳过 historical
        raw = f.read_text(encoding="utf-8", errors="ignore")
        if "status: historical" in raw.split("---")[1] if "---" in raw else "":
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        # 检查是否被其他笔记引用
        ref_count = 0
        for other in WIKI_DIR.rglob("*.md"):
            if ".obsidian" in str(other) or other == f:
                continue
            other_content = other.read_text(encoding="utf-8", errors="ignore")
            if f.stem in other_content:
                ref_count += 1
        
        if ref_count == 0:
            fm = parse_frontmatter(content)
            rel = str(f.relative_to(WIKI_DIR))
            orphans.append({
                "path": rel,
                "title": fm["title"] or f.stem,
                "domain": fm["domain"],
            })
    
    return orphans

def main():
    if "--scan" in sys.argv:
        print("=" * 50)
        print("  智能融合 — 全库扫描")
        print("=" * 50)
        orphans = scan_orphans()
        print(f"\\n孤岛笔记: {len(orphans)} 篇")
        for o in orphans:
            print(f"  🏝️ [{o['domain']}] {o['title'][:50]}")
        return
    
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("-"):
        note_path = Path(sys.argv[1])
        if not note_path.exists():
            print(f"❌ 文件不存在: {note_path}")
            return
        
        # 检查是否在 wiki 内
        try:
            note_path.relative_to(WIKI_DIR)
        except ValueError:
            print(f"❌ 文件不在 wiki 目录内: {note_path}")
            return
        
        merge_target = None
        if "--merge" in sys.argv:
            idx = sys.argv.index("--merge")
            if idx + 1 < len(sys.argv):
                merge_target = WIKI_DIR / sys.argv[idx + 1]
        
        if merge_target:
            ok, msg = merge_notes(note_path, merge_target)
            print(f"  {'✅' if ok else '❌'} {msg}")
            return
        
        # 找融合候选
        print("=" * 50)
        print(f"  📄 {note_path.name}")
        print("=" * 50)
        candidates = find_fusion_candidates(note_path)
        
        if not candidates:
            print("\\n🔍 未找到合适的融合候选")
            print("   这篇笔记是全新的主题，无需融合")
            return
        
        print(f"\\n🔍 找到 {len(candidates)} 个融合候选:")
        print()
        print(f"  {'评分':>6s} {'内容':>6s} {'标签':>6s} {'域':>4s}  笔记")
        print(f"  {'------':>6s} {'------':>6s} {'------':>6s} {'------':>4s}  {'----'}")
        
        for c in candidates:
            tag_str = ",".join(c["tags"][:3]) if c["tags"] else "-"
            dm = "✓" if c["domain_match"] else ""
            title_clean = c['title'].split('\\n')[0].strip()[:50]
            print(f"  {c['total_score']:.3f} {c['content_sim']:.3f} {c['tag_sim']:.3f}  {dm:>3s}  [{c['domain']}] {title_clean}")
            print(f"  {'':>22s} tags: {tag_str}")
            print()

        print("建议: 用 --merge <目标路径> 执行融合")
        print('      python scripts/smart_fuse.py "笔记路径" --merge "目录/文件名.md"')


if __name__ == "__main__":
    main()