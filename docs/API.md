# KMS Engine API 文档

> 版本: v5.0 | 更新: 2026-06-17
> 35+ 脚本 | 10 项核心能力 | 105 测试

---

## 一、核心入口：kms.py

统一 CLI 入口，通过 `python3 scripts/kms.py <子命令>` 调用。

### 子命令一览

| 子命令 | 说明 | 示例 |
|:-------|:-----|:------|
| `search <query>` | wiki 全文检索 | `kms search 资金因子 --fusion` |
| `link` | 更新双向链接 | `kms link` |
| `health [--parallel]` | 健康检查（并行加速） | `kms health --parallel` |
| `validate <笔记>` | 多视角验证 | `kms validate xxx.md` |
| `pipeline <笔记> [--skip]` | 内容流水线 | `kms pipeline xxx.md --skip enrich` |
| `analytics [--days N]` | 使用分析 | `kms analytics --days 30` |
| `react <agent> <goal>` | ReAct Agent | `kms react router "查资金因子"` |
| `status` | 系统状态+会话上下文 | `kms status` |
| `gate <笔记>` | 写入门禁 | `kms gate xxx.md` |
| `fuse` | 智能融合 | `kms smart-fuse` |
| `kg <子命令>` | 知识图谱 | `kms kg search 资金因子` |
| `score <笔记>` | AI 评分 | `kms score xxx.md` |
| `enrich <笔记>` | 背景富化 | `kms enrich xxx.md` |
| `index <子命令>` | 索引管理 | `kms index build` |
| `cleanup` | 清理缓存 | `kms cleanup` |

---

## 二、意图路由 (kms_router.py)

### IntentRouter

```
IntentRouter()
  .resolve(text: str) → (intent, skill, args)
  .help() → str
```

| 参数 | 类型 | 说明 |
|:-----|:-----|:------|
| `text` | str | 自然语言输入 |
| 返回 | tuple | `(intent, skill, args)` — 匹配失败返回 `(None, None, None)` |

**支持 12 种意图**：search / health / gate / link / kg / fuse / status / backup / index / score / validate / analytics

---

## 三、编排引擎 (kms_orchestrator.py)

### TaskOrchestrator

```
TaskOrchestrator(max_workers=6)
  .run(tasks: list[TaskDef]) → dict[str, Any]
  .visualize(tasks: list[TaskDef]) → str (Mermaid)
```

### TaskDef

```python
@dataclass
class TaskDef:
    name: str           # 任务名称
    func: Callable      # 执行函数
    deps: list[str]     # 依赖列表（默认 [])
    args: tuple         # 位置参数
    kwargs: dict        # 关键字参数
```

---

## 四、多视角验证 (kms_validator.py)

### 验证函数

| 函数 | 说明 | 返回 |
|:-----|:------|:------|
| `check_quality(note_path)` | frontmatter/字数/链接 | `{verdict, detail, issues}` |
| `check_fusion(note_path)` | smart_fuse 重叠检测 | `{verdict, detail, candidates}` |
| `check_entity(note_path)` | KG 实体抽取 | `{verdict, detail, entities}` |
| `check_governance(note_path)` | 断裂链接检测 | `{verdict, detail, broken_links}` |
| `validate(note_path)` | 四路并行+裁决回写 | `{verdict, checks}` |
| `read_issues(note_path)` | 读取历史 issues | `list[dict]` |
| `write_verdict(note_path, verdict, checks)` | 裁决回写 frontmatter | `None` |

### 裁决等级

| 等级 | 含义 | 操作 |
|:-----|:------|:------|
| `PASS` | 全部通过 | 继续流程 |
| `CONDITIONAL` | 有警告 | 回写 frontmatter，下次验证跳过已修复项 |
| `FAIL` | 有阻塞问题 | 阻止发布，需修复后重试 |

---

## 五、内容流水线 (kms_pipeline.py)

### 6 阶段

```python
PHASES = [
    ("validate", "VALIDATE", "4 路并行验证"),
    ("fuse",     "FUSE",     "smart_fuse 融合检查"),
    ("link",     "LINK",     "kms link 更新链接"),
    ("enrich",   "ENRICH",   "KG 实体抽取"),
    ("review",   "REVIEW",   "quality_gate 打分"),
    ("publish",  "PUBLISH",  "归档确认 + 清理"),
]
```

### run_pipeline()

```python
run_pipeline(note_path: str, skip: set = None, resume: bool = False)
```

| 参数 | 类型 | 说明 |
|:-----|:-----|:------|
| `note_path` | str | 笔记文件路径 |
| `skip` | set | 要跳过的阶段名 |
| `resume` | bool | 从中断处恢复 |

---

## 六、ReAct Agent (kms_react.py)

### ReActAgent（基类）

```python
class ReActAgent:
    def __init__(self, name: str, max_steps: int = 5)
    def observe(self, state: dict) -> str       # 观察状态
    def think(self, state: dict) -> Optional[str] # 思考下一步
    def act(self, action: str, state: dict) -> dict # 执行
    def validate(self, action, result, state) -> dict # 验证结果
    def fallback(self, action, result, state) -> Optional[dict] # 降级
    def run(self, goal: str, state: dict = None) -> dict  # ReAct 循环
```

### 5 个 Agent

| Agent | 类 | 步数 | 核心循环 |
|:------|:---|:----:|:---------|
| **Router** | `ReActRouter` | 2-3 | 复合意图→多步工具链 |
| **Validator** | `ReActValidator` | 3-4 | 动态选验证维度 |
| **Pipeline** | `ReActPipeline` | 3-4 | 动态编排阶段 |
| **Enricher** | `ReActEnricher` | 3 | analyze→search→append |
| **Reviewer** | `ReActReviewer` | 2-3 | score→suggest/report |

---

## 七、安全守卫 (kms_guard.py)

### 检测函数

```python
scan(note_path: str) -> list[dict]
  # 返回: [{"pattern": "API Key", "line": 42, "preview": "..."}]

fix(note_path: str) -> int
  # 返回: 替换数量
```

### 检测模式（6 种）

| 模式 | 正则 | 示例 |
|:-----|:------|:------|
| API Key | `sk-[a-zA-Z0-9]{20,}` | `sk-xxx...` |
| GitHub Token | `ghp_[a-zA-Z0-9]{36}` | `ghp_xxx...` |
| GitHub OAuth | `gho_[a-zA-Z0-9]{36}` | `gho_xxx...` |
| Slack Token | `xox[baprs]-...` | `xoxb-xxx...` |
| AWS Key | `AKIA[0-9A-Z]{16}` | `AKIAxxx...` |
| Private Key | `-----BEGIN ... PRIVATE KEY-----` | RSA/EC 私钥 |
| JWT | `eyJ[a-zA-Z0-9_-]+\.eyJ...` | JWT Token |

---

## 八、使用分析 (kms_analytics.py)

### UsageTracker

```python
UsageTracker()
  .log_command(command, detail=None, duration=None)
  .log_search(keyword, result_count=0)
  .report(days=7) → dict
```

### 报告结构

```python
{
    "period_days": 7,
    "total_commands": 42,
    "total_searches": 15,
    "top_commands": [{"command": "search", "count": 10, "avg_duration": 0.3}],
    "top_keywords": [{"keyword": "资金因子", "count": 3}],
}
```

---

## 九、会话记忆 (kms_session.py)

### 核心函数

```python
record_search(keyword: str)         # 记录搜索
record_command()                    # 记录命令
record_note(note_name: str)         # 记录笔记
record_health(checks: int, issues: int) # 记录健康检查
get_context() → str                 # 获取上下文摘要
load_portrait() → dict              # 加载用户画像
```

### 用户画像结构

```python
{
    "interests": ["AI工程化", "多因子量化", "知识管理", ...],
    "has_portrait": True,
}
```

---

## 十、每日晨报 (kms_daily_report.py)

### 核心函数

```python
fetch_arxiv_rss() → list[dict]      # ArXiv AI 论文
fetch_github_trending() → list[dict] # GitHub 热榜
check_stale(days=30) → list[dict]    # stale 笔记检测
build_report() → dict                # 生成完整报告
format_report(report) → str          # 格式化
```

### 报告结构

```python
{
    "date": "2026-06-17 08:30",
    "stale": {"count": 0, "items": [...]},
    "health": {"files": "371", "orphan": "105", ...},
    "usage": {"total_commands": 5, ...},
    "fetched": {"arxiv": [...], "github": [...]},
    "summary": "🔗 断裂292 | 📄 孤岛105",
}
```

---

## 十一、路径配置 (_path_setup.py)

所有脚本通过 `from _path_setup import ...` 获取路径。

### 可用路径

| 变量 | 路径 |
|:-----|:------|
| `KMS_ROOT` | `kms-engine/` |
| `SCRIPTS_DIR` | `kms-engine/scripts/` |
| `CONFIG_DIR` | `kms-engine/config/` |
| `TEMPLATES_DIR` | `kms-engine/templates/` |
| `WIKI_DIR` | `wiki-AIGC-KB/` |
| `OUTPUT_DIR` | `输出/` |
| `IE_DIR` | `investment-engine/` |

---

## 十二、测试 (tests/)

| 文件 | 数量 | 说明 |
|:-----|:----:|:------|
| `test_kms_react.py` | 17 | ReAct Agent 框架测试 |
| `test_kms_coverage.py` | 27 | 新功能全覆盖测试 |
| `test_health.py` | — | 健康检查测试 |
| `test_kms.py` | — | KMS 核心功能测试 |
| `test_write_gate.py` | — | 写入门禁测试 |
| `test_checkpoint_utils.py` | — | Checkpoint 测试 |
| `test_p4_pipeline.py` | — | Pipeline 测试 |

---

## 十三、自然语言入口

所有功能可通过 `kms "自然语言"` 调用：

| 你说 | 执行 |
|:-----|:------|
| `kms "查资金因子"` | `kms search --fusion 资金因子` |
| `kms "看看wiki健康"` | `kms health --parallel` |
| `kms "验证笔记 xxx.md"` | `kms validate xxx.md` |
| `kms "使用报告"` | `kms analytics --days 7` |
| `kms "智能路由查资金因子"` | ReAct Router 循环 |
| `kms "智能验证笔记"` | ReAct Validator |
| `kms "并行健康检查"` | `kms health --parallel` |
| `kms "更新链接"` | `kms link` |
