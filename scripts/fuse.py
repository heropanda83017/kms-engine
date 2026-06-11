#!/usr/bin/env python3
"""
fuse.py — 笔记融合工具
将独立的见解、快速记录等碎片笔记合并到主体笔记中

用法: python fuse.py                          # 自动扫描并融合
      python fuse.py --check                  # 只检查，不修改
      python fuse.py <目标笔记.md>             # 指定融合到某篇笔记
"""

import os, sys, re, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, LEARNING_NOTES
WIKI = WIKI_DIR
LEARN = LEARNING_NOTES  # 输出/01-学习笔记，正确的见解存储路径


def find_insights():
    """找到所有待融合的碎片笔记"""
    insights = []
    
    # 01-学习笔记 中的个人见解
    insight_dir = LEARN / "个人见解"
    if insight_dir.exists():
        for f in insight_dir.glob("*.md"):
            if f.suffix == '.bak':
                continue
            insights.append(f)
    
    # wiki 中的独立见解文件
    for f in WIKI.rglob("见解_*.md"):
        insights.append(f)
    
    # 快速记录
    quick_dir = LEARN / "快速记录"
    if quick_dir.exists():
        for f in quick_dir.glob("*.md"):
            insights.append(f)
    
    return insights


def find_best_target(insight_path, content):
    """为见解找到最合适的主体笔记"""
    # 从内容中提取引用的笔记路径
    refs = re.findall(r'\]\((.+?)\)', content)
    
    for ref in refs:
        # 尝试解析相对路径
        candidates = [
            WIKI / ref,
            insight_path.parent / ref,
            WIKI / ref.replace('../', ''),
        ]
        for c in candidates:
            resolved = c.resolve()
            if resolved.exists() and resolved.suffix == '.md':
                return resolved
    
    # 没有引用链接，按关键词匹配
    title_m = re.search(r'^# (.+)$', content, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else ''
    
    # 提取关键词
    keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', title)
    for kw in keywords:
        for f in WIKI.rglob("*.md"):
            if '.obsidian' in str(f):
                continue
            if kw in f.stem:
                return f
    
    return None


def fuse_note(insight_path, target_path, check_only=False):
    """将见解融合到目标笔记"""
    insight_content = insight_path.read_text(encoding='utf-8', errors='ignore')
    target_content = target_path.read_text(encoding='utf-8', errors='ignore')
    
    # 提取见解正文（跳过 YAML 头和标题）
    body = []
    in_body = False
    for line in insight_content.split('\n'):
        if line.strip().startswith('---') and not in_body:
            continue
        if line.strip().startswith('---'):
            in_body = True
            continue
        if in_body:
            body.append(line)
    
    body_text = '\n'.join(body).strip()
    if not body_text:
        return False
    
    # 检查目标是否已包含此见解
    # 用见解的第一句话作为去重标识
    first_sentence = ''
    for line in body:
        line = line.strip()
        if len(line) > 10:
            first_sentence = line[:40]
            break
    
    if first_sentence and first_sentence in target_content:
        return False  # 已存在，跳过
    
    rel_path = os.path.relpath(insight_path, target_path.parent).replace('\\', '/')
    
    block = f"\n\n---\n## 个人见解\n\n{body_text}\n\n> 内容整合自 [{insight_path.name}]({rel_path})\n"
    
    if check_only:
        print(f"  📋 可融合: {insight_path.name} → {target_path.name}")
        return False
    
    target_content += block
    target_path.write_text(target_content, encoding='utf-8')
    
    # 备份原文件（防止误操作）
    bak_path = insight_path.with_suffix('.md.bak')
    shutil.move(str(insight_path), str(bak_path))
    
    print(f"  ✅ {insight_path.name[:35]:<35s} → 融合到 {target_path.name}")
    return True


def main():
    check_only = '--check' in sys.argv
    
    print("=" * 50)
    print("  笔记融合工具")
    print("=" * 50)
    
    # 指定模式
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        target_path = Path(sys.argv[1])
        if not target_path.exists():
            print(f"❌ 目标不存在: {target_path}")
            return
        insights = find_insights()
        print(f"\n目标: {target_path.name}")
        print(f"待融合碎片: {len(insights)} 个")
        
        count = 0
        for ip in insights:
            if fuse_note(ip, target_path, check_only):
                count += 1
        print(f"\n{'检查' if check_only else '融合'}完成: {count} 篇")
        return
    
    # 自动模式
    insights = find_insights()
    print(f"\n待融合碎片: {len(insights)} 个")
    
    if check_only:
        for ip in insights:
            content = ip.read_text(encoding='utf-8', errors='ignore')
            target = find_best_target(ip, content)
            if target:
                print(f"  📋 {ip.name[:35]:<35s} → {target.name}")
            else:
                print(f"  ⚠️ {ip.name[:35]:<35s} → 未找到合适目标")
        return
    
    merged = 0
    for ip in insights:
        content = ip.read_text(encoding='utf-8', errors='ignore')
        target = find_best_target(ip, content)
        if target:
            if fuse_note(ip, target):
                merged += 1
        else:
            print(f"  ⚠️ {ip.name[:35]:<35s} → 未找到合适目标")
    
    print(f"\n融合完成: {merged} 篇")
    if merged > 0:
        print(f"原文件已重命名为 .bak，确认后手动删除")


if __name__ == "__main__":
    main()
