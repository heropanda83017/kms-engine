#!/usr/bin/env python3
"""Rewrite key orchestrator descriptions in natural language."""
import re
from pathlib import Path

SKILLS_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'skills'

rewrites = {
    "investment/stock-deep-research-sop": 
        "研究分析任何一只股票。说「研究下XX」「XX怎么样」「看看XX」「分析XX」时自动调用。9路并行深度分析→Agent河流交叉验证→完整研报，一条龙搞定。触发词：「研究一下」「深度分析」「个股研究」「股票分析」",
    
    "investment/stock-research-orchestrator":
        "个股全流程研究编排。说「研究XX股票」「全面分析XX」「XX基本面」时调用。DEFINE→ANALYZE 9路→CONTRAST三方对比→DELIVER 10节研报。触发词：「股票研究」「全流程」「个股分析」「研究股票」",
    
    "investment-agent-river":
        "10个Agent并行分析一只股票。说「河流研究XX」「深度分析XX」「Agent河流跑XX」时调用。9路并行分析→CK因子→多空辩论→情绪分析→交叉验证，结果归档到个股研究文件。触发词：「河流研究」「Agent河流」「研究河流」「并行分析」",
    
    "investment/daily-review-orchestrator":
        "收盘后复盘。说「今天复盘」「收盘了」「今日复盘」「盘面怎么样」时调用。自动采集6路MCP数据→市场分类→板块轮动→持仓自检→次日策略建议。交易日15:30后执行。触发词：「每日复盘」「收盘复盘」「今日复盘」「盘面分析」",
    
    "investment/strategy-backtest-orchestrator":
        "验证交易策略好不好用。说「回测XX策略」「测一下XX规则」「这个策略怎么样」时调用。自动定参数→回测→绩效归因→对比基准→风险评估→出回测报告。触发词：「策略回测」「回测」「回测策略」「策略验证」",
    
    "investment/strategy-engine":
        "看当前市场适合用什么策略。说「现在用什么策略」「市场什么情况」「策略锁定了吗」时调用。根据市场环境分类(5类市况)→锁定对应策略→监控是否需要切换。触发词：「策略管理」「策略锁定」「市场分类」「策略切换」",
    
    "investment/factor-deep-dive-orchestrator":
        "学一个因子是怎么回事。说「学一下XX因子」「XX因子怎么算」「因子拆解」时调用。回测IC→逐层拆解原理→业界做法→学术前沿→笔记归档。触发词：「因子拆解」「因子教学」「因子研究」「学因子」",
    
    "investment/industry-chain-mapper":
        "看一个行业的上下游产业链。说「产业链」「行业图谱」「XX上下游」「XX产业链」时调用。自动生成交互式d3.js图谱（PE分位着色+动量边框）+ 行业分析报告。触发词：「产业链」「产业图谱」「行业分析」「上下游」",
    
    "investment/investment-report":
        "出一份专业的投资分析报告。说「出个研报」「写报告」「生成研究报告」时调用。支持个股研报/行业研报/市场周报/舆情日报四种模板。触发词：「投资报告」「研报」「出报告」「写研报」",
    
    "investment/research-quality-check":
        "检查一份研报的质量。说「检查研报」「质量审查」「研报Review」时调用。从逻辑/数据/风险/收益/可维护性五个维度打分。触发词：「质量审查」「研报检查」「研报质量」",
    
    "investment/earnings-call-orchestrator":
        "分析上市公司的电话会议/业绩会。说「看看XX的业绩会」「电话会议」「业绩说明会」时调用。搜索最近业绩会纪要→财务分析→管理层指引→风险信号。触发词：「电话会议」「业绩会」「管理层分析」「业绩说明会」",
    
    "investment/investment-pipeline-operations":
        "运行每日数据流水线。说「跑流水线」「数据更新」「管线运行」时调用。自动采集新闻→因子映射→信号生成→Dashboard→复盘简报→策略锁定→推送通知。触发词：「数据流水线」「每日管线」「信号生成」",
    
    "investment/investment-self-monitor":
        "检查投资系统自己有没有出问题。说「系统自检」「持仓检查」「投资系统健康吗」时调用。自动检查持仓健康→交易行为异常→系统告警。不需要手动操作。触发词：「系统自检」「持仓健康」「交易异常」「系统告警」",
    
    "investment/research-debugging":
        "投资研究出错了怎么办。说「数据报错」「回测失败」「因子算不出来」「调试」时调用。系统化排查根因：数据源→因子计算→回测引擎，逐层定位问题。触发词：「调试」「数据错误」「回测失败」「因子报错」「问题诊断」",
    
    "investment/factor-weight-optimization":
        "优化多因子模型的权重。说「因子权重」「权重优化」「怎么配权重」时调用。用坐标下降法搜最优权重组合→walk-forward验证→止盈止损集成。触发词：「因子权重」「权重优化」「坐标下降」",
}

fixed = 0
for skill_name, new_desc in rewrites.items():
    md = SKILLS_DIR / skill_name / "SKILL.md"
    if not md.exists():
        print(f"❌ Not found: {skill_name}")
        continue
    
    content = md.read_text(encoding='utf-8', errors='replace')
    
    # Find and replace the description line
    # Handle both quoted and folded scalar formats
    # Pattern: match the description line(s) and replace with single-line description
    fm_match = re.match(r'^(---.*?^---)', content, re.DOTALL | re.MULTILINE)
    if not fm_match:
        print(f"❌ No frontmatter: {skill_name}")
        continue
    
    fm_text = fm_match.group(1)
    
    # Replace description: everything from "description:" to next non-indented line or ---
    lines = fm_text.split('\n')
    new_lines = []
    in_desc = False
    desc_line_found = False
    
    for line in lines:
        if line.startswith('description:') and not desc_line_found:
            # Replace with single-line description
            new_lines.append(f"description: {new_desc}")
            desc_line_found = True
            in_desc = False
        elif in_desc:
            # Skip indented continuation lines
            if line.startswith('  '):
                continue
            else:
                in_desc = False
                new_lines.append(line)
        else:
            new_lines.append(line)
        
        # Check if we're entering a folded scalar
        if line.startswith('description:') and (line.strip().endswith('>-') or line.strip().endswith('>') or line.strip().endswith('|') or line.strip().endswith('|-')):
            in_desc = True
    
    new_fm = '\n'.join(new_lines)
    content = content.replace(fm_text, new_fm)
    md.write_text(content, encoding='utf-8')
    fixed += 1
    print(f"✅ {skill_name}")

print(f"\nFixed: {fixed}/{len(rewrites)}")
