#!/usr/bin/env python3
"""
Batch patch SKILL.md descriptions — append trigger keywords for all skills that lack explicit triggers.
Builds trigger words from skill name, category path, and key nouns in existing description.
"""
import re, yaml
from pathlib import Path

SKILLS_DIR = Path("/home/heropanda/.hermes/profiles/ai-investor/skills")

# Manual trigger word mapping for specific skills (hard to infer from name alone)
MANUAL_TRIGGERS = {
    "apikey-image-gen": "「图片生成」「图片编辑」「文生图」「图像生成」",
    "autonomous-ai-agents/claude-code": "「编码」「code」「编程」「用Claude写代码」",
    "autonomous-ai-agents/hermes-agent": "「Hermes配置」「配置Hermes」「Hermes设置」「setup」",
    "autonomous-ai-agents/hermes-web-ui": "「Hermes网页」「Web UI」「dashboard」",
    "avoid-ai-writing": "「去AI味」「去AI痕迹」「AI写作」「改写」「humanize」「去AI味写作」",
    "data-science/jupyter-live-kernel": "「数据科学」「Jupyter」「数据分析」「notebook」「可视化」",
    "devops/kanban-orchestrator": "「看板」「kanban」「任务编排」「工作流编排」",
    "devops/kanban-worker": "「看板worker」「kanban执行」「任务执行」",
    "devops/webhook-subscriptions": "「webhook」「事件订阅」「回调」",
    "dogfood": "「吃狗粮」「QA」「质量测试」「bug检测」",
    "email/himalaya": "「邮件」「email」「发邮件」「查邮件」",
    "github/github-auth": "「GitHub认证」「GitHub登录」「gh auth」「GitHub token」",
    "github/github-code-review": "「代码审查」「PR审查」「code review」「Review PR」",
    "github/github-issues": "「Issue」「GitHub issue」「提issue」「任务管理」",
    "github/github-pr-workflow": "「PR流程」「pull request」「PR生命周期」「合并PR」",
    "github/github-repo-management": "「仓库管理」「repo管理」「Git仓库」「GitHub仓库」",
    "grok-image-to-video": "「图片转视频」「视频生成」「Grok」「动画」",
    "html-report-to-visual-faithful-pdf": "「HTML转PDF」「PDF生成」「打印PDF」「报告转PDF」",
    "investment/auto-skill-creator": "「创建skill」「自动创建」「skill创建」「保存为skill」",
    "investment/daily-review-orchestrator": "「每日复盘」「收盘复盘」「晚间复盘」「今日复盘」",
    "investment/earnings-call-analysis": "「电话会议」「业绩会」「earnings call」「管理层分析」",
    "investment/earnings-call-orchestrator": "「电话会议」「业绩会」「业绩说明会」「管理层指引」",
    "investment/external-engineering-insight": "「外部借鉴」「工程洞察」「技能分析」「模式提取」",
    "investment/factor-deep-dive": "「因子深研」「因子教学」「学因子」「因子原理」",
    "investment/factor-deep-dive-orchestrator": "「因子深度拆解」「因子研究」「因子分析」",
    "investment/factor-system-health": "「因子健康」「IC衰减」「因子监控」「因子质量」",
    "investment/factor-weight-optimization": "「因子权重」「权重优化」「坐标下降」「权重搜索」",
    "investment/futures-strategy": "「股指期货」「期货策略」「IM/IC/IF/IH」「期货回测」",
    "investment/industry-chain-mapper": "「产业链」「产业链图谱」「链图谱」「行业图谱」",
    "investment/industry-kpi-builder": "「行业KPI」「KPI模板」「行业指标」「运营KPI」",
    "investment/investment-pipeline-operations": "「投资管线」「流水线」「数据分析管线」「每日管线」",
    "investment/investment-research-cycle": "「研究闭环」「投研流程」「外部借鉴归档」「研究归档」",
    "investment/pipeline-governance": "「熔断器」「治理层」「Harness」「管线监控」",
    "investment/research-debugging": "「调试」「数据错误」「回测失败」「因子报错」「问题诊断」",
    "investment/research-quality-check": "「质量审查」「研报质量」「研报检查」「五维审查」",
    "investment/skill-quality-automation": "「技能进化」「skill进化」「DSPy优化」「GEPA」",
    "investment/socratic-research": "「苏格拉底」「追问」「研究聚焦」「模糊想法」",
    "investment/spec-driven-research": "「规格驱动」「研究规格」「假设验证」「研究框架」",
    "investment/stock-deep-research-sop": "「个股深度」「深度研究」「全面分析」「股票研究」",
    "investment/stock-research-orchestrator": "「股票研究」「全流程研究」「编排研究」「个股分析」",
    "investment/strategy-backtest-orchestrator": "「策略回测」「回测」「策略验证」「回测报告」",
    "investment/strategy-engine": "「策略管理」「策略锁定」「市场分类」「板块轮动」",
    "investment/wechat-intel": "「微信情报」「聊天记录」「微信分析」「私域情报」",
    "investment/workflow-generator": "「工作流」「workflow」「编排」「批量采集」",
    "investment-agent-river": "「河流研究」「Agent河流」「研究河流」「6Agent」",
    "investment-analysis": "「投资分析」「分析工具箱」「投资研究」「选股分析」",
    "investment-report": "「投资报告」「研报」「行业研报」「个股研报」「周报」",
    "mcp/mcp-stdio-server": "「MCP服务器」「MCP stdio」「创建MCP」「MCP开发」",
    "mcp/native-mcp": "「MCP客户端」「MCP连接」「MCP配置」「native MCP」",
    "media/bilibili-content": "「B站」「Bilibili」「哔哩哔哩」「B站视频」",
    "media/gif-search": "「GIF」「动图」「表情包」「搜GIF」",
    "media/heartmula": "「歌曲生成」「音乐生成」「AI音乐」「歌词生成」",
    "media/mmx-cli": "「MiniMax」「mmx」「视频生成」「图像生成」「语音合成」",
    "media/spotify": "「Spotify」「音乐」「播放列表」「歌单」",
    "media/youtube-content": "「YouTube」「视频摘要」「油管」「YouTube转写」",
    "meeting-minutes": "「会议纪要」「公文排版」「会议记录」「格式规范」",
    "minimax": "「MiniMax」「海螺AI」「视频生成」「图像生成」",
    "mlops/evaluation/lm-evaluation-harness": "「模型评测」「LLM评测」「benchmark」「MMLU」「GSM8K」",
    "mlops/evaluation/weights-and-biases": "「W&B」「Weights & Biases」「实验追踪」「模型注册」",
    "mlops/huggingface-hub": "「HuggingFace」「HF Hub」「模型下载」「数据集下载」",
    "mlops/inference/llama-cpp": "「llama.cpp」「GGUF」「本地推理」「模型量化」",
    "mlops/inference/obliteratus": "「去审查」「abliterate」「模型去限制」「拒绝消除」",
    "mlops/inference/vllm": "「vLLM」「高吞吐推理」「模型部署」「推理加速」",
    "mlops/models/audiocraft": "「AudioCraft」「音乐生成」「MusicGen」「音频生成」",
    "mlops/models/segment-anything": "「SAM」「图像分割」「分割一切」「Segment Anything」",
    "mlops/research/dspy": "「DSPy」「声明式编程」「LM程序」「prompt优化」",
    "morning-routine": "「早上好」「你好」「早安」「每日简报」「例行检查」",
    "next-slide": "「PPT」「演示」「幻灯片」「slide」「做个PPT」",
    "note-taking/factor-note-template": "「因子笔记」「因子模板」「笔记模板」「因子研究笔记」",
    "note-taking/obsidian": "「Obsidian」「笔记」「知识库」「vault」",
    "operations/agent-reach": "「数据采集」「爬虫」「信息收集」「多平台采集」",
    "operations/claude-code-coding": "「代码审查」「FINAL REVIEW」「V4 Pro审查」「代码质量」",
    "operations/context-engineering": "「上下文工程」「提示词优化」「token预算」「上下文压缩」",
    "operations/design-review": "「设计审查」「架构审查」「ARCH审查」「方案评审」",
    "operations/frontier-evolution-cycle": "「前沿对标」「技术监控」「技术演进」「差距分析」",
    "operations/hermes-operations": "「Hermes操作」「Hermes命令」「hermes CLI」「Web Dashboard」",
    "operations/hermes-runtime-extension": "「运行时扩展」「monkey-patch」「代理扩展」「运行时注入」",
    "operations/model-provider-integration": "「模型配置」「provider」「模型供应商」「模型路由」",
    "operations/profile-health-audit": "「配置审计」「profile审计」「配置健康」「跨profile检查」",
    "operations/self-audit": "「自检」「体系审计」「差距对标」「覆盖度评分」",
    "operations/system-architecture-evolution": "「架构演进」「系统改造」「架构升级」「P0/P1/P2」",
    "operations/system-operations": "「系统运维」「健康检查」「运维工具」「系统监控」",
    "operations/windows-env-workflow": "「Windows环境」「WSL」「跨平台」「环境配置」",
    "operations/workflow-code-generation": "「代码生成」「ARCH→代码」「CC生成」「工作流生成」",
    "operations/workspace-audit": "「目录审计」「工作空间」「项目结构」「知识萃取」",
    "productivity/airtable": "「Airtable」「数据库」「表格」「数据管理」",
    "productivity/google-workspace": "「Google」「Gmail」「Google日历」「Google Drive」",
    "productivity/kms": "「KMS」「知识管理」「知识库」「wiki」「笔记管理」",
    "productivity/linear": "「Linear」「项目管理」「任务管理」「issue管理」",
    "productivity/maps": "「地图」「地理编码」「路径规划」「POI」",
    "productivity/nano-pdf": "「PDF编辑」「PDF修改」「修改PDF」「PDF文字」",
    "productivity/notion": "「Notion」「笔记」「数据库」「项目管理」",
    "productivity/ocr-and-documents": "「OCR」「文字识别」「文档提取」「PDF提取」",
    "productivity/powerpoint": "「PowerPoint」「PPT」「演示文稿」「幻灯片」",
    "productivity/teams-meeting-pipeline": "「Teams」「会议摘要」「Microsoft Teams」「会议记录」",
    "productivity/xhs-video-to-notes": "「小红书视频」「视频转笔记」「XHS转写」",
    "remotion": "「Remotion」「视频制作」「React视频」「动画视频」",
    "report-extractor": "「研报提取」「报告提取」「提取研报」「文档提取」",
    "research/arxiv": "「ArXiv」「论文搜索」「学术论文」「论文检索」",
    "research/blogwatcher": "「博客监控」「RSS」「Feed」「博客订阅」",
    "research/external-research-integration": "「外部研究」「研究集成」「学术整合」「论文集成」",
    "research/llm-wiki": "「LLM知识库」「第二大脑」「wiki查询」「知识检索」",
    "research/polymarket": "「预测市场」「Polymarket」「链上数据」「事件预测」",
    "research/research-paper-writing": "「论文写作」「学术论文」「ML论文」「NeurIPS」「ICML」",
    "scrapling-reportify": "「Scrapling」「爬虫」「反爬突破」「报告抓取」",
    "social-media/xurl": "「X/Twitter」「Twitter发文」「发推」「社交媒体」",
    "software-development/debugging-hermes-tui-commands": "「TUI调试」「Hermes命令」「斜杠命令」「slash command」",
    "software-development/ecc-agent-engineering": "「ECC」「Agent工程」「8角色」「工程流水线」",
    "software-development/hermes-agent-skill-authoring": "「SKILL.md」「创建skill」「skill格式」「skill创作」",
    "software-development/hermes-s6-container-supervision": "「容器」「Docker」「s6」「容器监控」「supervision」",
    "software-development/node-inspect-debugger": "「Node.js调试」「Node调试」「Chrome DevTools」「调试」",
    "software-development/plan": "「规划」「plan」「计划」「执行计划」「设计方案」",
    "software-development/python-debugpy": "「Python调试」「debugpy」「远程调试」「debug」",
    "software-development/requesting-code-review": "「代码审查」「安全扫描」「提交前审查」「pre-commit」",
    "software-development/spike": "「技术探索」「spike」「原型验证」「可行性验证」",
    "software-development/subagent-driven-development": "「子Agent」「委托任务」「并行开发」「多Agent」",
    "software-development/systematic-debugging": "「系统调试」「根因分析」「bug修复」「bug调试」",
    "software-development/test-coverage-playbook": "「测试覆盖」「单元测试」「pytest」「测试补全」",
    "software-development/test-driven-development": "「TDD」「测试驱动」「先测试后代码」「RED-GREEN」",
    "stock-research": "「股票数据」「股票查询」「个股行情」「A股数据」",
    "test-kms-core": "「KMS测试」「核心测试」「pytest」「KMS单元测试」",
    "wechat-article-scraper": "「微信公众号」「文章抓取」「公众号文章」「微信文章」",
    "xhs-sentiment-monitoring": "「小红书舆情」「情感分析」「舆情监控」「小红书监控」",
    "yuanbao": "「元宝」「企业微信」「群聊」「@成员」",
}


def get_trigger_from_desc(desc: str, skill_name: str) -> str | None:
    """Extract or generate trigger words for a skill without existing triggers."""
    # Skip if skill has manual mapping
    if skill_name in MANUAL_TRIGGERS:
        return MANUAL_TRIGGERS[skill_name]
    
    # Auto-generate from description key nouns
    # Extract Chinese keywords (non-stop words)
    desc_clean = desc.strip()
    if not desc_clean:
        return None
    
    # Fall back: use skill's short name as trigger
    short_name = skill_name.split("/")[-1].replace("-", "")
    return f"「{short_name}」「{short_name.replace('_','')}」"


def patch_description(filepath: Path) -> bool:
    """Add trigger words to description line if missing."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    
    # Check frontmatter
    fm_match = re.match(r"^(---.*?^---)", content, re.DOTALL | re.MULTILINE)
    if not fm_match:
        return False
    
    fm_text = fm_match.group(1)
    
    # Parse description
    desc_match = re.search(r"^description:\s*(.+)$", fm_text, re.MULTILINE)
    if not desc_match:
        return False
    
    desc = desc_match.group(1).strip()
    
    # Check if trigger words already exist
    if re.search(r"触发词|Use when|Use for|触发条件|触发场景", desc):
        return False
    
    # Get relative name
    rel = filepath.relative_to(SKILLS_DIR)
    skill_name = str(rel.parent)
    
    trigger_text = get_trigger_from_desc(desc, skill_name)
    if not trigger_text:
        return False
    
    # Append trigger words to description line
    new_desc = f"{desc}。触发词：{trigger_text}"
    old_line = desc_match.group(0)
    new_line = f"description: {new_desc}"
    
    # Replace in content
    new_content = content.replace(old_line, new_line, 1)
    if new_content != content:
        filepath.write_text(new_content, encoding="utf-8")
        return True
    return False


def main():
    changed = 0
    skipped_builtin = 0
    already_have = 0
    no_desc = 0
    
    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        rel = skill_md.relative_to(SKILLS_DIR)
        name = str(rel.parent)
        
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        
        # Check frontmatter
        fm_match = re.match(r"^(---.*?^---)", content, re.DOTALL | re.MULTILINE)
        if not fm_match:
            print(f"  ⚠️  No frontmatter: {name}")
            continue
        
        fm_text = fm_match.group(1)
        
        # Parse description
        desc_match = re.search(r"^description:\s*(.+)$", fm_text, re.MULTILINE)
        if not desc_match:
            no_desc += 1
            print(f"  ❌ No description: {name}")
            continue
        
        desc = desc_match.group(1).strip()
        
        # Check if trigger words already exist
        if re.search(r"触发词|Use when|Use for", desc):
            already_have += 1
            continue
        
        if patch_description(skill_md):
            changed += 1
            trigger_text = get_trigger_from_desc(desc, name)
            print(f"  ✅ {name} → +{trigger_text}")
        else:
            print(f"  ⚠️  No manual mapping: {name}")
    
    print(f"\n{'='*50}")
    print(f"Total: {already_have + changed + no_desc} skills")
    print(f"✅ Already had triggers: {already_have}")
    print(f"✅ Patched with triggers: {changed}")
    print(f"❌ No description: {no_desc}")


if __name__ == "__main__":
    main()
