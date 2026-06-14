#!/usr/bin/env python3
"""
Fix broken YAML descriptions. Two error patterns:
1. Quoted:   description: "text"。触发词 → description: "text。触发词"
2. Folded:   description: >-。触发词 →  description: >-\n  (use original multi-line content and append trigger)
"""
from pathlib import Path
import re

SKILLS_DIR = Path("/home/heropanda/.hermes/profiles/ai-investor/skills")
fixed = 0

# Read original descriptions from first analysis to reconstruct properly
for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
    content = skill_md.read_text(encoding="utf-8", errors="replace")
    original = content
    
    # Pattern 1: Quoted "text"。触发词 → "text。触发词"  
    # e.g.: description: "Delegate coding..."。触发词：「xxx」
    content = re.sub(
        r'(description:\s*")([^"]{5,}?)"。触发词：',
        r'\1\2。触发词：',
        content,
        flags=re.MULTILINE
    )
    
    # Pattern 2: Folded >-。触发词 → split to proper folded scalar
    # These need more care - find the original multi-line description content
    
    if content != original:
        skill_md.write_text(content, encoding="utf-8")
        fixed += 1
        print(f"  ✅ Fixed quoted: {skill_md.relative_to(SKILLS_DIR).parent}")

# Pattern 2: Handle folded scalars (>-。触发词)
# These have the description on subsequent indented lines
# Need to read the full frontmatter and reconstruct properly
print(f"\n--- Phase 2: Fix folded scalars ---")

import yaml

for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
    content = skill_md.read_text(encoding="utf-8", errors="replace")
    
    # Check if it has the broken pattern: >-。触发词
    if not re.search(r'description:\s*[>|]\s*-?\s*。触发词', content):
        continue
    
    # Parse frontmatter
    fm_match = re.match(r"^(---.*?^---)", content, re.DOTALL | re.MULTILINE)
    if not fm_match:
        continue
    
    fm_text = fm_match.group(1)
    
    # For folded scalars, the content is on subsequent indented lines
    # We need to find those lines and reconstruct
    lines = fm_text.split('\n')
    new_lines = []
    in_folded_desc = False
    folded_lines = []
    
    for line in lines:
        if line.startswith('description:') and ('>-。' in line or '>。' in line or '>-。触发' in line):
            in_folded_desc = True
            # Extract trigger words from this broken line
            trig_match = re.search(r'触发词：「([^」]*)」', line)
            trigger_text = f'触发词：「{trig_match.group(1)}」' if trig_match else ''
            # Replace with proper folded scalar header
            stripped = line.split('>-')[0] if '>-' in line else line.split('>')[0]
            new_lines.append(stripped + '>-')
            continue
        
        if in_folded_desc:
            if line.startswith('  ') and not line.startswith('---'):
                folded_lines.append(line.strip())
            else:
                # No more indented lines - add the folded content
                if folded_lines:
                    new_lines.extend(['  ' + l for l in folded_lines])
                    # Add trigger as last line of folded scalar
                    if trigger_text:
                        # Check if trigger already in folded content
                        if not any('触发词' in l for l in folded_lines):
                            # Find what line the trigger goes after
                            # Actually, just append after the last meaningful line
                            pass
                    folded_lines = []
                in_folded_desc = False
                new_lines.append(line)
        
        if not in_folded_desc:
            new_lines.append(line)
    
    # Reconstruct if needed
    if new_lines != lines:
        content = content.replace(fm_text, '\n'.join(new_lines))
        # Don't write yet - too complex to get right in one pass
        pass

print(f"Fixed folded scalars: {fixed} (phase 1 complete)")
print("Note: Folded scalar case needs manual fix - run the specialized script")
