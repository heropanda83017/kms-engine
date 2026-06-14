#!/usr/bin/env python3
"""kg_store.py — 实体存储层（SQLite版）

Phase 2 升级：从 JSON 迁移到 SQLite，保留完整 API 签名兼容。
Phase 1 JSON 数据自动迁移后保留为备份。

数据文件：
  CONFIG_DIR/kg-store/kg.db     # SQLite 数据库
  CONFIG_DIR/kg-store/*.json    # Phase1 备份（迁移后只读）

API（100%向后兼容）:
  upsert_entity(name, type, domain, description, aliases) -> dict
  add_entity_note(name, note_path, count=1)
  add_relation(source, target, rtype, description="")
  batch_store(entities, relations, note_path)
  get_entities_for_note(note_path) -> list[dict]
  search_entities(query, limit=10) -> list[dict]
  get_related_entities(name, max_depth=1) -> dict
  find_path(source_name, target_name, max_depth=5) -> list[list]
  merge_entities(canonical_name, alias_names) -> dict
  get_stats() -> dict
  get_all_entities() -> dict
  get_all_relations() -> list
  reset()
"""

import json, os, sys, sqlite3, time
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import CONFIG_DIR
from kg_entity_types import valid_entity_type, valid_relation_type

# ── 存储根目录 ────────────────────────────────────────
STORE_DIR = CONFIG_DIR / "kg-store"
STORE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = STORE_DIR / "kg.db"
WAL_PATH = STORE_DIR / "kg.db-wal"
SHM_PATH = STORE_DIR / "kg.db-shm"

# JSON 文件（Phase1 备份）
ENTITIES_FILE = STORE_DIR / "entities.json"
RELATIONS_FILE = STORE_DIR / "relations.json"
NOTE_ENTITIES_FILE = STORE_DIR / "note_entities.json"
STATS_FILE = STORE_DIR / "stats.json"

# ── 数据库连接（线程本地） ────────────────────────────
_conn: Optional[sqlite3.Connection] = None
_initialized = False


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接（惰性初始化）"""
    global _conn, _initialized
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("PRAGMA busy_timeout=5000")
    if not _initialized:
        _init_schema()
        _migrate_from_json()
        _initialized = True
    return _conn


def _init_schema():
    """初始化数据库表结构（使用已有连接）"""
    c = _conn
    if c is None:
        return
    c.executescript("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL COLLATE NOCASE,
            type TEXT NOT NULL,
            domain TEXT DEFAULT '',
            description TEXT DEFAULT '',
            aliases TEXT DEFAULT '[]',
            first_seen TEXT,
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS entity_notes (
            entity_id INTEGER NOT NULL,
            note_path TEXT NOT NULL,
            occurrences INTEGER DEFAULT 1,
            last_seen TEXT,
            PRIMARY KEY (entity_id, note_path),
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        );

        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            description TEXT DEFAULT '',
            first_seen TEXT,
            last_seen TEXT,
            UNIQUE(source_id, target_id, type),
            FOREIGN KEY (source_id) REFERENCES entities(id),
            FOREIGN KEY (target_id) REFERENCES entities(id)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
        CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
        CREATE INDEX IF NOT EXISTS idx_entity_notes_path ON entity_notes(note_path);
        CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
        CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
    """)
    if _conn:
        _conn.commit()


def _migrate_from_json():
    """从 Phase1 JSON 迁移数据到 SQLite（幂等）"""
    c = _conn
    if c is None:
        return
    # 检查是否已迁移
    row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row:
        return  # 已迁移

    if not ENTITIES_FILE.exists():
        # 标记已迁移（无数据）
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                  ("schema_version", "2.0"))
        c.commit()
        return

    # 加载 JSON 数据
    entities = json.loads(ENTITIES_FILE.read_text(encoding="utf-8")) if ENTITIES_FILE.exists() else {}
    relations = json.loads(RELATIONS_FILE.read_text(encoding="utf-8")) if RELATIONS_FILE.exists() else []
    note_entities = json.loads(NOTE_ENTITIES_FILE.read_text(encoding="utf-8")) if NOTE_ENTITIES_FILE.exists() else {}
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8")) if STATS_FILE.exists() else {}

    migrated_count = 0
    for name, ent in entities.items():
        try:
            c.execute("""
                INSERT OR IGNORE INTO entities (name, type, domain, description, aliases, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                name,
                ent.get("type", "concept"),
                ent.get("domain", ""),
                ent.get("description", ""),
                json.dumps(ent.get("aliases", []), ensure_ascii=False),
                ent.get("first_seen", datetime.now().isoformat()),
                ent.get("last_seen", datetime.now().isoformat()),
            ))
            migrated_count += 1
        except Exception as e:
            print(f"  ⚠️  kg-store: 迁移实体失败 '{name}': {e}", file=sys.stderr)

    # 迁移关系
    for rel in relations:
        try:
            src = c.execute("SELECT id FROM entities WHERE name=?", (rel["source"],)).fetchone()
            tgt = c.execute("SELECT id FROM entities WHERE name=?", (rel["target"],)).fetchone()
            if src and tgt:
                c.execute("""
                    INSERT OR IGNORE INTO relations (source_id, target_id, type, description, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    src["id"], tgt["id"],
                    rel.get("type", "related_to"),
                    rel.get("description", ""),
                    rel.get("first_seen", datetime.now().isoformat()),
                    rel.get("last_seen", datetime.now().isoformat()),
                ))
            elif not src:
                _print_migrate_error("关系迁移: 源实体不存在", rel.get("source", "?"))
            elif not tgt:
                _print_migrate_error("关系迁移: 目标实体不存在", rel.get("target", "?"))
        except Exception as e:
            _print_migrate_error("关系迁移失败", str(e)[:100])

    # 迁移笔记关联
    for note_path, names in note_entities.items():
        for name in names:
            try:
                eid = c.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
                if eid:
                    c.execute("""
                        INSERT OR IGNORE INTO entity_notes (entity_id, note_path, occurrences, last_seen)
                        VALUES (?, ?, 1, ?)
                    """, (eid["id"], note_path, datetime.now().isoformat()))
            except Exception as e:
                _print_migrate_error("笔记关联迁移失败", f"{note_path}:{name} {str(e)[:100]}")

    # 迁移统计
    last_extract = stats.get("last_extract_time")
    c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
              ("schema_version", "2.0"))
    if last_extract:
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                  ("last_extract_time", last_extract))

    c.commit()
    print(f"  ✅ kg-store: 从 JSON 迁移 {migrated_count} 实体 → SQLite", file=sys.stderr)


# ── 内部辅助 ──────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()


def _entity_name_to_id(name: str) -> Optional[int]:
    """实体名称 → ID。返回 None 如不存在。"""
    row = _get_conn().execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
    return row["id"] if row else None


def _row_to_entity(row) -> dict:
    """sqlite3.Row → 标准实体 dict"""
    return {
        "name": row["name"],
        "type": row["type"],
        "domain": row["domain"] or "",
        "description": row["description"] or "",
        "aliases": json.loads(row["aliases"]) if row["aliases"] else [],
        "first_seen": row["first_seen"] or "",
        "last_seen": row["last_seen"] or "",
    }


def _row_to_relation(row) -> dict:
    """sqlite3.Row → 标准关系 dict"""
    return {
        "id": row["id"],
        "source": row["source"],
        "target": row["target"],
        "type": row["type"],
        "description": row["description"] or "",
        "first_seen": row["first_seen"] or "",
        "last_seen": row["last_seen"] or "",
    }


# ── 公开 API ──────────────────────────────────────────

def upsert_entity(name: str, etype: str, domain: str = "",
                  description: str = "", aliases: Optional[list] = None) -> dict:
    """插入或更新实体。返回实体 dict。"""
    if not name or not name.strip():
        return {}
    name = name.strip()
    if not valid_entity_type(etype):
        return {}

    c = _get_conn()
    now = _now()
    aliases_json = json.dumps(aliases or [], ensure_ascii=False)

    existing = c.execute("SELECT * FROM entities WHERE name=?", (name,)).fetchone()
    if existing:
        update_fields = ["last_seen=?"]
        params = [now]
        if description and not existing["description"]:
            update_fields.append("description=?")
            params.append(description)
        if aliases:
            # Merge aliases
            old_aliases = set(json.loads(existing["aliases"]) if existing["aliases"] else [])
            old_aliases.update(aliases)
            update_fields.append("aliases=?")
            params.append(json.dumps(list(old_aliases), ensure_ascii=False))
        if domain and not existing["domain"]:
            update_fields.append("domain=?")
            params.append(domain)
        params.append(name)
        c.execute(f"UPDATE entities SET {', '.join(update_fields)} WHERE name=?", params)
    else:
        c.execute("""
            INSERT INTO entities (name, type, domain, description, aliases, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, etype, domain, description, aliases_json, now, now))

    c.commit()
    row = c.execute("SELECT * FROM entities WHERE name=?", (name,)).fetchone()
    return _row_to_entity(row) if row else {}


def add_entity_note(name: str, note_path: str, count: int = 1):
    """将笔记关联到实体"""
    if not name or not note_path:
        return
    eid = _entity_name_to_id(name)
    if eid is None:
        return
    c = _get_conn()
    c.execute("""
        INSERT INTO entity_notes (entity_id, note_path, occurrences, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(entity_id, note_path) DO UPDATE SET
            occurrences = occurrences + ?,
            last_seen = ?
    """, (eid, note_path, count, _now(), count, _now()))
    c.commit()


def add_relation(source: str, target: str, rtype: str,
                 description: str = "") -> bool:
    """添加关系（幂等）。返回是否新增。"""
    if not valid_relation_type(rtype):
        return False
    src_id = _entity_name_to_id(source)
    tgt_id = _entity_name_to_id(target)
    if src_id is None or tgt_id is None:
        return False

    c = _get_conn()
    existing = c.execute(
        "SELECT id FROM relations WHERE source_id=? AND target_id=? AND type=?",
        (src_id, tgt_id, rtype)
    ).fetchone()

    if existing:
        c.execute("UPDATE relations SET last_seen=?, description=CASE WHEN description='' THEN ? ELSE description END WHERE id=?",
                  (_now(), description, existing["id"]))
        c.commit()
        return False

    c.execute("""
        INSERT INTO relations (source_id, target_id, type, description, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (src_id, tgt_id, rtype, description, _now(), _now()))
    c.commit()
    return True


def batch_store(entities: list, relations: list, note_path: str):
    """批量存储一个笔记的所有实体+关系"""
    for ent in entities:
        upsert_entity(
            name=ent.get("name", ""),
            etype=ent.get("type", ""),
            domain=ent.get("domain", ""),
            description=ent.get("description", ""),
            aliases=ent.get("aliases", []),
        )
        add_entity_note(ent.get("name", ""), note_path)

    for rel in relations:
        add_relation(
            source=rel.get("source", ""),
            target=rel.get("target", ""),
            rtype=rel.get("type", ""),
            description=rel.get("description", ""),
        )

    c = _get_conn()
    c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
              ("last_extract_time", _now()))
    c.commit()


def get_notes_for_entity(entity_name: str) -> list:
    """获取引用了某实体的所有笔记路径

    返回: [{"note_path": str, "occurrences": int, "last_seen": str}, ...]
    """
    c = _get_conn()
    rows = c.execute("""
        SELECT en.note_path, en.occurrences, en.last_seen
        FROM entity_notes en
        JOIN entities e ON en.entity_id = e.id
        WHERE e.name = ?
        ORDER BY en.occurrences DESC
    """, (entity_name,)).fetchall()
    return [dict(r) for r in rows]


def _print_migrate_error(msg: str, detail: str = ""):
    """日志辅助：迁移错误"""
    print(f"  ⚠️  kg-store 迁移: {msg} {detail}".rstrip(), file=sys.stderr)


def get_entities_for_note(note_path: str) -> list:
    """获取某篇笔记的所有实体"""
    c = _get_conn()
    rows = c.execute("""
        SELECT e.* FROM entities e
        JOIN entity_notes en ON e.id = en.entity_id
        WHERE en.note_path = ?
        ORDER BY e.name
    """, (note_path,)).fetchall()
    return [_row_to_entity(r) for r in rows]


def search_entities(query: str, limit: int = 10) -> list:
    """按名称/别名搜索实体"""
    q = query.lower().strip()
    if not q:
        return []
    c = _get_conn()
    # 搜索名称
    rows = c.execute("""
        SELECT * FROM entities
        WHERE LOWER(name) LIKE ? OR LOWER(aliases) LIKE ?
        ORDER BY name
        LIMIT ?
    """, (f"%{q}%", f"%{q}%", limit)).fetchall()
    return [_row_to_entity(r) for r in rows]


def get_related_entities(name: str, max_depth: int = 1) -> dict:
    """获取与某实体相关的实体+关系图

    返回: {"nodes": [entity, ...], "edges": [relation_with_names, ...]}
    """
    c = _get_conn()
    eid = _entity_name_to_id(name)
    if eid is None:
        return {"nodes": [], "edges": []}

    # 获取直接关系
    rows = c.execute("""
        SELECT r.id, r.type, r.description, r.first_seen, r.last_seen,
               s.name AS source, t.name AS target
        FROM relations r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
        WHERE r.source_id = ? OR r.target_id = ?
    """, (eid, eid)).fetchall()

    related_names = set()
    edges = []
    for r in rows:
        rel = _row_to_relation(r)
        edges.append(rel)
        if rel["source"] == name:
            related_names.add(rel["target"])
        else:
            related_names.add(rel["source"])

    # 获取相关实体详情
    if related_names:
        placeholders = ",".join("?" for _ in related_names)
        node_rows = c.execute(f"SELECT * FROM entities WHERE name IN ({placeholders})",
                              list(related_names)).fetchall()
        nodes = [_row_to_entity(r) for r in node_rows]
    else:
        nodes = []

    return {"nodes": nodes, "edges": edges}


def find_path(source_name: str, target_name: str, max_depth: int = 5) -> list:
    """查找两个实体之间的路径（BFS）

    返回: [[path1], [path2], ...] 每条路径是 (entity_name, relation_type) 交替的列表
    例如: [("CK瓶颈因子", "is_a"), ("瓶颈因子", "related_to"), ...]
    """
    if max_depth < 1 or not source_name or not target_name:
        return []
    if source_name == target_name:
        return [[(source_name, "self")]]

    c = _get_conn()
    src_id = _entity_name_to_id(source_name)
    tgt_id = _entity_name_to_id(target_name)
    if src_id is None or tgt_id is None:
        return []

    # BFS: (current_id, [path])
    from collections import deque
    visited = {src_id}
    queue = deque([(src_id, [])])

    # Preload all relations for speed
    all_rels = c.execute("""
        SELECT r.source_id, r.target_id, r.type, s.name AS sn, t.name AS tn
        FROM relations r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
    """).fetchall()

    # Build adjacency list
    adj = defaultdict(list)
    for r in all_rels:
        adj[r["source_id"]].append((r["target_id"], r["type"], r["tn"]))
        adj[r["target_id"]].append((r["source_id"], r["type"], r["sn"]))

    paths = []
    while queue and len(paths) < 5:
        cur, path = queue.popleft()
        depth = len(path) // 2  # Each step has (entity, relation)

        if cur == tgt_id:
            # Build named path
            named_path = [(source_name, "start")]
            for step in path:
                named_path.append((step[1], step[0]))  # (target_name, relation_type)
            paths.append(named_path)
            continue

        if depth >= max_depth:
            continue

        for neighbor, rel_type, neighbor_name in adj.get(cur, []):
            if neighbor not in visited:  # 不重复访问避免环路
                visited.add(neighbor)
                queue.append((neighbor, path + [(rel_type, neighbor_name)]))

    return paths


def merge_entities(canonical_name: str, alias_names: list) -> dict:
    """合并同义实体：将所有 alias 的关系/笔记关联转移到 canonical

    返回: canonical 实体 dict
    """
    if not canonical_name or not alias_names:
        return get_all_entities().get(canonical_name, {})

    c = _get_conn()
    canonical_id = _entity_name_to_id(canonical_name)

    # 如果 canonical 不存在，用第一个 alias 的数据创建
    if canonical_id is None:
        for alias in alias_names:
            aid = _entity_name_to_id(alias)
            if aid:
                row = c.execute("SELECT * FROM entities WHERE id=?", (aid,)).fetchone()
                # 用 alias 的数据创建 canonical
                upsert_entity(
                    name=canonical_name,
                    etype=row["type"],
                    domain=row["domain"],
                    description=row["description"],
                    aliases=json.loads(row["aliases"]) if row["aliases"] else [],
                )
                canonical_id = _entity_name_to_id(canonical_name)
                break
        if canonical_id is None:
            return {}  # 没有可合并的数据

    merged_aliases = set()
    for alias in alias_names:
        aid = _entity_name_to_id(alias)
        if aid is None or aid == canonical_id:
            continue

        # 转移关系
        c.execute("UPDATE relations SET source_id=? WHERE source_id=? AND source_id!=?",
                  (canonical_id, aid, canonical_id))
        c.execute("UPDATE relations SET target_id=? WHERE target_id=? AND target_id!=?",
                  (canonical_id, aid, canonical_id))

        # 转移笔记关联
        c.execute("""
            INSERT INTO entity_notes (entity_id, note_path, occurrences, last_seen)
            SELECT ?, note_path, occurrences, last_seen FROM entity_notes WHERE entity_id=?
            ON CONFLICT(entity_id, note_path) DO UPDATE SET
                occurrences = entity_notes.occurrences + excluded.occurrences
        """, (canonical_id, aid))

        # 收集别名
        alias_row = c.execute("SELECT aliases FROM entities WHERE id=?", (aid,)).fetchone()
        if alias_row and alias_row["aliases"]:
            merged_aliases.update(json.loads(alias_row["aliases"]))

        # 删除旧实体（清除所有残余关系）
        c.execute("DELETE FROM entity_notes WHERE entity_id=?", (aid,))
        c.execute("DELETE FROM relations WHERE source_id=? OR target_id=?", (aid, aid))
        c.execute("DELETE FROM entities WHERE id=?", (aid,))

    # 更新 canonical 的别名
    merged_aliases.update(alias_names)
    existing_aliases = set()
    cur = c.execute("SELECT aliases FROM entities WHERE id=?", (canonical_id,)).fetchone()
    if cur and cur["aliases"]:
        existing_aliases.update(json.loads(cur["aliases"]))
    merged_aliases.update(existing_aliases)
    c.execute("UPDATE entities SET aliases=? WHERE id=?",
              (json.dumps(list(merged_aliases), ensure_ascii=False), canonical_id))

    c.commit()
    row = c.execute("SELECT * FROM entities WHERE id=?", (canonical_id,)).fetchone()
    return _row_to_entity(row) if row else {}


def get_stats() -> dict:
    """获取存储统计"""
    c = _get_conn()
    total_entities = c.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    total_relations = c.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    notes_with_entities = c.execute("SELECT COUNT(DISTINCT note_path) FROM entity_notes").fetchone()[0]
    last_extract = c.execute("SELECT value FROM meta WHERE key='last_extract_time'").fetchone()
    return {
        "total_entities": total_entities,
        "total_relations": total_relations,
        "notes_with_entities": notes_with_entities,
        "last_extract_time": last_extract["value"] if last_extract else None,
    }


def get_all_entities() -> dict:
    """获取所有实体 dict (name -> entity_dict)"""
    c = _get_conn()
    rows = c.execute("SELECT * FROM entities ORDER BY name").fetchall()
    return {r["name"]: _row_to_entity(r) for r in rows}


def get_all_relations() -> list:
    """获取所有关系（带名称）"""
    c = _get_conn()
    rows = c.execute("""
        SELECT r.id, r.type, r.description, r.first_seen, r.last_seen,
               s.name AS source, t.name AS target
        FROM relations r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
        ORDER BY r.id
    """).fetchall()
    return [_row_to_relation(r) for r in rows]


def reset():
    """清空所有数据"""
    c = _get_conn()
    c.executescript("""
        DELETE FROM entity_notes;
        DELETE FROM relations;
        DELETE FROM entities;
        DELETE FROM meta;
    """)
    c.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("schema_version", "2.0"))
    c.commit()
    print("  ✅ kg-store: 已清空所有数据")


# ── CLI ────────────────────────────────────────────────

def _print_entity(e: dict):
    print(f"  [{e['type']}] {e['name']} — {e.get('description', '')} "
          f"{'(aliases: ' + ', '.join(e.get('aliases',[])) + ')' if e.get('aliases') else ''}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KG Store 管理工具 (SQLite)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("stats", help="显示存储统计")
    sub.add_parser("list", help="列出所有实体")
    sub.add_parser("reset", help="清空所有数据")

    p_search = sub.add_parser("search", help="搜索实体")
    p_search.add_argument("query", help="搜索关键词")

    p_related = sub.add_parser("related", help="查看实体的关联实体")
    p_related.add_argument("name", help="实体名称")

    p_path = sub.add_parser("path", help="查找两个实体之间的路径")
    p_path.add_argument("source", help="源实体")
    p_path.add_argument("target", help="目标实体")
    p_path.add_argument("--depth", type=int, default=5, help="最大搜索深度")

    p_merge = sub.add_parser("merge", help="合并同义实体")
    p_merge.add_argument("canonical", help="规范名称")
    p_merge.add_argument("aliases", nargs="+", help="要合并的别名")

    args = parser.parse_args()
    if args.cmd == "stats":
        s = get_stats()
        print(f"  实体数: {s['total_entities']}")
        print(f"  关系数: {s['total_relations']}")
        print(f"  已关联笔记: {s['notes_with_entities']}")
        print(f"  最后提取: {s.get('last_extract_time', '从未')}")
    elif args.cmd == "list":
        ents = get_all_entities()
        by_type = defaultdict(list)
        for n, e in sorted(ents.items()):
            by_type[e.get("type", "unknown")].append(n)
        for t, names in sorted(by_type.items()):
            print(f"\n  [{t}] ({len(names)}):")
            for n in names:
                print(f"    - {n}")
        print(f"\n  共计: {len(ents)} 实体, {len(get_all_relations())} 关系")
    elif args.cmd == "search":
        for e in search_entities(args.query):
            _print_entity(e)
    elif args.cmd == "related":
        g = get_related_entities(args.name)
        print(f"  `{args.name}` 的关联实体 ({len(g['nodes'])}个):")
        for n in g["nodes"]:
            print(f"    [{n.get('type','?')}] {n['name']} — {n.get('description','')}")
        print(f"  关系: {len(g['edges'])} 条")
        for e in g["edges"]:
            print(f"    {e['source']} --[{e['type']}]--> {e['target']}")
    elif args.cmd == "path":
        paths = find_path(args.source, args.target, args.depth)
        if paths:
            print(f"  `{args.source}` → `{args.target}` 找到 {len(paths)} 条路径:")
            for pi, p in enumerate(paths, 1):
                parts = []
                for step in p:
                    if step[1] == "start":
                        parts.append(f"[{step[0]}]")
                    else:
                        parts.append(f"--{step[1]}--> [{step[0]}]")
                print(f"  路径{pi}: {' '.join(parts)}")
        else:
            print(f"  ❌ `{args.source}` → `{args.target}` 无路径（max_depth={args.depth}）")
    elif args.cmd == "merge":
        result = merge_entities(args.canonical, args.aliases)
        if result:
            print(f"  ✅ 合并完成: {result['name']}")
            print(f"     类型: {result['type']}")
            print(f"     别名: {result.get('aliases', [])}")
        else:
            print(f"  ❌ 合并失败: 找不到可合并的实体")
    elif args.cmd == "reset":
        confirm = input("  确认清空所有数据? (yes/no): ")
        if confirm == "yes":
            reset()


if __name__ == "__main__":
    main()
