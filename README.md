# KMS Engine — 个人知识管理系统

> 将零散笔记转化为互联的知识网络，AI驱动的知识图谱 + 语义搜索

---

## 是什么

KMS Engine 是一个**个人知识管理（PKM）系统**，核心目标不是「存笔记」，而是**让知识可发现、可关联、可推理**。

它做了三件事：

1. **自动抽取知识实体** — 你写笔记，系统自动提取其中的概念、人物、公司、因子等实体
2. **构建语义知识图谱** — 实体之间的关系自动建立起可查询的知识网络
3. **智能搜索** — 关键词 + 向量 + 知识图谱 → 结果排序更准

---

## 核心功能

| 功能 | 命令 | 说明 |
|:-----|:-----|:-----|
| 知识图谱搜索 | `kms search <词> --fusion` | KG+RRF 融合搜索，结果带实体增强 |
| 实体关系查询 | `kms kg related <实体名>` | 查看一个实体的所有关联实体和关系 |
| 路径推理 | `kms kg path <源> <目标>` | 查找两个实体之间的关联路径（BFS） |
| 实体合并 | `kms kg merge <规范名> <别名...>` | 合并同义实体（如"资金因子v4"→"资金因子"） |
| 笔记实体抽取 | `kms kg extract <笔记.md>` | 从笔记正文中提取实体和关系 |
| 全库扫描 | `kms kg scan` | 增量扫描全库，提取实体（跳过已处理的） |
| 一键归档 | `kms insight-capture finalize <笔记路径>` | 归档时自动完成实体抽取 |
| Wiki 治理 | `python scripts/wiki_audit.py` | 检测冗余、归类异常、大文件 |
| 健康检查 | `kms health` | 6维健康检查（断裂链接/frontmatter/空壳等） |

---

## 快速开始

```bash
# 环境要求
pip install -r requirements.txt

# 查看系统状态
python scripts/kms.py status

# 搜索笔记（关键词）
python scripts/kms.py search <关键词>

# 搜索笔记（KG+RRF融合）
python scripts/kms.py search <关键词> --fusion

# 查看知识图谱统计
python scripts/kms.py kg stats

# 全库扫描实体抽取
python scripts/kms.py kg scan

# 知识图谱路径查询
python scripts/kms.py kg path <源实体> <目标实体>
```

---

## 架构

```
┌─────────────────────────────────────────────┐
│ Layer 3: 用户接口                            │
│  kms CLI / insight_capture finalize          │
├─────────────────────────────────────────────┤
│ Layer 2: 实体抽取层                           │
│  kg_extract.py → LLM (DeepSeek V4 Flash)     │
│                 → JSON 提取 + 重试(2次)       │
├─────────────────────────────────────────────┤
│ Layer 1: 存储+查询层 (SQLite)                  │
│  kg_store.py                                  │
│  ├── entities (845+ 实体, 8种类型)             │
│  ├── relations (1460+ 关系, 6种类型)           │
│  ├── find_path — BFS路径搜索                   │
│  ├── merge_entities — 同义实体合并              │
│  └── search_entities — 名称/别名搜索            │
├─────────────────────────────────────────────┤
│ Layer 0: RRF 搜索引擎                          │
│  kms.db — FTS5 + MiniMax Embedding 1536d     │
│          → RRF k=60 融合                      │
└─────────────────────────────────────────────┘
```

### 知识图谱实体类型

| 类型 | 说明 | 示例 |
|:-----|:-----|:-----|
| `concept` | 核心概念 | 安全边际、RRF混合搜索 |
| `person` | 人物 | Andrej Karpathy、Tiago Forte |
| `company` | 公司/机构 | OpenAI、DeepSeek、中际旭创 |
| `factor` | 投资因子 | 资金流因子、CK瓶颈因子 |
| `indicator` | 指标/度量 | IC值、PE分位数、RSI |
| `method` | 方法/框架 | Zettelkasten、PARA、RRF |
| `tool` | 工具/系统 | Obsidian、MiniMax、Hermes |
| `domain` | 领域/学科 | 知识管理、量化投资、AI工程 |

### 关系类型

`is_a` · `part_of` · `uses` · `related_to` · `influences` · `contrasts_with`

---

## 关键命令速查

```bash
# 检索
kms search <词>                         # 关键词搜索
kms search <词> --rrf                   # RRF 混合搜索
kms search <词> --fusion                # KG+RRF 融合搜索（推荐）

# 知识图谱
kms kg stats                            # 图谱统计
kms kg search <词>                      # 搜索实体
kms kg related <实体名>                  # 实体关联图
kms kg path <源> <目标>                  # 实体路径
kms kg extract <笔记.md>                 # 提取实体
kms kg merge <规范名> <别名...>          # 合并同义实体
kms kg scan                             # 全库扫描

# 系统维护
kms health                              # 健康检查
kms index build                         # 构建RRF索引
kms link                                # 更新链接
kms insight-capture finalize <路径>      # 一键归档

# Wiki 治理
python scripts/wiki_audit.py            # 治理报告
python scripts/wiki_deep_scan.py        # 深度扫描
```

---

## 数据指标（当前）

| 指标 | 数值 |
|:-----|:----:|
| 笔记总数 | 285+ |
| 知识图谱实体 | 1,409 |
| 知识图谱关系 | 1,462 |
| 已关联笔记 | 228 |
| 实体类型 | 8 种 |
| 关系类型 | 6 种 |

---

## 技术栈

- **Python 3.11+** — 核心语言
- **SQLite + WAL** — 知识图谱存储（零依赖）
- **DeepSeek V4 Flash** — 实体抽取 LLM
- **MiniMax Embedding (1536d)** — 向量检索
- **SQLite FTS5** — 全文检索
- **RRF (k=60)** — 混合搜索融合算法

---

## 相关项目

- [`wiki-AIGC-KB`](https://github.com/) — 知识库内容（Markdown 笔记）
- [`investment-engine`](https://github.com/) — 投资因子引擎

---

> ⚠️ 本系统为个人知识管理设计，不构成任何投资建议。
