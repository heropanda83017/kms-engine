#!/usr/bin/env python3
"""Generate Skill Directory — comprehensive index of all 141 skills.
Output: skill_directory.md (auto-loaded by skill-routing skill)
"""
import re, yaml, json
from pathlib import Path
from datetime import datetime

SKILLS_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'skills'
OUT_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'skills' / 'operations' / 'skill-routing'

# Category labels
CATEGORY_NAMES = {
    'investment': '💎 投资研究',
    'operations': '⚙️ 系统运维',
    'software-development': '🔧 软件开发',
    'productivity': '📋 效率工具',
    'research': '📚 学术研究',
    'media': '🎵 媒体处理',
    'mlops': '🤖 MLOps',
    'github': '🐙 GitHub',
    'mcp': '🔌 MCP',
    'devops': '🚀 DevOps',
    'note-taking': '📝 笔记',
}

def extract_triggers(desc: str) -> list[str]:
    """Extract trigger keywords from description."""
    triggers = []
    # 触发词：「a」「b」「c」
    m = re.search(r'触发词[：:](.+?)(?:\n|$)', desc)
    if m:
        triggers.extend(re.findall(r'「([^」]*)」', m.group(1)))
    # 触发场景：「a」「b」
    m = re.search(r'触发场景[：:](.+?)(?:\n|$)', desc)
    if m:
        triggers.extend(re.findall(r'「([^」]*)」', m.group(1)))
    # Use when / Use for
    m = re.search(r'Use when (.+?)(?:\.|$)', desc)
    if m:
        triggers.append(m.group(1).strip())
    return triggers

def get_triggers_next(short_name: str) -> list[str]:
    """Determine what skills should be triggered after this one."""
    triggers_next = []
    
    # Investment orchestrator chains  
    if short_name == 'stock-deep-research-sop':
        triggers_next = ['investment/investment-agent-river', 'investment/investment-report', 'investment/research-quality-check']
    elif short_name == 'investment-agent-river':
        triggers_next = ['investment/investment-report', 'investment/research-quality-check']
    elif short_name == 'daily-review-orchestrator':
        triggers_next = ['investment/strategy-engine', 'investment/investment-pipeline-operations']
    elif short_name == 'factor-deep-dive-orchestrator':
        triggers_next = ['investment/factor-weight-optimization', 'investment/factor-system-health']
    elif short_name == 'stock-research-orchestrator':
        triggers_next = ['investment/investment-report']
    elif short_name == 'earnings-call-orchestrator':
        triggers_next = ['investment/investment-report']
    elif short_name == 'strategy-backtest-orchestrator':
        triggers_next = ['investment/strategy-engine']
    elif short_name == 'external-engineering-insight':
        triggers_next = ['investment/investment-research-cycle']
    elif short_name == 'industry-chain-mapper':
        triggers_next = ['investment/industry-kpi-builder']
    elif short_name == 'socratic-research':
        triggers_next = ['analysis-frameworks', 'investment/investment-analysis']
    elif short_name == 'spec-driven-research':
        triggers_next = ['investment/stock-deep-research-sop']
    elif short_name == 'research-debugging':
        triggers_next = ['investment/factor-deep-dive']
    elif short_name == 'research-quality-check':
        triggers_next = ['investment/investment-report']
    
    return triggers_next

def main():
    entries = []
    
    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        rel = skill_md.relative_to(SKILLS_DIR)
        full_name = str(rel.parent)
        short_name = full_name.split("/")[-1]
        category = full_name.split("/")[0] if "/" in full_name else "other"
        
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        
        # Extract description from YAML
        desc = ""
        try:
            fm_match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)", content, re.DOTALL)
            if fm_match:
                fm_data = yaml.safe_load(fm_match.group(1))
                if isinstance(fm_data, dict) and 'description' in fm_data:
                    desc = str(fm_data['description']).strip()
        except:
            pass
        
        triggers = extract_triggers(desc)
        triggers_next = get_triggers_next(short_name)
        
        entries.append({
            'name': full_name,
            'short': short_name,
            'category': CATEGORY_NAMES.get(category, category),
            'description': desc[:150],
            'triggers': triggers,
            'triggers_next': triggers_next,
        })
    
    # Generate markdown directory
    lines = [
        "---",
        "name: skill-routing",
        "description: >-",
        "  Skill 路由目录 — 所有可用 Skill 的索引+触发词+链式调用。",
        "  用户在输入中包含触发词时，自动 skill_view 加载对应 Skill。",
        "  执行完一个 Skill 后，检查 triggers_next 加载下一个。",
        "trigger:",
        "  - skill routing",
        "  - skill directory",
        "  - available skills",
        f"version: 1.0.0 ({datetime.now().strftime('%Y-%m-%d')})",
        "---",
        "",
        "# 🗺️ Skill Directory — 技能路由目录",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 共 {len(entries)} 个 Skill",
        ">",
        "> **如何使用：** 用户在输入中提到以下触发词时，自动 `skill_view(name='xxx')` 加载对应 Skill。",
        "> 执行完成后，检查 `triggers_next` 看是否要继续加载下一个 Skill。",
        "",
    ]
    
    # Group by category
    cats = {}
    for e in entries:
        cats.setdefault(e['category'], []).append(e)
    
    for cat in sorted(cats.keys()):
        items = cats[cat]
        lines.append(f"---")
        lines.append(f"## {cat} ({len(items)}个)")
        lines.append("")
        
        for e in items:
            lines.append(f"### {e['name']}")
            lines.append(f"")
            lines.append(f"{e['description']}")
            lines.append(f"")
            if e['triggers']:
                lines.append(f"- **触发词：** {' '.join(f'`{t}`' for t in e['triggers'])}")
            if e['triggers_next']:
                lines.append(f"- **触发之后：** → {' → '.join(f'`{t}`' for t in e['triggers_next'])}")
            lines.append(f"")
    
    lines.append("---")
    lines.append(f"*End of Skill Directory — {len(entries)} skills*")
    
    output = "\n".join(lines)
    
    # Write to skill-routing directory
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "SKILL.md"
    # Atomic write
    tmp = out_path.with_suffix(".md.tmp")
    tmp.write_text(output, encoding="utf-8")
    tmp.replace(out_path)
    
    print(f"✅ Skill Directory generated: {out_path}")
    print(f"   {len(entries)} skills")
    
    # Also write JSON version for programmatic use
    json_path = OUT_DIR / "skill_directory.json"
    json_tmp = json_path.with_suffix(".json.tmp")
    json_tmp.write_text(json.dumps({
        'generated': datetime.now().isoformat(),
        'total': len(entries),
        'skills': entries,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    json_tmp.replace(json_path)
    print(f"✅ JSON directory: {json_path}")
    
    # Print routing stats
    with_chains = sum(1 for e in entries if e['triggers_next'])
    with_triggers = sum(1 for e in entries if e['triggers'])
    print(f"\n📊 Stats:")
    print(f"   Skills with triggers: {with_triggers}")
    print(f"   Skills with chains: {with_chains}")
    print(f"   Chain coverage: {with_chains/len(entries)*100:.1f}%")

if __name__ == "__main__":
    main()
