#!/usr/bin/env python3
"""Phase 1 v2: Scan sessions for actual skill usage."""
import json, re
from pathlib import Path
from collections import Counter

SESSIONS_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'sessions'
SKILLS_DIR = Path.home() / '.hermes' / 'profiles' / 'ai-investor' / 'skills'

# All skill short names (the part after last /)
skill_map = {}
for skill_md in SKILLS_DIR.rglob("SKILL.md"):
    full = str(skill_md.relative_to(SKILLS_DIR).parent)
    short = full.split("/")[-1]
    skill_map[short] = full

all_shorts = list(skill_map.keys())
print(f"Total skills: {len(skill_map)}")

# Scan recent sessions
files = sorted(SESSIONS_DIR.glob("*.json"))
agg = Counter()
session_count = 0
for f in files[-200:]:
    try:
        with open(f, encoding='utf-8', errors='replace') as fh:
            data = json.load(fh)
    except:
        continue
    
    session_count += 1
    sp = data.get('system_prompt', '')
    messages = data.get('messages', [])
    platform = data.get('platform', '')
    
    if platform == 'cron':
        continue
    
    found = set()
    for short in all_shorts:
        # Pattern 1: loaded via skill_view or mentioned in system prompt
        if re.search(r'`' + re.escape(short) + r'`', sp):
            found.add(short)
        # Pattern 2: mentioned as "xxx skill" in tool descriptions
        if re.search(re.escape(short) + r'\s+skill', sp, re.IGNORECASE):
            found.add(short)
        # Pattern 3: skill_view calls in messages
        for msg in messages[-15:]:
            content = str(msg.get('content', ''))
            if short in content and ('skill_view' in content or 'skill_manage' in content):
                found.add(short)
    
    for s in found:
        agg[s] += 1

print(f"Sessions scanned: {session_count}")

# Categorize
high = []   # >= 5
med = []    # 2-4
low = []    # 1
zero = []   # 0

for short in all_shorts:
    c = agg.get(short, 0)
    full = skill_map[short]
    if c >= 5:
        high.append((c, full))
    elif c >= 2:
        med.append((c, full))
    elif c == 1:
        low.append((c, full))
    else:
        zero.append(full)

print(f"\n{'='*60}")
print(f"SKILL USAGE REPORT")
print(f"{'='*60}")

print(f"\n🟢 高频 (>=5次): {len(high)}")
for c, name in sorted(high, reverse=True):
    print(f"  {c:4d}x  {name}")

print(f"\n🟡 中频 (2-4次): {len(med)}")
for c, name in sorted(med, reverse=True):
    print(f"  {c:4d}x  {name}")

print(f"\n🔵 低频 (1次): {len(low)}")
for c, name in sorted(low, reverse=True):
    print(f"  {c:4d}x  {name}")

print(f"\n⚫ 零激活: {len(zero)}")

print(f"\n{'='*60}")
print(f"  合计: {len(all_shorts)}")
print(f"  有记录: {len(high)+len(med)+len(low)}")
print(f"  零激活: {len(zero)} ({len(zero)/len(all_shorts)*100:.1f}%)")
print(f"{'='*60}")
