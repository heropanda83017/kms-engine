# ARCH: 知识整合三层架构
> 生成: 2026-05-28 | 目标: 139篇零散笔记 → 互联知识网

## 现状
- wiki: 139篇笔记, 9个知识域, 双向链接已就位
- 缺少统一 frontmatter（无 type/domain/confidence 元数据）
- 缺少全局知识图谱导航页
- 新笔记写入时未标准化元数据

## 方案

### Layer 1 — 双向链接 (已就位 ✅)
wiki-link.py 增量扫描, 不做改动

### Layer 2 — 统一 Frontmatter (新增)
写入每篇笔记时注入标准 frontmatter:
```yaml
---
title: 笔记标题
type: research | insight | lecture | reference    # 笔记类型
domain: 算力产业链 | AI公司研究 | 投资方法 | ...   # 所属领域
tags: [关键词1, 关键词2]
source: 晓辉博士 | 研报 | 自研 | 其他             # 来源
confidence: high | medium | low                   # 置信度
created: 2026-05-28
updated: 2026-05-28
---
```

改动文件:
- archive_note.py — 归档时注入 frontmatter
- fill_note.py — 生成笔记时包含 frontmatter
- 新增 fix_frontmatter.py — 一次性回填 139篇已有笔记（基于内容自动推断）

### Layer 3 — 知识图谱导航 (新增)
新增 scripts/knowledge_graph.py:
- 扫描 wiki 所有笔记
- 按 domain 分组
- 按 type 分类 (research/insight/lecture/reference)
- 构建跨域交叉引用
- 输出 wiki/图谱索引.md

## 验收标准
1. fix_frontmatter.py 跑完后 wiki 每篇笔记都有标准 frontmatter
2. 无笔记因 frontmatter 注入导致内容损坏
3. knowledge_graph.py 输出 wiki/图谱索引.md
4. 图谱索引包含: 按域分组 + 类型分布 + 交叉引用
5. 全部 ast.parse ✅ + pytest 通过 ✅
6. V4 Pro FINAL REVIEW APPROVED
