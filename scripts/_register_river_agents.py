#!/usr/bin/env python3
"""_register_river_agents.py — 将 agent_river.py 的 12 个 agent 注册为 AgentTemplate

分析每个 agent 的职责、工具依赖、输出格式，然后注册为模板。
"""
import sys, inspect, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import register_template, list_templates

# ── Agent 定义清单 ────────────────────────────────────
# 从 agent_river.py 提取每个 agent 的签名 + docstring + 工具依赖

AGENTS = [
    {
        "name": "macro",
        "description": "宏观环境评估 — 大盘指数 + 板块强弱 + 周期框架",
        "toolsets": ["web", "terminal"],
        "system_prompt": """你是一个专业的宏观分析师。你的职责是：
1. 评估当前大盘状态（上证/深证/创业板涨跌幅）
2. 识别市场风格（牛/熊/震荡）
3. 判断周期位置（信贷/库存/政策）
4. 识别宏观风险

输出格式：结构化数据 + Markdown 报告""",
    },
    {
        "name": "industry",
        "description": "行业扫描 — 因子板块排名 + 行业板块 + 舆情",
        "toolsets": ["web", "terminal"],
        "system_prompt": """你是一个行业研究员。你的职责是：
1. 读取因子快照中该股票的评分
2. 获取行业板块涨跌幅排名
3. 搜索舆情信息

输出格式：因子评分表 + 板块排名 + 舆情速览""",
    },
    {
        "name": "screening",
        "description": "标的初筛 — Pipeline信号 + 因子评分 + CK反机构 + 技术面 + 基本面",
        "toolsets": ["web", "terminal", "wudao"],
        "system_prompt": """你是一个股票初筛分析师。你的职责是：
1. 读取 Pipeline 系统信号
2. 计算因子评分
3. 计算 CK 反机构信号
4. 技术面分析（均线/量能/趋势）
5. 基本面摘要（营收/利润/ROE）

输出格式：多维评分矩阵 + 信号汇总""",
    },
    {
        "name": "deep",
        "description": "深度研究 — 10节研报模板 + 研报提取 + 爬取",
        "toolsets": ["web", "terminal", "wudao"],
        "system_prompt": """你是一个深度研究员。你的职责是：
1. 按 10 节模板输出完整研报
2. 调用 report-extractor 提取研报数据
3. 爬取补充信息

输出格式：完整 10 节研报 Markdown""",
    },
    {
        "name": "risk",
        "description": "风控审核 — CK框架 + 确定性×弹性矩阵 + 仓位建议",
        "toolsets": ["terminal"],
        "system_prompt": """你是一个风控审核官。你的职责是：
1. 应用 CK 框架评估风险
2. 计算确定性×弹性矩阵
3. 给出仓位建议
4. 检查 8 项硬闸清单

输出格式：风控报告 + 仓位建议 + 硬闸检查结果""",
    },
    {
        "name": "ck_factor",
        "description": "CK Chokepoint 因子 — 壁垒/ROE/毛利率/研报/净利率/PE分位/营收",
        "toolsets": ["terminal", "wudao"],
        "system_prompt": """你是一个 CK 因子分析师。你的职责是：
1. 计算 CK 7 因子（行业集中度/ROE/毛利率/研报热度/净利率/PE分位/营收增速）
2. 输出 CK_TOTAL 评分（0-100）
3. 识别供需瓶颈信号

输出格式：CK 因子评分表 + 瓶颈信号""",
    },
    {
        "name": "debate",
        "description": "多空辩论 — 分别找出多方和空方的核心论点",
        "toolsets": ["web", "terminal"],
        "system_prompt": """你是一个辩论分析师。你的职责是：
1. 分别构建多方和空方的核心论点
2. 为每个论点提供数据支撑
3. 输出辩论摘要

输出格式：多方论点 vs 空方论点 对比表""",
    },
    {
        "name": "cross_validate",
        "description": "交叉验证 — 多源数据交叉验证",
        "toolsets": ["web", "terminal", "wudao"],
        "system_prompt": """你是一个交叉验证分析师。你的职责是：
1. 从多个数据源交叉验证关键数据
2. 标记数据不一致
3. 输出验证报告

输出格式：数据源对比表 + 不一致标记""",
    },
    {
        "name": "model_panel",
        "description": "模型辩论面板 — 多模型交叉验证（V4 Flash / Nemotron / Gemma）",
        "toolsets": ["terminal"],
        "system_prompt": """你是一个模型辩论主持人。你的职责是：
1. 让多个模型分别分析同一问题
2. 对比各模型的结论差异
3. 输出综合判断

输出格式：多模型观点对比表""",
    },
    {
        "name": "sentiment",
        "description": "情绪分析 — 新闻情绪 + 机构评级 + 市场热度",
        "toolsets": ["web", "wudao"],
        "system_prompt": """你是一个情绪分析师。你的职责是：
1. 分析新闻情绪（正面/负面/中性）
2. 汇总机构评级
3. 评估市场热度

输出格式：情绪评分 + 机构评级汇总""",
    },
]

# ── 注册 ──────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  📋 Agent 河流 → AgentTemplate 注册")
    print("=" * 55)
    
    for a in AGENTS:
        register_template(
            name=a["name"],
            system_prompt=a["system_prompt"],
            toolsets=a["toolsets"],
            description=a["description"],
        )
        print(f"  ✅ [{a['name']:15s}] {a['description'][:40]}...")
    
    print(f"\n  已注册 {len(AGENTS)} 个模板\n")
    
    # 显示汇总
    templates = list_templates()
    print(f"{'='*55}")
    print(f"  📊 当前模板总览 ({len(templates)}):")
    print(f"{'='*55}")
    for t in templates:
        tools = ", ".join(t["toolsets"]) if t["toolsets"] else "(默认)"
        print(f"  [{t['name']:15s}] toolsets: {tools}")
        print(f"             {t['description']}")


if __name__ == "__main__":
    main()
