# 因子研究笔记模板 v4（11节结构）

> 模板路径: `kms-engine/templates/factor-note-v4.md`
> 参考示例: `08-investment/04-因子研究/capital-flow.md` (760行)
> 对应 Hermes skill: `factor-note-template`

## 元数据（frontmatter）

```yaml
---
title: "因子名称：核心设计"
factor: factor-name
type: factor-study
domain: 因子研究
tags:
  - 标签1
  - 标签2
created: YYYY-MM-DD
updated: YYYY-MM-DD-vN
related_factors: [['因子A', '因子B']]
---
```

## 01 | 架构总览
维度评分表 + cap + 信号融合

## 02 | 核心认知
3-5 条一句话原则

## 03 | 原理：为什么有效
行为金融学/经济学基础

## 04 | 业界做法：当前实现与行业差距
对比表，已实现的 ✅，未实现的 ❌

## 05 | 学术前沿：必读论文
论文标题 + 「对因子的启示」

## 06 | 发现问题
每条：问题描述 🔴/🟠 → 修复 → 影响

## 07 | 完整代码精读
逐段代码，每段先讲「为什么」再贴代码

## 08 | 开发流水线
ARCH REVIEW → ENGINE → FINAL REVIEW

## 09 | 待解答的问题
待 pipeline 验证的假设

## 10 | 数据字段确认
API 字段名速查

## 11 | 关联因子
[[link]] 交叉引用
