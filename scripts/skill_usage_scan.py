#!/usr/bin/env python3
"""
Phase 1: Skill Usage Telemetry
Scan Hermes session DB → 统计每个 Skill 的实际加载/触发频率
"""
import json, re
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter, defaultdict

SESSIONS_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'sessions'
SKILLS_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'skills'

# All skill names (from actual SKILL.md files on disk)
ALL_SKILLS = set()
for skill_md in SKILLS_DIR.rglob("SKILL.md"):
    name = str(skill_md.relative_to(SKILLS_DIR).parent)
    ALL_SKILLS.add(name)

# Build regex patterns for each skill (match in system prompt)
# Hermes injects skill descriptions like "name: xxx\ndescription: yyy"
SKILL_PATTERNS = {}
for s in ALL_SKILLS:
    short = s.split("/")[-1]
    SKILL_PATTERNS[s] = re.compile(
        r'name:\s*' + re.escape(short) + r'[^_a-z]',
        re.IGNORECASE
    )

def scan_sessions(days_back=90, max_files=500):
    """Scan session files and count skill activations."""
    session_files = sorted(SESSIONS_DIR.glob("*.json"))
    cutoff = datetime.now() - timedelta(days=days_back)
    
    # Per-skill counts
    skill_count = Counter()  # times loaded in system prompt
    skill_msg_count = Counter()  # times mentioned in messages (skill_view)
    session_skill_map = defaultdict(set)  # which skills per session
    daily_active_skills = defaultdict(set)  # skills active per day
    
    total_sessions = 0
    loaded_sessions = 0
    skipped = 0
    
    for sf in session_files[-max_files:]:
        total_sessions += 1
        try:
            with open(sf, encoding='utf-8', errors='replace') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            skipped += 1
            continue
        
        session_start = data.get('session_start', '')
        if session_start:
            try:
                dt = datetime.fromisoformat(session_start.replace('Z', '+00:00'))
                if dt < cutoff:
                    continue
            except:
                pass
        
        system_prompt = data.get('system_prompt', '')
        messages = data.get('messages', [])
        
        # 1. Check system prompt for skill descriptions
        skills_in_session = set()
        for skill_name, pattern in SKILL_PATTERNS.items():
            if pattern.search(system_prompt):
                skills_in_session.add(skill_name)
                skill_count[skill_name] += 1
        
        # 2. Check messages for skill_view() calls
        for msg in messages:
            content = str(msg.get('content', ''))
            for skill_name in ALL_SKILLS:
                short = skill_name.split("/")[-1]
                # Match skill_view(name='skill-name') or skill_view(name="skill-name")
                if re.search(rf"skill_view\(name=['\"]{re.escape(short)}['\"]", content, re.IGNORECASE):
                    skills_in_session.add(skill_name)
                    skill_msg_count[skill_name] += 1
        
        if skills_in_session:
            loaded_sessions += 1
            session_skill_map[sf.stem] = skills_in_session
            if session_start:
                try:
                    date_key = datetime.fromisoformat(session_start.replace('Z', '+00:00')).strftime('%Y-%m-%d')
                    daily_active_skills[date_key].update(skills_in_session)
                except:
                    pass
    
    return {
        'total_sessions': total_sessions,
        'loaded_sessions': loaded_sessions,
        'skipped': skipped,
        'skill_count': skill_count,
        'skill_msg_count': skill_msg_count,
        'total_skills': len(ALL_SKILLS),
        'active_skills': len(skill_count),
        'session_skill_map': session_skill_map,
        'daily_active_skills': daily_active_skills,
    }


def print_report(result):
    """Pretty-print skill usage report."""
    skill_count = result['skill_count']
    
    print("=" * 70)
    print("  Phase 1: Skill Usage Telemetry Report")
    print(f"  Sessions scanned: {result['total_sessions']}")
    print(f"  Sessions with skills loaded: {result['loaded_sessions']}")
    print(f"  Total SKILL.md on disk: {result['total_skills']}")
    print(f"  Skills ever activated: {result['active_skills']}")
    print(f"  Zero-activation skills: {result['total_skills'] - result['active_skills']}")
    print(f"  Coverage rate: {result['active_skills']/result['total_skills']*100:.1f}%")
    print("=" * 70)
    
    # Tier 1: High frequency (>= 10 activations)
    print("\n🟢 高频激活 (≥10次):")
    high = [(s, c) for s, c in skill_count.most_common() if c >= 10]
    for name, count in high:
        print(f"  {count:4d}x  {name}")
    
    # Tier 2: Medium frequency (3-9)
    print("\n🟡 中频激活 (3-9次):")
    med = [(s, c) for s, c in skill_count.most_common() if 3 <= c < 10]
    for name, count in med:
        print(f"  {count:4d}x  {name}")
    
    # Tier 3: Low frequency (1-2)
    print("\n🔵 低频激活 (1-2次):")
    low = [(s, c) for s, c in skill_count.most_common() if 1 <= c < 3]
    for name, count in low:
        print(f"  {count:4d}x  {name}")
    
    # Tier 4: Zero activation
    print("\n⚫ 零激活 (0次):")
    all_activated = set(s for s, c in skill_count.items())
    zero = sorted(ALL_SKILLS - all_activated)
    # Group by category
    cats = defaultdict(list)
    for name in zero:
        cat = name.split("/")[0] if "/" in name else "(root)"
        cats[cat].append(name)
    for cat in sorted(cats):
        print(f"  [{cat}]")
        for name in sorted(cats[cat]):
            print(f"    - {name}")
    
    # Summary table
    print("\n" + "=" * 70)
    print("  活性汇总")
    print(f"  🟢 高频 (≥10次):   {len(high)} 个")
    print(f"  🟡 中频 (3-9次):    {len(med)} 个")
    print(f"  🔵 低频 (1-2次):    {len(low)} 个")
    print(f"  ⚫ 零激活 (0次):    {len(zero)} 个")
    print(f"  ─────────────────────")
    print(f"  总计:               {result['total_skills']} 个")
    print(f"  活跃率:             {result['active_skills']/result['total_skills']*100:.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    print(f"Scanning last {days} days of sessions...")
    result = scan_sessions(days_back=days, max_files=500)
    print_report(result)
    
    # Save raw data
    out = {
        'report_date': datetime.now().isoformat(),
        'days_back': days,
        'total_skills': result['total_skills'],
        'active_skills': result['active_skills'],
        'skill_frequencies': dict(result['skill_count'].most_common()),
    }
    out_path = Path("/tmp/hermes_skill_usage_report.json")
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nRaw data saved: {out_path}")
