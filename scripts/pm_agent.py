#!/usr/bin/env python3
"""pm_agent.py — AI 项目经理驱动 Multi-Agent 研究

借鉴小红书「AI当PM指导Multi-agent做研究」范式。
三层流程：PM 规划 → DAG 执行 → 经验沉淀

用法:
  python pm_agent.py research "分析中际旭创"           # 完整研究流程
  python pm_agent.py plan "分析中际旭创"               # 仅规划
  python pm_agent.py reflect                           # 查看经验沉淀
"""

import json, sys, os, uuid
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import list_templates, run_template

# ── 配置 ──────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".hermes" / "profiles" / "ai-investor" / "config"
EXPERIENCE_FILE = CONFIG_DIR / "research_experience.json"
PLANS_DIR = CONFIG_DIR / "research_plans"
PLANS_DIR.mkdir(parents=True, exist_ok=True)


# ── 数据类 ────────────────────────────────────────────

@dataclass
class AgentTask:
    """单个 agent 的任务定义"""
    template_name: str
    goal: str
    context: str = ""
    toolsets: list = None
    output_requirements: str = "结构化输出"
    acceptance_criteria: list = None

    def __post_init__(self):
        if self.toolsets is None:
            self.toolsets = []
        if self.acceptance_criteria is None:
            self.acceptance_criteria = ["数据可验证", "来源可查", "逻辑清晰"]


@dataclass
class ResearchPlan:
    """PM Agent 输出的研究方案"""
    topic: str
    goal: str
    quality_standards: list = None
    agents: list = None
    created_at: str = ""
    acceptance_criteria: list = None

    def __post_init__(self):
        if self.quality_standards is None:
            self.quality_standards = ["信息来源可查", "数据可验证", "逻辑清晰"]
        if self.agents is None:
            self.agents = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if self.acceptance_criteria is None:
            self.acceptance_criteria = [
                "所有数据来源可追溯",
                "关键数据点至少两个独立信源交叉验证",
                "逻辑链完整无断裂",
                "结论有数据支撑",
            ]


# ── PM 系统提示词 ─────────────────────────────────────

def _build_pm_prompt(topic: str, context: str) -> str:
    """构建 PM Agent 的系统提示词"""
    templates = list_templates()
    agents_str = "\n".join(
        f"  - {t['name']}: {t['description']} (toolsets: {', '.join(t['toolsets'])})"
        for t in templates
    )

    return f"""你是一个专业的研究项目经理 (Research PM)。
你的职责是：给定一个研究主题，设计一个多 Agent 协作研究方案。

## 可用 Agent 模板

{agents_str}

## 你的工作流程

1. **理解研究目标** — 分析研究主题，明确范围、深度和产出要求
2. **选择 Agent** — 从以上模板中选择合适的组合（通常 3-8 个）
3. **定制每个 Agent 的任务** — 为每个选中的 Agent 定制：
   - 定制化的研究目标（与总目标对齐）
   - 定制化的上下文（前置研究结果）
   - 输出要求
   - 验收标准
4. **定义质量标准** — 信息来源可查、数据可验证、逻辑清晰
5. **输出研究方案** — JSON 格式

## 设计原则

- 每个 Agent 的上下文要精简，不超过其需要的信息
- 考虑依赖关系：前置 Agent 的输出是后置 Agent 的输入
- 过程文档必须留存到本地文件
- 验收标准必须明确、可检查

## 输出格式

请只返回 JSON，不要包含任何其他文字：
{{
  "goal": "研究目标描述",
  "quality_standards": ["标准1", "标准2"],
  "acceptance_criteria": ["验收1", "验收2"],
  "agents": [
    {{
      "template_name": "macro",
      "goal": "定制化的研究目标",
      "context": "定制化的上下文",
      "output_requirements": "输出要求",
      "acceptance_criteria": ["验收标准"]
    }}
  ]
}}

研究主题: {topic}
额外上下文: {context}
"""


# ── PM 规划 ───────────────────────────────────────────

def plan_research(topic: str, context: str = "") -> ResearchPlan:
    """PM Agent 规划研究方案（支持动态组队）"""
    print(f"  📋 PM 正在设计研究方案...", end="", flush=True)

    # 1. 检索技能库
    try:
        from skill_library import SkillLibrary
        skills = SkillLibrary.search(topic, top_k=1)
        if skills:
            skill = skills[0]
            tasks = skill.to_plan(topic)
            agents = []
            for t in tasks:
                agents.append(AgentTask(
                    template_name=t["template_name"],
                    goal=t["goal"],
                    context=t["context"],
                ))
            plan = ResearchPlan(topic=topic, goal=skill.description, agents=agents)
            print(f" ✅ 匹配技能「{skill.name}」({len(agents)} agent)")
            return plan
    except ImportError:
        pass

    # 2. 无技能匹配 → 动态组队
    prompt = _build_pm_prompt(topic, context)

    # 调用 LLM 生成规划（通过 litellm）
    try:
        from litellm import completion
        import os as _os
        resp = completion(
            model=_os.environ.get("PM_MODEL", "deepseek/deepseek-v4-flash"),
            messages=[
                {"role": "system", "content": "你是一个专业的研究项目经理。请只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            api_key=_os.environ.get("DEEPSEEK_PRO_API_KEY", ""),
            api_base="https://api.deepseek.com",
            temperature=0.3,
            max_tokens=4096,
        )
        raw = resp.choices[0].message.content.strip()
    except Exception as e:
        print(f" ❌ LLM 调用失败: {e}")
        # 降级：返回默认规划
        return _default_plan(topic, context)

    # 解析 JSON
    import re
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        print(" ❌ JSON 解析失败，使用默认规划")
        return _default_plan(topic, context)

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        print(" ❌ JSON 解析失败，使用默认规划")
        return _default_plan(topic, context)

    # 构建 Plan
    agents = []
    dynamic_created = []
    for a in data.get("agents", []):
        template_name = a.get("template_name", "macro")
        # 检查是否是动态模板（模板不存在时自动创建）
        from agent_template import get_template, create_dynamic_template
        if not get_template(template_name):
            # 动态创建
            dyn_prompt = a.get("system_prompt", a.get("context", f"你是一个{topic}领域的专业分析师。"))
            dyn_tools = a.get("toolsets", ["web"])
            create_dynamic_template(
                name=template_name,
                system_prompt=dyn_prompt,
                toolsets=dyn_tools,
                description=a.get("description", f"{topic}专用分析agent"),
            )
            dynamic_created.append(template_name)
        agents.append(AgentTask(
            template_name=template_name,
            goal=a.get("goal", topic),
            context=a.get("context", ""),
            output_requirements=a.get("output_requirements", "结构化输出"),
            acceptance_criteria=a.get("acceptance_criteria",
                                       ["数据可验证", "来源可查", "逻辑清晰"]),
        ))

    plan = ResearchPlan(
        topic=topic,
        goal=data.get("goal", topic),
        quality_standards=data.get("quality_standards", ["信息来源可查"]),
        agents=agents,
        acceptance_criteria=data.get("acceptance_criteria",
                                      ["数据来源可追溯", "交叉验证", "逻辑完整"]),
    )

    # 保存规划文档
    plan_path = PLANS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{topic[:20]}.json"
    plan_path.write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2),
                         encoding="utf-8")

    print(f" ✅ {len(agents)} 个 agent")
    return plan


def _default_plan(topic: str, context: str = "") -> ResearchPlan:
    """降级：默认研究方案（使用所有可用 agent）"""
    templates = list_templates()
    agents = []
    for t in templates:
        agents.append(AgentTask(
            template_name=t["name"],
            goal=f"研究 {topic} 的 {t['description']}",
            context=context,
        ))
    return ResearchPlan(
        topic=topic,
        goal=f"全面研究 {topic}",
        agents=agents,
    )


# ── Interview Mode ────────────────────────────────────

def _interview_mode():
    """对话式目标生成 — AI 采访用户 → 自动生成 ResearchPlan → 执行"""
    print(f"\n{'='*55}")
    print(f"  💬 Interview Mode — 我来问你几个问题")
    print(f"{'='*55}\n")

    questions = [
        ("research_topic", "你想研究什么主题或股票？"),
        ("focus", "关注哪些方面？（基本面/技术面/估值/宏观/行业/全部）"),
        ("timeframe", "时间范围或上下文？（如2026年Q2、近期）"),
        ("constraints", "有什么特殊要求或约束？"),
        ("output", "期望的输出形式？（简要分析/完整报告/辩论总结）"),
    ]

    answers = {}
    for key, question in questions:
        print(f"  🤖 {question}")
        try:
            ans = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  ⏹️  已取消")
            return
        answers[key] = ans if ans else "无"

    topic = answers["research_topic"]
    context = (
        f"关注方面: {answers['focus']}；"
        f"时间范围: {answers['timeframe']}；"
        f"约束: {answers['constraints']}；"
        f"输出形式: {answers['output']}"
    )

    print(f"\n{'='*55}")
    print(f"  ✅ 已收集信息，正在生成研究方案...")
    print(f"{'='*55}\n")

    pm_research(topic, context)


# ── DAG 执行 ──────────────────────────────────────────

def execute_plan(plan: ResearchPlan, verbose: bool = True) -> dict:
    """按规划执行研究方案"""
    results = {}
    total = len(plan.agents)

    if verbose:
        print(f"\n{'='*55}")
        print(f"  🚀 执行研究方案 — {len(plan.agents)} 个 agent")
        print(f"{'='*55}\n")

    for i, task in enumerate(plan.agents, 1):
        if verbose:
            print(f"  [{i}/{total}] 🚀 {task.template_name}...", end="", flush=True)

        try:
            session = run_template(
                task.template_name,
                goal=task.goal,
                context=task.context,
                toolsets_override=task.toolsets if task.toolsets else None,
            )
            results[task.template_name] = session
            if verbose:
                status = session.status if hasattr(session, "status") else "unknown"
                if status == "success":
                    print(f" ✅")
                else:
                    err = getattr(session, "error", "")[:50]
                    print(f" ❌ {err}")
        except Exception as e:
            if verbose:
                print(f" ❌ {e}")
            results[task.template_name] = {"status": "failed", "error": str(e)}

    if verbose:
        success = sum(1 for r in results.values()
                      if hasattr(r, "status") and r.status == "success")
        print(f"\n  ✅ 完成: {success}/{total} 成功")

    return results


# ── 经验沉淀 ──────────────────────────────────────────

def reflect(topic: str, plan: ResearchPlan, results: dict) -> str:
    """分析执行经验，写入经验文档"""
    # 收集经验
    experience = {
        "topic": topic,
        "timestamp": datetime.now().isoformat(),
        "agent_count": len(plan.agents),
        "success_count": sum(
            1 for r in results.values()
            if hasattr(r, "status") and r.status == "success"
        ),
        "failed_agents": [
            name for name, r in results.items()
            if hasattr(r, "status") and r.status == "failed"
        ],
        "acceptance_criteria": plan.acceptance_criteria,
    }

    # 追加到经验文件
    experiences = []
    if EXPERIENCE_FILE.exists():
        try:
            experiences = json.loads(EXPERIENCE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            experiences = []

    experiences.append(experience)
    tmp = EXPERIENCE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(experiences, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(EXPERIENCE_FILE)

    return str(EXPERIENCE_FILE)


# ── 主入口 ────────────────────────────────────────────

def pm_research(topic: str, context: str = "") -> dict:
    """完整的研究流程：PM 规划 → DAG 执行 → 经验沉淀"""
    print(f"\n{'='*55}")
    print(f"  🎯 PM Agent 研究 — {topic}")
    print(f"{'='*55}")

    # Step 1: PM 规划
    print(f"\n📋 Phase 1: PM 规划")
    plan = plan_research(topic, context)

    # Step 2: DAG 执行
    print(f"\n🚀 Phase 2: DAG 执行")
    results = execute_plan(plan)

    # Step 3: 经验沉淀
    print(f"\n📝 Phase 3: 经验沉淀")
    exp_path = reflect(topic, plan, results)
    print(f"  经验已保存: {exp_path}")

    print(f"\n{'='*55}")
    print(f"  ✅ 研究完成")
    print(f"{'='*55}")

    return {
        "plan": plan,
        "results": results,
        "experience_path": exp_path,
    }


# ── CLI ───────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PM Agent — AI 项目经理")
    sub = parser.add_subparsers(dest="cmd")

    # research
    p_res = sub.add_parser("research", help="完整研究流程")
    p_res.add_argument("topic", help="研究主题")
    p_res.add_argument("--context", default="", help="额外上下文")

    # plan
    p_plan = sub.add_parser("plan", help="仅规划")
    p_plan.add_argument("topic", help="研究主题")
    p_plan.add_argument("--context", default="")

    # reflect
    sub.add_parser("reflect", help="查看经验沉淀")

    # interview
    sub.add_parser("interview", help="对话式目标生成 — AI采访你，自动生成研究方案")

    args = parser.parse_args()

    if args.cmd == "research":
        pm_research(args.topic, args.context)

    elif args.cmd == "plan":
        plan = plan_research(args.topic, args.context)
        print(f"\n📋 研究方案:")
        print(f"  目标: {plan.goal}")
        print(f"  Agent: {len(plan.agents)} 个")
        for a in plan.agents:
            print(f"    [{a.template_name}] {a.goal[:60]}...")
        print(f"  验收标准: {plan.acceptance_criteria}")

    elif args.cmd == "interview":
        _interview_mode()

    elif args.cmd == "reflect":
        if EXPERIENCE_FILE.exists():
            experiences = json.loads(EXPERIENCE_FILE.read_text(encoding="utf-8"))
            print(f"📋 研究经验 ({len(experiences)} 条):")
            for exp in experiences[-5:]:
                print(f"  [{exp['timestamp'][:16]}] {exp['topic'][:40]}...")
                print(f"    {exp['success_count']}/{exp['agent_count']} agent 成功")
                if exp["failed_agents"]:
                    print(f"    失败: {', '.join(exp['failed_agents'])}")
        else:
            print("📭 尚无研究经验")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
