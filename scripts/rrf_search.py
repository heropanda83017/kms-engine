#!/usr/bin/env python3
"""
RRF混合搜索引擎 — Reciprocal Rank Fusion hybrid search
Combines SQLite FTS5 (BM25) + sqlite-vec (MiniMax embeddings) + RRF fusion

数据流:
  build_index() → scan wiki → FTS5索引 + 向量DB → 持久化到 kms.db
  search_rrf()  → query → FTS5 hits + vector hits → RRF(1/(k+rank)) → 排序输出

依赖:
  - sqlite-vec 0.1.9+  (向量存储与余弦相似度)
  - MiniMax embo-01 API  (1536维文本嵌入)
  - SQLite FTS5  (内置, 关键词BM25)

用法:
  python3 rrf_search.py build              # 全量构建索引
  python3 rrf_search.py search "关键词"     # RRF混合搜索
  python3 rrf_search.py search "关键词" --mode fts5   # 仅关键词
  python3 rrf_search.py search "关键词" --mode vector # 仅向量
  python3 rrf_search.py status             # 索引状态
"""

import os, sys, json, re, time, hashlib, math, sqlite3
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
KMS_DIR = SCRIPT_DIR.parent
WIKI_DIR = KMS_DIR / "wiki-AIGC-KB"
DB_PATH = KMS_DIR / "kms.db"

# 若 WIKI_DIR 不存在, 尝试父级
if not WIKI_DIR.exists():
    WIKI_DIR = KMS_DIR.parent / "wiki-AIGC-KB"

# 向量维度 (MiniMax embo-01)
VECTOR_DIM = 1536

# RRF常数
RRF_K = 60

# 批处理大小 (MiniMax API 单次调用最大文本数)
BATCH_SIZE = 50


# ════════════════════════════════════════════════
#  MiniMax 嵌入 API
# ════════════════════════════════════════════════

_MINIMAX_KEY = None

def _get_minimax_key():
    global _MINIMAX_KEY
    if _MINIMAX_KEY:
        return _MINIMAX_KEY
    env_paths = [
        Path.home() / ".hermes" / "profiles" / "ai-investor" / ".env",
        Path.home() / ".hermes" / ".env",
        Path("/mnt/e/AIGC-KB/.env"),
    ]
    for env_path in env_paths:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "MINIMAX_CN_API_KEY" in line and "=" in line:
                    raw = line.split("=", 1)[1].strip()
                    _MINIMAX_KEY = raw.strip("'\"")
                    return _MINIMAX_KEY
    raise RuntimeError("MINIMAX_CN_API_KEY not found in any .env")


def _embed_batch(texts, embed_type="db"):
    """调用 MiniMax embedding API 获取一批文本的向量"""
    import urllib.request
    key = _get_minimax_key()
    url = "https://api.minimaxi.com/v1/embeddings"
    data = json.dumps({
        "model": "embo-01",
        "texts": texts,
        "type": embed_type,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    vectors = result.get("vectors", [])
    if not vectors:
        raise RuntimeError(f"MiniMax embedding returned empty vectors: {result}")
    return vectors


def embed_texts(texts, batch_size=BATCH_SIZE, embed_type="db"):
    """将文本列表分批嵌入, 返回 [vector, ...]"""
    all_vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        all_vectors.extend(_embed_batch(batch, embed_type))
    return all_vectors


# ════════════════════════════════════════════════
#  SQLite DB 管理
# ════════════════════════════════════════════════

def _get_db():
    """获取数据库连接 (带 sqlite-vec 加载)"""
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=OFF")  # 批量构建时加速

    # 加载 sqlite-vec 扩展
    db.enable_load_extension(True)
    try:
        import sqlite_vec
        sqlite_vec.load(db)
    except Exception as e:
        print(f"⚠️ sqlite-vec 加载失败: {e}")
    db.enable_load_extension(False)

    return db


def _init_schema(db):
    """创建索引表结构"""
    # FTS5 全文索引
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
            title, content, path,
            tokenize='unicode61'
        )
    """)

    # 向量索引表
    db.execute("""
        CREATE TABLE IF NOT EXISTS wiki_vectors (
            path TEXT PRIMARY KEY,
            title TEXT,
            content_hash TEXT,
            updated_at REAL
        )
    """)

    # sqlite-vec 向量存储
    db.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS wiki_embeddings USING vec0(
            embedding float[{VECTOR_DIM}] distance_metric=cosine
        )
    """)

    # chunk → path 映射表 (rowid → path + chunk_index)
    db.execute("""
        CREATE TABLE IF NOT EXISTS wiki_chunk_map (
            rowid INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            title TEXT
        )
    """)

    # 元数据
    db.execute("""
        CREATE TABLE IF NOT EXISTS wiki_index_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)


def _get_content_hash(content):
    """计算内容的简短哈希, 用于增量更新判断"""
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]


def _extract_title(content, filepath):
    """从 frontmatter 或文件名提取标题"""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            for line in content[3:end].strip().split("\n"):
                line = line.strip()
                if line.startswith("title:"):
                    return line.split(":", 1)[1].strip().strip("\"'")
    return filepath.stem


def _strip_markdown(text):
    """去除 markdown 标记, 保留纯文本"""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\(.*?\)', r'\1', text)
    text = re.sub(r'[#*`~>|-]', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()


def _chunk_text(text, max_chars=2000, overlap=300):
    """将长文本分割成有意义的块, 优先按标题拆分, 用于精确的向量匹配"""
    # Try splitting by markdown headers first
    sections = re.split(r'\n(?=#+\s)', text)
    if len(sections) <= 1:
        # Fall back to paragraph splitting
        sections = text.split("\n\n")

    chunks = []
    current = ""
    for s in sections:
        s = s.strip()
        if not s:
            continue
        if len(current) + len(s) > max_chars and current:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + s if overlap else s
        else:
            current = (current + "\n\n" + s).strip() if current else s
    if current:
        chunks.append(current)
    return chunks if chunks else [text[:max_chars]]


# ════════════════════════════════════════════════
#  索引构建
# ════════════════════════════════════════════════

def _scan_wiki():
    """扫描 wiki 目录, 返回所有 .md 文件的路径和内容"""
    files = []
    if not WIKI_DIR.exists():
        print(f"❌ wiki 目录不存在: {WIKI_DIR}")
        return files

    for f in sorted(WIKI_DIR.rglob("*.md")):
        if ".obsidian" in str(f) or f.name.startswith("CHANGELOG"):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            files.append((f, content))
        except Exception as e:
            print(f"⚠️ 无法读取 {f}: {e}")
    return files


def build_index_incremental():
    """增量构建索引: 只重新索引内容变更的文件

    策略:
    - 对比 content_hash, 只处理新增/修改/删除的文件
    - 未变更的文件完全跳过 (不调 API, 不写 DB)
    - 适用于每日增量更新 (< 5s 大多数日子)
    """
    t0 = time.time()
    db = _get_db()
    _init_schema(db)

    # 获取已索引文件的 hash 映射
    stored = {}
    for row in db.execute("SELECT path, content_hash FROM wiki_vectors").fetchall():
        stored[row[0]] = row[1]

    scanned = set()
    changed = []  # 新文件或内容变更的文件
    unchanged = 0

    files = _scan_wiki()
    for fpath, content in files:
        rel = str(fpath.relative_to(WIKI_DIR))
        scanned.add(rel)
        current_hash = _get_content_hash(content)

        if rel in stored and stored[rel] == current_hash:
            # 未变更, 跳过
            unchanged += 1
            continue

        changed.append((fpath, content, rel, current_hash))

    # 被删除的文件 (在索引中但不在文件系统中)
    deleted = [p for p in stored if p not in scanned]

    if not changed and not deleted:
        elapsed = time.time() - t0
        print(f"✅ 无需更新: {unchanged} 个文件均未变更 ({elapsed:.1f}s)")
        return

    print(f"📝  增量更新: 新增/变更 {len(changed)} 个, 删除 {len(deleted)} 个, 跳过 {unchanged} 个")

    # 1. 处理新增/变更文件
    embed_texts_list = []
    embed_meta = []

    for fpath, content, rel, content_hash in changed:
        title = _extract_title(content, fpath)

        # FTS5: 用去标记后的纯文本
        plain = _strip_markdown(content)
        db.execute("DELETE FROM wiki_fts WHERE path = ?", (rel,))
        db.execute(
            "INSERT INTO wiki_fts (title, content, path) VALUES (?, ?, ?)",
            (title, plain[:100000], rel)
        )

        # 更新元数据
        db.execute(
            "INSERT OR REPLACE INTO wiki_vectors (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            (rel, title, content_hash, time.time())
        )

        # 准备嵌入文本: 先按原始内容分块 (保留标题结构), 再逐块去标记
        chunks = _chunk_text(content)
        for ci, chunk in enumerate(chunks):
            plain_chunk = _strip_markdown(chunk)
            if len(plain_chunk.strip()) < 50:
                continue
            embed_texts_list.append(plain_chunk[:2000])
            embed_meta.append((rel, title, ci))

    # 2. 删除已从文件系统移除的条目
    for rel in deleted:
        db.execute("DELETE FROM wiki_vectors WHERE path = ?", (rel,))
        db.execute("DELETE FROM wiki_fts WHERE path = ?", (rel,))
        # 删除对应的向量嵌入 (通过 chunk_map 的 rowid)
        for row in db.execute(
            "SELECT rowid FROM wiki_chunk_map WHERE path = ?", (rel,)
        ).fetchall():
            try:
                db.execute(f"DELETE FROM wiki_embeddings WHERE rowid = {row[0]}")
            except Exception:
                pass
        db.execute("DELETE FROM wiki_chunk_map WHERE path = ?", (rel,))

    # 3. 生成新嵌入
    if embed_texts_list:
        print(f"🧠  生成向量嵌入 ({len(embed_texts_list)} chunks) via MiniMax embo-01...")
        vectors = embed_texts(embed_texts_list, embed_type="db")

        # 清理旧嵌入 (先删除对应行)
        for rel, _, _ in embed_meta:
            for row in db.execute(
                "SELECT rowid FROM wiki_chunk_map WHERE path = ?", (rel,)
            ).fetchall():
                try:
                    db.execute(f"DELETE FROM wiki_embeddings WHERE rowid = {row[0]}")
                except Exception:
                    pass
            db.execute("DELETE FROM wiki_chunk_map WHERE path = ?", (rel,))

        # 写入新嵌入
        for (rel, title, ci), vec in zip(embed_meta, vectors):
            cursor = db.execute(
                "INSERT INTO wiki_embeddings (embedding) VALUES (?)",
                (json.dumps(vec),)
            )
            new_rowid = cursor.lastrowid
            db.execute(
                "INSERT INTO wiki_chunk_map (rowid, path, chunk_index, title) VALUES (?, ?, ?, ?)",
                (new_rowid, rel, ci, title)
            )

    db.commit()
    elapsed = time.time() - t0
    print(f"✅ 增量索引完成: 变更 {len(changed)} / 删除 {len(deleted)} / 跳过 {unchanged} ({elapsed:.1f}s)")

    # 更新元数据
    total = db.execute("SELECT COUNT(*) FROM wiki_vectors").fetchone()[0]
    db.execute("INSERT OR REPLACE INTO wiki_index_meta (key, value) VALUES (?, ?)",
               ("total_files", str(total)))
    db.execute("INSERT OR REPLACE INTO wiki_index_meta (key, value) VALUES (?, ?)",
               ("last_built", str(time.time())))


def build_index():
    """全量构建 FTS5 + 向量索引"""
    t0 = time.time()
    db = _get_db()
    _init_schema(db)

    print(f"🗂️  扫描 wiki: {WIKI_DIR}")
    files = _scan_wiki()
    print(f"   找到 {len(files)} 个 .md 文件")

    # 清空旧索引 (先DROP再CREATE确保schema刷新)
    db.execute("DROP TABLE IF EXISTS wiki_fts")
    db.execute("DROP TABLE IF EXISTS wiki_embeddings")
    db.execute("DROP TABLE IF EXISTS wiki_chunk_map")
    _init_schema(db)  # 重新创建
    db.execute("DELETE FROM wiki_vectors")
    db.execute("DELETE FROM wiki_index_meta")

    # 收集需要嵌入的文本
    embed_texts_list = []
    embed_meta = []  # [(path, title, chunk_idx)]

    print(f"\n📝  构建 FTS5 索引 ({len(files)} 文件)...")
    for fpath, content in files:
        rel = str(fpath.relative_to(WIKI_DIR))
        title = _extract_title(content, fpath)
        content_hash = _get_content_hash(content)

        # FTS5: 按文件索引 (用去标记后的纯文本)
        plain = _strip_markdown(content)
        db.execute(
            "INSERT INTO wiki_fts (title, content, path) VALUES (?, ?, ?)",
            (title, plain[:100000], rel)
        )

        # 保存元数据
        db.execute(
            "INSERT OR REPLACE INTO wiki_vectors (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            (rel, title, content_hash, time.time())
        )

        # 准备嵌入文本: 先按原始内容分块 (保留标题结构), 再逐块去标记
        chunks = _chunk_text(content)
        for ci, chunk in enumerate(chunks):
            plain_chunk = _strip_markdown(chunk)
            if len(plain_chunk.strip()) < 50:
                continue  # 跳过过小的块 (纯标题等)
            embed_texts_list.append(plain_chunk[:2000])
            embed_meta.append((rel, title, ci))

        if len(files) <= 5 or len(embed_texts_list) % 50 == 0:
            print(f"   FTS5: {len(embed_texts_list)} chunks prepared...")

    print(f"\n🧠  生成向量嵌入 ({len(embed_texts_list)} chunks) via MiniMax embo-01...")
    # 分批嵌入
    all_vectors = embed_texts(embed_texts_list)
    print(f"   嵌入完成: {len(all_vectors)} vectors")

    # 写入向量表 + chunk_map
    print(f"\n💾  写入向量索引 {VECTOR_DIM}d + chunk_map...")
    inserted = 0
    for (rel, title, ci), vec in zip(embed_meta, all_vectors):
        rowid = abs(hash(f"{rel}#{ci}")) % (2**63 - 1)
        embedding_str = json.dumps([float(v) for v in vec])
        try:
            db.execute(
                "INSERT INTO wiki_embeddings (rowid, embedding) VALUES (?, ?)",
                (rowid, embedding_str)
            )
            db.execute(
                "INSERT OR IGNORE INTO wiki_chunk_map (rowid, path, chunk_index, title) VALUES (?, ?, ?, ?)",
                (rowid, rel, ci, title)
            )
            inserted += 1
        except Exception as e:
            print(f"⚠️ 写入向量失败 {rel}#{ci}: {e}")

    # 保存元数据
    db.execute("INSERT OR REPLACE INTO wiki_index_meta (key, value) VALUES (?, ?)",
               ("total_files", str(len(files))))
    db.execute("INSERT OR REPLACE INTO wiki_index_meta (key, value) VALUES (?, ?)",
               ("total_chunks", str(len(embed_texts_list))))
    db.execute("INSERT OR REPLACE INTO wiki_index_meta (key, value) VALUES (?, ?)",
               ("indexed_at", str(time.time())))

    db.commit()
    elapsed = time.time() - t0
    print(f"\n✅ 索引构建完成: {inserted} vectors in {elapsed:.1f}s")
    print(f"   DB: {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"   文件: {len(files)} | 块: {len(embed_texts_list)} | 维: {VECTOR_DIM}")

    return {"files": len(files), "chunks": len(embed_texts_list), "vectors": inserted, "elapsed": elapsed}


# ════════════════════════════════════════════════
#  搜索
# ════════════════════════════════════════════════

def _fts5_search(db, query, top_k=20):
    """FTS5 BM25 关键词搜索"""
    # SQLite FTS5 使用 MATCH 语法, 但需要转义特殊字符
    safe_query = re.sub(r'[^\w\u4e00-\u9fff\s]', ' ', query)
    safe_query = ' OR '.join(safe_query.split())  # 默认 OR 匹配
    if not safe_query.strip():
        return []

    try:
        rows = db.execute(
            "SELECT rank, path, title FROM wiki_fts WHERE wiki_fts MATCH ? ORDER BY rank LIMIT ?",
            (safe_query, top_k)
        ).fetchall()
        results = []
        for rank, path, title in rows:
            # BM25: rank is the score, lower is better → 1/(1+rank)
            score = 1.0 / (1.0 + rank)
            results.append({"path": path, "title": title, "score": score, "rank": len(results)})
        return results
    except Exception as e:
        print(f"⚠️ FTS5 搜索失败: {e}")
        return []


def _vector_search(db, query_vec, top_k=20):
    """向量余弦相似度搜索"""
    if query_vec is None:
        return []

    embedding_str = json.dumps([float(v) for v in query_vec])
    try:
        rows = db.execute(
            "SELECT rowid, distance FROM wiki_embeddings WHERE embedding MATCH ? AND k = ?",
            (embedding_str, top_k)
        ).fetchall()
        # rowid → 解析回 path#chunk_idx
        results = []
        for rowid, distance in rows:
            score = 1.0 - distance  # cosine distance → similarity
            results.append({"rowid": rowid, "distance": distance, "score": score})
        return results
    except Exception as e:
        print(f"⚠️ Vector 搜索失败: {e}")
        return []


def _resolve_rowid(rowid):
    """从 rowid 反查 path + chunk 信息"""
    # 当前设计 rowid = hash(path#chunk_idx), 无法直接反查
    # 需要建立一个从 rowid → path 的映射表
    # 但当前 wiki_vectors 表是按文件存储的, 没有 chunk 级别映射
    # 我们可以在构建时维护一个映射表
    return None


def rrf_fuse(fts5_results, vector_results, k=RRF_K, top_k=10):
    """RRF (Reciprocal Rank Fusion) 融合两个排序结果"""
    # 累加器: {path: {score, rank_fts5, rank_vec, title, ...}}
    fused = {}

    for r in fts5_results:
        path = r["path"]
        fused[path] = {
            "path": path,
            "title": r.get("title", ""),
            "rrf_score": 1.0 / (k + r["rank"] + 1),
            "fts5_score": r["score"],
            "fts5_rank": r["rank"],
            "has_fts5": True,
            "has_vector": False,
        }

    for r in vector_results:
        path = r.get("path", _resolve_rowid(r.get("rowid")))
        if not path:
            continue
        if path in fused:
            fused[path]["rrf_score"] += 1.0 / (k + (fused[path].get("vector_rank", 0) + 1))
            fused[path]["vector_score"] = r["score"]
            fused[path]["has_vector"] = True
        else:
            fused[path] = {
                "path": path,
                "title": "",
                "rrf_score": 1.0 / (k + 1),  # vector only
                "fts5_score": 0,
                "vector_score": r["score"],
                "has_fts5": False,
                "has_vector": True,
            }

    # 按 RRF 得分排序
    ranked = sorted(fused.values(), key=lambda x: -x["rrf_score"])
    for i, r in enumerate(ranked[:top_k]):
        r["final_rank"] = i + 1

    return ranked[:top_k]


def search_rrf(query, top_k=10, mode="rrf"):
    """执行 RRF 混合搜索"""
    t0 = time.time()
    db = _get_db()
    _init_schema(db)

    # 检查索引是否存在
    meta_count = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='wiki_chunk_map'").fetchone()[0]
    if meta_count == 0:
        return {"error": "索引不存在，请先运行 'python3 rrf_search.py build'", "results": []}

    # 1. FTS5 关键词搜索
    fts5_results = _fts5_search(db, query, top_k=20) if mode in ("rrf", "fts5") else []

    # 向量搜索
    vector_results = []
    if mode in ("rrf", "vector"):
        try:
            query_vec = embed_texts([query], embed_type="query")[0]
            raw_vector = _vector_search(db, query_vec, top_k=20)
            for rv in raw_vector:
                path = _resolve_rowid_fast(db, rv["rowid"])
                if path:
                    vector_results.append({"path": path, **rv})
        except Exception as e:
            print(f"⚠️ 向量搜索失败: {e}")

    # 3. RRF 融合
    if mode == "rrf":
        results = rrf_fuse(fts5_results, vector_results, top_k=top_k)
    elif mode == "fts5":
        results = fts5_results[:top_k]
        # 统一字段名
        for r in results:
            r["fts5_score"] = r.pop("score", 0)
            r["rrf_score"] = r["fts5_score"]
    elif mode == "vector":
        results = sorted(vector_results, key=lambda x: -x["score"])[:top_k]
        for r in results:
            r["vector_score"] = r.pop("score", 0)
            r["rrf_score"] = r["vector_score"]
    else:
        results = fts5_results[:top_k]

    # 补充 title
    for r in results:
        if not r.get("title"):
            row = db.execute("SELECT title FROM wiki_vectors WHERE path = ?", (r["path"],)).fetchone()
            if row:
                r["title"] = row[0]

    elapsed = time.time() - t0
    return {"results": results, "elapsed": elapsed, "mode": mode, "query": query}


def _resolve_rowid_fast(db, rowid):
    """从 rowid 反查 path (通过 chunk_map)"""
    row = db.execute("SELECT path, title FROM wiki_chunk_map WHERE rowid = ?", (rowid,)).fetchone()
    if row:
        return row[0]
    return None


def _search_flat(db, query, top_k=10):
    """回退方案: 直接全文扫描 (当前 kms.py cmd_search 的方式)"""
    results = []
    keyword = query.lower()
    for f in WIKI_DIR.rglob("*.md"):
        if ".obsidian" in str(f):
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if keyword not in content.lower() and keyword not in str(f).lower():
                continue
            rel = str(f.relative_to(WIKI_DIR))
            lines = [l.strip() for l in content.split("\n") if keyword in l.lower()][:2]
            results.append({"path": rel, "title": _extract_title(content, f), "lines": lines})
        except Exception:
            continue
    return results[:top_k]


# ════════════════════════════════════════════════
#  状态
# ════════════════════════════════════════════════

def show_status():
    """显示索引状态"""
    db = _get_db()
    _init_schema(db)

    fts_count = db.execute("SELECT COUNT(*) FROM wiki_fts").fetchone()[0]
    vec_count = db.execute("SELECT COUNT(*) FROM wiki_vectors").fetchone()[0]
    embed_count = db.execute("SELECT COUNT(*) FROM wiki_embeddings").fetchone()[0]

    meta = {}
    for row in db.execute("SELECT key, value FROM wiki_index_meta"):
        meta[row[0]] = row[1]

    print("=" * 50)
    print("  RRF 混合搜索 — 索引状态")
    print("=" * 50)
    wc = WIKI_DIR
    actual_files = len(list(wc.rglob("*.md"))) - len(list(wc.rglob(".obsidian/**/*.md")))
    print(f"\n🗂️  Wiki: {wc}")
    print(f"   实际 .md 文件数: ? (估算 ~{actual_files})")
    print(f"\n📦 DB: {DB_PATH}")
    if DB_PATH.exists():
        print(f"   大小: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"\n📊 索引统计:")
    print(f"   FTS5 条目:     {fts_count}")
    print(f"   文件元数据:     {vec_count}")
    print(f"   向量条目:       {embed_count}")
    print(f"   总文件数:       {meta.get('total_files', '?')}")
    print(f"   总块数:         {meta.get('total_chunks', '?')}")
    if "indexed_at" in meta:
        import datetime
        dt = datetime.datetime.fromtimestamp(float(meta["indexed_at"]))
        print(f"   索引时间:       {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print()


# ════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "build":
        build_index()

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("用法: rrf_search.py search <关键词> [--mode rrf|fts5|vector] [--top-k N]")
            return
        query = sys.argv[2]
        mode = "rrf"
        top_k = 10
        for i, a in enumerate(sys.argv[3:], 3):
            if a == "--mode" and i + 1 < len(sys.argv):
                mode = sys.argv[i + 1]
            if a == "--top-k" and i + 1 < len(sys.argv):
                top_k = int(sys.argv[i + 1])

        result = search_rrf(query, top_k=top_k, mode=mode)
        if "error" in result:
            print(f"❌ {result['error']}")
            return

        elapsed = result.get("elapsed", 0)
        print(f"\n🔍 RRF 搜索: \"{query}\" (mode={mode})")
        print(f"   耗时: {elapsed:.2f}s")
        print()
        for r in result.get("results", []):
            flags = []
            if r.get("has_fts5"):
                flags.append("📝")
            if r.get("has_vector"):
                flags.append("🧠")
            flag_str = "".join(flags) if flags else "  "
            print(f"  #{r.get('final_rank', '?'):2d} {flag_str}  [{r['path']}]")
            title = r.get("title", "") or ""
            if title:
                print(f"        {title}")
            fts = r.get("fts5_score", 0)
            vec = r.get("vector_score", 0)
            print(f"        RRF得分: {r.get('rrf_score', 0):.4f}  "
                  f"FTS5: {fts:.4f}  "
                  f"Vec: {vec:.4f}")
            print()

    elif cmd == "status":
        show_status()

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
