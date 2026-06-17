#!/usr/bin/env python3
"""skill_library.py — 技能库 (Skill Library)

借鉴 Voyager (Wang et al., 2023)，让 agent 不断发现新技能→存入技能库→复用。
论文证明技能库让探索效率提升 +340%。

用法:
  from skill_library import SkillLibrary, Skill, SkillStep

  # 注册技能
  SkillLibrary.register(Skill(
      name="ai-stock-research",
      description="AI算力链股票研究",
      steps=[SkillStep("macro", "评估{topic}的宏观环境")],
  ))

  # 检索技能
  skills = SkillLibrary.search("AI算力")
"""

import json, sys, re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── 存储路径 ──────────────────────────────────────────
CONFIG_DIR = Path.home() / ".hermes" / "profiles" / "ai-investor" / "config"
SKILLS_FILE = CONFIG_DIR / "agent_skills.json"


# ── 数据类 ────────────────────────────────────────────

@dataclass
class SkillStep:
    """技能中的一步"""
    agent_name: str
    goal_template: str
    context_template: str = ""
    output_key: str = ""


@dataclass
class Skill:
    """可复用的 agent 工作流片段"""
    name: str
    description: str
    steps: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    success_rate: float = 0.0
    usage_count: int = 0
    created_at: str = ""
    source: str = "manual"  # manual / auto_extracted

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if isinstance(self.steps, list) and self.steps and isinstance(self.steps[0], dict):
            self.steps = [SkillStep(**s) for s in self.steps]

    def to_plan(self, topic: str) -> list:
        """将技能转为 PM 规划中的 agent 任务列表"""
        tasks = []
        for step in self.steps:
            goal = step.goal_template.replace("{topic}", topic)
            context = step.context_template.replace("{topic}", topic) if step.context_template else ""
            tasks.append({
                "template_name": step.agent_name,
                "goal": goal,
                "context": context,
                "output_key": step.output_key,
            })
        return tasks


# ── 技能库 ────────────────────────────────────────────

class SkillLibrary:
    """技能库"""

    _skills: dict[str, Skill] = {}

    @classmethod
    def _load(cls):
        """从 JSON 加载技能"""
        if cls._skills:
            return
        if not SKILLS_FILE.exists():
            return
        try:
            data = json.loads(SKILLS_FILE.read_text(encoding="utf-8"))
            for name, item in data.items():
                cls._skills[name] = Skill(**item)
        except (json.JSONDecodeError, OSError):
            pass

    @classmethod
    def _save(cls):
        """原子写入技能文件"""
        SKILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {name: asdict(skill) for name, skill in cls._skills.items()}
        tmp = SKILLS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SKILLS_FILE)

    @classmethod
    def register(cls, skill: Skill) -> Skill:
        """注册技能（幂等，同名覆盖）"""
        cls._load()
        cls._skills[skill.name] = skill
        cls._save()
        return skill

    @classmethod
    def search(cls, query: str, top_k: int = 5) -> list:
        """搜索技能（名称+描述+标签 多字段匹配）"""
        cls._load()
        if not cls._skills:
            return []
        q = query.lower().strip()
        if not q:
            return list(cls._skills.values())[:top_k]

        scored = []
        for name, skill in cls._skills.items():
            score = 0
            # 名称匹配（权重 3）
            if q in name.lower():
                score += 3
            # 描述匹配（权重 2）
            if q in skill.description.lower():
                score += 2
            # 标签匹配（权重 2）
            for tag in skill.tags:
                if q in tag.lower():
                    score += 2
            # 步骤匹配（权重 1）
            for step in skill.steps:
                if q in step.agent_name.lower() or q in step.goal_template.lower():
                    score += 1
            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]

    # ── 语义搜索（P1-3 新增 2026-06-17） ────────────────────────

    _embedding_cache: dict[str, list[float]] = {}
    _skills_text_cache: dict[str, str] = {}

    @classmethod
    def _build_skill_text(cls, skill) -> str:
        parts = [skill.name, skill.description]
        parts.extend(skill.tags)
        for step in skill.steps:
            parts.append(step.agent_name)
            parts.append(step.goal_template)
        return " | ".join(p for p in parts if p)

    @classmethod
    def _get_embedding(cls, text: str) -> list:
        cache_key = text[:200]
        if cache_key in cls._embedding_cache:
            return cls._embedding_cache[cache_key]
        import os
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        if not api_key:
            return []
        try:
            import urllib.request, json as _json
            url = "https://api.minimax.chat/v1/embeddings"
            payload = _json.dumps({"model": "embo-01", "texts": [text]}).encode("utf-8")
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
                if "vectors" in data and data["vectors"]:
                    emb = data["vectors"][0]
                    cls._embedding_cache[cache_key] = emb
                    return emb
        except Exception:
            pass
        return []

    @classmethod
    def _cosine_similarity(cls, a: list, b: list) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    @classmethod
    def search_semantic(cls, query: str, top_k: int = 5) -> list:
        cls._load()
        if not cls._skills:
            return []
        query_emb = cls._get_embedding(query)
        if query_emb:
            scored = []
            for name, skill in cls._skills.items():
                skill_text = cls._build_skill_text(skill)
                skill_emb = cls._get_embedding(skill_text[:500])
                if skill_emb:
                    sim = cls._cosine_similarity(query_emb, skill_emb)
                    if sim > 0.3:
                        scored.append((sim, skill))
            if scored:
                scored.sort(key=lambda x: -x[0])
                return [s for _, s in scored[:top_k]]
        return cls.search(query, top_k=top_k)

    @classmethod
    def get(cls, name: str) -> Optional[Skill]:
        """获取指定技能"""
        cls._load()
        return cls._skills.get(name)

    @classmethod
    def list_all(cls) -> list:
        """列出所有技能"""
        cls._load()
        return list(cls._skills.values())

    @classmethod
    def delete(cls, name: str) -> bool:
        """删除技能"""
        cls._load()
        if name not in cls._skills:
            return False
        del cls._skills[name]
        cls._save()
        return True

    @classmethod
    def extract_from_history(cls, max_skills: int = 3) -> list:
        """从 PM Agent 执行历史中自动提取技能"""
        cls._load()
        exp_path = CONFIG_DIR / "research_experience.json"
        if not exp_path.exists():
            return []

        try:
            experiences = json.loads(exp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        # 找成功的研究
        successful = [e for e in experiences if e.get("success_count", 0) > 0]
        extracted = []

        for exp in successful[-max_skills:]:
            topic = exp.get("topic", "未知")
            # 从 topic 生成技能名
            name = f"auto_{topic[:20].replace(' ', '_')}"

            if name in cls._skills:
                continue  # 已存在

            skill = Skill(
                name=name,
                description=f"自动提取: {topic}",
                steps=[
                    SkillStep("macro", f"评估{topic}的宏观环境"),
                    SkillStep("industry", f"扫描{topic}所在行业"),
                    SkillStep("screening", f"对{topic}进行多维度初筛"),
                ],
                tags=[topic[:10]],
                source="auto_extracted",
            )
            cls._skills[name] = skill
            extracted.append(skill)

        if extracted:
            cls._save()

        return extracted

    @classmethod
    def clear(cls):
        """清空所有技能（测试用）"""
        cls._skills.clear()


# ── 内置技能注册 ──────────────────────────────────────

def register_builtin_skills():
    """注册内置技能（2 → 12）"""
    SkillLibrary.register(Skill(
        name="ai-stock-research",
        description="AI算力链股票研究 — 宏观→行业→初筛→CK因子→深度→风控",
        steps=[
            SkillStep("macro", "评估{topic}的宏观环境"),
            SkillStep("industry", "扫描{topic}所在行业"),
            SkillStep("screening", "对{topic}进行多维度初筛"),
            SkillStep("ck_factor", "计算{topic}的CK瓶颈因子"),
            SkillStep("deep", "撰写{topic}的深度研究报告"),
            SkillStep("risk", "对{topic}进行风控审核"),
        ],
        tags=["AI算力", "股票研究", "光模块", "半导体"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="macro-sentiment-screening",
        description="宏观→情绪→初筛 — 快速评估股票",
        steps=[
            SkillStep("macro", "评估{topic}的宏观环境"),
            SkillStep("sentiment", "分析{topic}的市场情绪"),
            SkillStep("screening", "对{topic}进行多维度初筛"),
        ],
        tags=["快速评估", "宏观", "情绪"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="deep-research-with-debate",
        description="深度研究+多空辩论 — 初筛→CK→深度→辩论→风控",
        steps=[
            SkillStep("screening", "对{topic}进行多维度初筛"),
            SkillStep("ck_factor", "计算{topic}的CK瓶颈因子"),
            SkillStep("deep", "撰写{topic}的深度研究报告"),
            SkillStep("debate", "组织关于{topic}的多空辩论"),
            SkillStep("risk", "对{topic}进行风控审核"),
        ],
        tags=["深度研究", "辩论", "多空"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="macro-industry-quick-scan",
        description="宏观+行业快速扫描 — 了解大环境再聚焦行业",
        steps=[
            SkillStep("macro", "评估{topic}的宏观环境"),
            SkillStep("industry", "扫描{topic}所在行业"),
            SkillStep("sentiment", "分析{topic}的市场情绪"),
        ],
        tags=["宏观", "行业", "快速扫描"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="full-river-standard",
        description="标准河流全流程 — 10 agent 完整研究",
        steps=[
            SkillStep("macro", "评估{topic}的宏观环境"),
            SkillStep("industry", "扫描{topic}所在行业"),
            SkillStep("sentiment", "分析{topic}的市场情绪"),
            SkillStep("screening", "对{topic}进行多维度初筛"),
            SkillStep("ck_factor", "计算{topic}的CK瓶颈因子"),
            SkillStep("cross_validate", "对{topic}进行交叉验证"),
            SkillStep("deep", "撰写{topic}的深度研究报告"),
            SkillStep("debate", "组织关于{topic}的多空辩论"),
            SkillStep("model_panel", "组织关于{topic}的模型辩论"),
            SkillStep("risk", "对{topic}进行风控审核"),
        ],
        tags=["全流程", "标准", "河流"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="ck-factor-deep-dive",
        description="CK 因子深度拆解 — 专注瓶颈因子分析",
        steps=[
            SkillStep("screening", "对{topic}进行多维度初筛"),
            SkillStep("ck_factor", "计算{topic}的CK瓶颈因子"),
            SkillStep("deep", "撰写{topic}的CK因子深度报告"),
        ],
        tags=["CK因子", "瓶颈", "深度"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="risk-first-assessment",
        description="风控优先评估 — 先看风险再决定是否深入研究",
        steps=[
            SkillStep("macro", "评估{topic}的宏观风险"),
            SkillStep("sentiment", "分析{topic}的市场情绪风险"),
            SkillStep("screening", "对{topic}进行多维度初筛"),
            SkillStep("risk", "对{topic}进行风控审核"),
        ],
        tags=["风控", "风险评估", "保守"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="groupchat-debate-only",
        description="纯辩论模式 — 多空双方+评审，不执行其他分析",
        steps=[
            SkillStep("macro", "提供{topic}的宏观背景"),
            SkillStep("sentiment", "提供{topic}的市场情绪"),
            SkillStep("bull", "从多方角度分析{topic}"),
            SkillStep("bear", "从空方角度分析{topic}"),
            SkillStep("judge", "评审关于{topic}的多空辩论"),
        ],
        tags=["辩论", "多空", "评审"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="code-review-workflow",
        description="代码审查流程 — 审查→分析→风控",
        steps=[
            SkillStep("code-reviewer", "审查{topic}的代码质量"),
            SkillStep("analyst", "分析{topic}的业务影响"),
            SkillStep("risk", "评估{topic}的技术风险"),
        ],
        tags=["代码审查", "技术", "质量"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="cross-validate-fact-check",
        description="交叉验证+事实核查 — 多源数据验证关键信息",
        steps=[
            SkillStep("screening", "收集{topic}的关键数据"),
            SkillStep("cross_validate", "对{topic}进行多源交叉验证"),
            SkillStep("sentiment", "分析{topic}的市场情绪一致性"),
        ],
        tags=["交叉验证", "事实核查", "数据"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="model-panel-ensemble",
        description="多模型集成分析 — 多个模型对同一问题分别分析后综合",
        steps=[
            SkillStep("screening", "收集{topic}的基础数据"),
            SkillStep("model_panel", "组织多个模型分析{topic}"),
            SkillStep("risk", "综合评估{topic}的风险"),
        ],
        tags=["多模型", "集成", "ensemble"],
        source="manual",
    ))
    SkillLibrary.register(Skill(
        name="pm-agent-research",
        description="PM Agent 完整研究 — 规划→执行→沉淀全流程",
        steps=[
            SkillStep("macro", "评估{topic}的宏观环境"),
            SkillStep("industry", "扫描{topic}所在行业"),
            SkillStep("screening", "对{topic}进行多维度初筛"),
            SkillStep("ck_factor", "计算{topic}的CK瓶颈因子"),
            SkillStep("deep", "撰写{topic}的深度研究报告"),
            SkillStep("debate", "组织关于{topic}的多空辩论"),
            SkillStep("risk", "对{topic}进行风控审核"),
        ],
        tags=["PM", "全流程", "研究"],
        source="manual",
    ))


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="技能库管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有技能")
    sub.add_parser("register-builtin", help="注册内置技能")

    p_search = sub.add_parser("search", help="搜索技能")
    p_search.add_argument("query", help="搜索关键词")

    p_extract = sub.add_parser("extract", help="从历史自动提取技能")

    args = parser.parse_args()

    if args.cmd == "list":
        skills = SkillLibrary.list_all()
        if not skills:
            print("📭 无已注册技能")
        else:
            print(f"📋 技能库 ({len(skills)}):")
            for s in skills:
                steps = ", ".join(st.agent_name for st in s.steps)
                tags = " ".join(f"#{t}" for t in s.tags)
                print(f"  [{s.name}] {s.description}")
                print(f"     步骤: {steps}")
                print(f"     标签: {tags} | 成功率: {s.success_rate:.0%} | 使用: {s.usage_count}次")

    elif args.cmd == "register-builtin":
        register_builtin_skills()
        print(f"✅ 内置技能已注册 ({len(SkillLibrary.list_all())} 个)")

    elif args.cmd == "search":
        results = SkillLibrary.search(args.query)
        if not results:
            print(f"❌ 无匹配技能: {args.query}")
        else:
            print(f"🔍 搜索 '{args.query}' → {len(results)} 个匹配:")
            for s in results:
                steps = ", ".join(st.agent_name for st in s.steps)
                print(f"  [{s.name}] {s.description}")
                print(f"     步骤: {steps}")

    elif args.cmd == "extract":
        extracted = SkillLibrary.extract_from_history()
        if extracted:
            print(f"✅ 自动提取 {len(extracted)} 个技能:")
            for s in extracted:
                print(f"  [{s.name}] {s.description}")
        else:
            print("⏭️  无可提取的技能（无成功历史）")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
