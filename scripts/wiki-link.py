#!/usr/bin/env python3
"""
wiki-link.py — wiki 新内容与旧内容的双向链接生成
用法: python wiki-link.py                      # 自动扫描新内容并链接
      python wiki-link.py --rebuild             # 重建 wiki 索引
      python wiki-link.py --check               # 只检查不修改

集成到 kms sync: 自动在同步后调用
"""

import os, sys, re, json
from pathlib import Path

import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, REGISTRY
WIKI = WIKI_DIR

# 增量扫描: 只处理 mtime 变化的文件
import os, time
MTIME_CACHE = WIKI / ".wiki_mtime_cache.json"

def _get_changed_files():
    """返回自上次扫描后修改的文件列表"""
    cache = {}
    if MTIME_CACHE.exists():
        cache = json.loads(MTIME_CACHE.read_text(encoding="utf-8"))
    
    changed = []
    for f in WIKI.rglob("*.md"):
        if ".obsidian" in str(f):
            continue
        rel = str(f.relative_to(WIKI))
        mtime = f.stat().st_mtime
        if rel not in cache or cache[rel] != mtime:
            changed.append(f)
            cache[rel] = mtime
    
    return changed


def _save_cache(cache: dict):
    """写入 mtime 缓存——必须在注入成功后调用"""
    MTIME_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def build_registry():
    """构建/重建 wiki 内容索引"""
    registry = {}
    for f in sorted(WIKI.rglob("*.md")):
        if '.obsidian' in str(f):
            continue
        rel = str(f.relative_to(WIKI)).replace('\\', '/')
        content = f.read_text(encoding='utf-8', errors='ignore')
        title_m = re.search(r'^# (.+)$', content, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else f.stem
        sections = re.findall(r'^##? (.+)$', content, re.MULTILINE)
        dir_path = str(f.parent.relative_to(WIKI)) if f.parent != WIKI else ''
        registry[rel] = {
            'title': title, 'sections': sections, 'dir': dir_path,
            'has_links': '### 🔗 相关阅读' in content,
        }
    with open(REGISTRY, 'w', encoding='utf-8') as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    return registry


def classify(content_rel, title):
    """判断内容类型"""
    if '晓辉博士' in content_rel or '晓辉' in content_rel:
        return '🎬'
    if '研报' in content_rel:
        return '📊'
    if '见解' in content_rel:
        return '💡'
    if '图谱' in content_rel:
        return '🔗'
    if '框架' in content_rel:
        return '🏗️'
    return '📄'


def guess_group(old_rel):
    """判断旧内容的分组"""
    if '08-investment' in old_rel:
        if any(kw in old_rel for kw in ['芯片', '英伟达', '个股', 'HBM', '光模块']):
            return '🏗️ 算力基建'
        return '📈 投资视角'
    if '03-core' in old_rel:
        return '🧠 算法模型'
    if '06-reading' in old_rel:
        return '📚 读书笔记'
    if '07-practice' in old_rel:
        return '🔧 实践'
    if '04-tools' in old_rel:
        return '🔧 工具'
    return '📚 其他'


# 新内容关键词规则
MATCH_RULES = [
    (['Anthropic', 'OpenAI', 'Karpathy', '马斯克', 'xAI'], '🏗️ 算力基建'),
    (['Scaling', 'Law', 'HBM', '数据中心', 'GPU', '算力', '芯片', '瓶颈'], '🏗️ 算力基建'),
    (['HBM', '海力士', '三星', '美光', '存储', '半导体'], '🏗️ 算力基建'),
    (['光模块', '旭创', '新易盛', '天孚通信', '数通'], '🏗️ 算力基建'),
    (['资本开支', '折旧', '投资风险', '现金'], '📈 投资视角'),
]


def find_related(new_rel, new_title, registry):
    """为新内容找到相关的旧内容"""
    # 确定搜索关键词
    search_kws = []
    for kw_list, _ in MATCH_RULES:
        if any(kw.lower() in new_title.lower() or kw.lower() in new_rel.lower() for kw in kw_list):
            search_kws.extend(kw_list)
    if not search_kws:
        return {}
    
    related = {}
    for old_rel, old_info in registry.items():
        if old_rel == new_rel:
            continue
        for kw in search_kws:
            if kw.lower() in old_rel.lower() or kw.lower() in old_info['title'].lower():
                group = guess_group(old_rel)
                if group not in related:
                    related[group] = []
                related[group].append((old_rel, old_info['title']))
                break
    
    # 每组只保留3个
    for group in related:
        related[group] = related[group][:3]
    return related


def inject_links(new_rel, related, ntype):
    """为新人内容注入链接区块，同时反向链接到旧内容"""
    new_path = WIKI / new_rel
    new_content = new_path.read_text(encoding='utf-8')
    new_title = re.search(r'^# (.+)$', new_content, re.MULTILINE)
    new_title = new_title.group(1).strip() if new_title else ''
    
    # 构建链接区块
    lines = ["", "---", f"### 🔗 相关阅读", f"> {ntype} **{new_title[:30]}** 与知识库其他内容的关联导航", ""]
    
    has_links = False
    all_refs = []
    for group, items in related.items():
        if not items:
            continue
        has_links = True
        lines.append(f"**{group}**  ")
        link_items = []
        for old_rel, old_title in items:
            # 计算相对路径
            base_dir = Path(new_rel).parent
            try:
                rel_path = os.path.relpath(WIKI / old_rel, WIKI / base_dir).replace('\\', '/')
            except (OSError, AttributeError):
                rel_path = old_rel
            short = old_title[:20]
            link_items.append(f"[{short}]({rel_path})")
            all_refs.append((old_rel, ntype, new_title[:25], new_rel))
        lines.append(" | ".join(link_items) + "")
        lines.append("")
    
    if not has_links:
        return False
    
    # 阅读建议
    if all_refs:
        first_three = all_refs[:3]
        lines.append("💡 **建议阅读：** 先看本篇 → " + " → ".join([f"[{r[2]}]({r[3]})" for r in first_three]) + "")
    
    # 写入新页面
    new_content += '\n'.join(lines)
    new_path.write_text(new_content, encoding='utf-8')
    print(f"  ✅ 注入链接: {new_rel.split('/')[-1][:45]}")
    
    # 为旧页面添加反向链接
    for old_rel, src_type, src_title, src_path in all_refs:
        old_path = WIKI / old_rel
        if not old_path.exists():
            continue
        old_content = old_path.read_text(encoding='utf-8', errors='ignore')
        bl = f"- {src_type} [{src_title}]({src_path})"
        if bl in old_content:
            continue
        if '### ← 被新内容引用' not in old_content:
            old_content += '\n\n---\n### ← 被新内容引用\n'
        old_content += bl + '\n'
        old_path.write_text(old_content, encoding='utf-8')
        print(f"    ↪ 反向: {old_rel.split('/')[-1][:45]}")
    
    return True


def main():
    check_only = '--check' in sys.argv
    rebuild = '--rebuild' in sys.argv
    
    print("=" * 50)
    print("  wiki-link: wiki 跨链接生成")
    print("=" * 50)
    
    # 1. 构建索引
    print("\n[1/3] wiki 内容索引...")
    registry = build_registry()
    print(f"  ✅ {len(registry)} 个页面")
    
    # 2. 找到需要链接的新内容
    print("\n[2/3] 扫描新内容...")
    new_files = []
    for rel, info in sorted(registry.items()):
        if info['has_links']:
            continue
        # 判断是否为近期新增内容（通过文件名中的日期）
        if re.search(r'20\d{2}-\d{2}-\d{2}', rel):
            new_files.append(rel)
        # 或者包含关键词
        elif any(kw in info['title'] for kw in ['Anthropic', 'Scaling', 'HBM', '光模块', '图谱', '见解']):
            new_files.append(rel)
    
    if not new_files:
        print("  ⏭️ 没有需要链接的新内容")
        return
    
    print(f"  发现 {len(new_files)} 个新内容:")
    for rel in new_files:
        print(f"    📄 {rel.split('/')[-1]}")
    
    if check_only:
        print("\n⏭️ --check 模式，不修改")
        return
    
    # 3. 生成链接
    print("\n[3/3] 注入链接...")
    updated = 0
    for new_rel in new_files:
        new_path = WIKI / new_rel
        new_content = new_path.read_text(encoding='utf-8', errors='ignore')
        new_title = re.search(r'^# (.+)$', new_content, re.MULTILINE)
        new_title = new_title.group(1).strip() if new_title else ''
        ntype = classify(new_rel, new_title)
        related = find_related(new_rel, new_title, registry)
        if inject_links(new_rel, related, ntype):
            updated += 1
    
    print(f"\n✅ 更新完成: {updated} 个页面")


if __name__ == "__main__":
    main()
