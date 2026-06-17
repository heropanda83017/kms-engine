# KMS Engine — 个人知识管理系统

> 第二大脑 · 自进化知识库 · AI 驱动的知识图谱

---

## 概览

**KMS Engine** 是一个个人知识管理系统，基于语义搜索 + 知识图谱 + AI 辅助，帮你构建"第二大脑"。

| 指标 | 数据 |
|:-----|:-----|
| Python 脚本 | 35+ |
| 测试用例 | 78+ |
| 核心能力 | 10 项 |
| 数据存储 | SQLite + JSON + Markdown |

---

## 核心能力

### 📝 笔记管理
- `kms create` — 创建新笔记（自动选择目录）
- `kms search` — 全文检索 + 语义融合搜索 (RRF)
- `kms link` — 自动维护双向链接
- `kms score` — AI 质量打分 (0-10)
- `kms enrich` — 背景富化（补充搜索信息）
- `kms smart-fuse` — 智能融合（查找最佳融合目标）
- `kms validate` — 链接完整性验证

### 🧠 知识图谱
- `kms kg` — 知识图谱管理（实体抽取 + 关系构建）
- `kms resolve` — 三层技能架构路由解析

### 🤖 AI Agent
- **PM Agent** — 项目管理智能体
- **GroupChat** — 多 Agent 对话协作
- **TaskGraph** — DAG 任务编排
- **SkillLibrary** — 技能库管理
- **KG Graph Visual** — 知识图谱可视化
- **KG Image Gen** — 知识图谱图片生成
- **Agent Dashboard** — Agent 监控面板
- **Agent Protocol** — Agent 通信协议
- **Agent Sandbox** — Agent 沙盒环境
- **Agent Template** — Agent 模板系统

### 🔄 自动化
- `daily_brief` — 每日知识简报
- `delegate_retry_wrapper` — 带重试的任务委托
- `checkpoint_watchdog` — 检查点中断检测
- `kms health-daily/weekly` — 系统健康巡检

---

## 快速开始

```bash
# 查看系统状态
python3 scripts/kms_core.py status

# 搜索知识库
python3 scripts/kms_core.py search "机器学习" --fusion

# 创建新笔记
python3 scripts/kms_core.py create "笔记标题"

# 运行每日巡检
python3 scripts/kms_health_daily.py
```

---

## 架构

```
输入层                   处理层                   存储层
├── 手动创建             ├── AI 语义理解         ├── SQLite (kg.db)
├── 网页抓取             ├── 实体抽取            ├── JSON 注册表
├── 文档导入             ├── 关系构建            ├── Markdown wiki
├── API 接入             ├── 质量评分            └── 缓存 (cache/)
└── Agent 协作           └── 融合搜索
```

---

## 数据源

| 信源 | 状态 | 说明 |
|:-----|:------|:------|
| baostock | ✅ | A 股数据（对齐投资体系） |
| wiki-AIGC-KB | ✅ | 主知识库 |
| KMS 注册表 | ✅ | 模块索引 |

---

## 配置

`config/config.yaml` — 主要配置项：

```yaml
storage:
  kg_db: config/kg-store/kg.db    # 知识图谱数据库
  registry: config/.link_registry.json  # 链接注册表
search:
  mode: rrf                      # 融合搜索模式
  top_k: 10                      # 默认返回数
```

---

## 依赖

| 依赖 | 用途 |
|:-----|:------|
| Python 3.14+ | 运行环境 |
| sqlite3 | 知识图谱存储 |
| json | 注册表/配置 |
| re / pathlib | 文件操作 |

---

## 相关项目

- [investment-engine](https://github.com/heropanda83017/investment-engine) — A 股量化投资系统（共享数据源）
- [karpathy-llm-wiki](https://github.com/heropanda83017/karpathy-llm-wiki) — Wiki 维护技能
- [book-note-maker](https://github.com/heropanda83017/book-note-maker) — 读书笔记技能
- [meeting-minutes](https://github.com/heropanda83017/meeting-minutes) — 公文排版技能

---

> 本系统仅供个人学习研究使用。
