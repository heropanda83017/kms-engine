# KMS Engine — 个人知识管理系统

> 第二大脑，自进化知识库。35+ 脚本，78+ 测试，10 项核心能力。

---

## 能力全景

### 🎯 一键直达

| 你说 | 执行 |
|:-----|:------|
| `kms "查资金因子"` | 意图路由 → `kms search --fusion 资金因子` |
| `kms "看看wiki健康"` | 意图路由 → `kms health --parallel` |
| `kms "验证笔记 xxx.md"` | 意图路由 → `kms validate xxx.md` |
| `kms "使用报告"` | 意图路由 → `kms analytics` |
| `kms "智能路由查资金因子"` | ReAct Router → 思考→行动→观察循环 |

### 🤖 ReAct Agent（5个）

| Agent | 步数 | 循环逻辑 |
|:------|:----:|:---------|
| **Router** | 2-3 | 复合意图理解 → 多步工具链（真实调kms search/health/validate等） |
| **Validator** | 3-4 | 根据笔记大小动态选验证维度（质量/融合/实体/治理） |
| **Pipeline** | 3-4 | 根据frontmatter/字数动态编排阶段（validate→fuse→guard→link） |
| **Enricher** | 3 | analyze→search→append 自动富化背景信息 |
| **Reviewer** | 2-3 | score→suggest/report→report 质量打分+改进建议 |

### 📋 核心功能

| 功能 | 说明 |
|:-----|:------|
| **意图路由** | 12种意图自然语言→命令，无需记忆CLI参数 |
| **并行编排** | DAG拓扑排序+ThreadPoolExecutor，6路健康检查~1.8x加速 |
| **多视角验证** | 4路并行：质量(frontmatter/字数/链接) + 融合(smart_fuse) + 实体(KG) + 治理(断裂链接) |
| **内容流水线** | 6阶段：validate→fuse→link→enrich→review→publish + checkpoint中断恢复 |
| **使用分析** | SQLite追踪搜索关键词和命令执行，支持 `` 报告 |
| **会话记忆** | JSON持久化跨会话上下文——最近搜索/笔记/健康检查/命令数 |
| **安全守卫** | 6种敏感模式：API Key / GitHub Token / JWT / Private Key / AWS Key / Slack Token |
| **每日晨报** | cron 08:30自动运行：ArXiv RSS抓取 + stale检测 + 健康快照 + 使用统计 + 微信推送 |
| **用户画像** | 4维度结构化画像（兴趣/风格/决策/信源），集成到status/search/daily-report |
| **反馈回流** | validate裁决自动回写笔记frontmatter，已修复的issue下次不再告警 |
| **流水线目录** | 5层结构：01-raw→02-process→03-output→04-system |

### 📈 数据对比

| 指标 | v4.0 | v5.0 |
|:-----|:----:|:----:|
| 脚本数 | 25+ | 35+ |
| 测试数 | 61 | 78+ |
| ReAct Agent | 0 | 5 |
| 自动抓取信源 | 0 | 1 (ArXiv) |
| 用户画像 | ❌ | ✅ |

---

## 🛠 安装

```bash
git clone https://github.com/heropanda83017/kms-engine.git
cd kms-engine
pip install -r requirements.txt
```

## 📁 文件结构

```
kms-engine/
├── scripts/            35+命令 (kms.py 统一入口)
│   ├── kms_router.py        意图路由(12种自然语言→命令)
│   ├── kms_orchestrator.py  并行编排引擎(拓扑排序+线程池)
│   ├── kms_validator.py     4路笔记验证+反馈回写frontmatter
│   ├── kms_pipeline.py      6阶段内容流水线+checkpoint
│   ├── kms_analytics.py     SQLite使用分析追踪
│   ├── kms_session.py       跨会话记忆+用户画像
│   ├── kms_guard.py         敏感信息检测(6种模式)
│   ├── kms_react.py         ReAct Agent(5个: Router/Validator/Pipeline/Enricher/Reviewer)
│   ├── kms_daily_report.py  每日晨报(ArXiv RSS+stale+健康+推送)
│   └── ... (25+原有脚本)
├── config/             配置文件
├── templates/          笔记模板
└── tests/              78+测试
```

## 📜 更新日志

| 日期 | 版本 | 内容 |
|:-----|:----|:------|
| 2026-06-17 | v5.0 | ReAct 5 Agent + 自动抓取ArXiv + 用户画像 + 反馈回流 + ECC体系优化 |
| 2026-06-15 | v4.3 | 7项体系升级：Intent Router / Orchestrator / Validator / Pipeline / Analytics / Session / Guard |
