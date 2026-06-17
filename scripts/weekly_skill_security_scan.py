#!/usr/bin/env python3
"""
Weekly SkillSpector security scan wrapper.
Runs the lite scanner against all 142+ Hermes skills.
Compares findings against previous report to detect new issues.
"""
import json, subprocess, sys
from pathlib import Path
from datetime import datetime
from _path_setup import KMS_ROOT

SCANNER = str(KMS_ROOT / "scripts" / "scan_hermes_skills.py")
VENV_PYTHON = "/tmp/ss_venv/bin/python3"
REPORT_DIR = KMS_ROOT / "reports" / "security"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

today = datetime.now().strftime("%Y-%m-%d")
report_path = REPORT_DIR / f"skill_security_{today}.json"
prev_report = None

# Find previous report for comparison
existing = sorted(REPORT_DIR.glob("skill_security_*.json"))
if len(existing) >= 2:
    prev_report = existing[-2]

print(f"🛡️  Weekly SkillSpector Scan — {today}")
print(f"   Scanner: {SCANNER}")
print(f"   Venv:    {VENV_PYTHON}")
print(f"   Report:  {report_path}")

# Run scan
result = subprocess.run(
    [str(VENV_PYTHON), str(SCANNER)],
    capture_output=True, text=True, timeout=120,
    encoding='utf-8', errors='replace'
)

print(result.stdout)

if result.returncode != 0:
    print(f"⚠️  Scanner exited with code {result.returncode}")
    print(result.stderr[:500])

# Load current report for comparison
if report_path.exists():
    with open(report_path) as f:
        current = json.load(f)
    
    # Summary line for cron log
    findings = current.get('findings_total', 0)
    critical = current.get('severity_breakdown', {}).get('CRITICAL', 0)
    high = current.get('severity_breakdown', {}).get('HIGH', 0)
    
    print(f"\n📊 Summary: {findings} findings ({critical} CRITICAL, {high} HIGH)")
    
    # Compare with previous
    if prev_report and prev_report.exists():
        with open(prev_report) as f:
            prev = json.load(f)
        prev_findings = prev.get('findings_total', 0)
        delta = findings - prev_findings
        trend = "🟢 improved" if delta < 0 else ("🔴 worsened" if delta > 0 else "🟡 stable")
        print(f"   vs {prev_report.stem}: {delta:+d} findings ({trend})")
    
    # Alert on new CRITICAL/HIGH
    if critical > 0 or high > 5:
        print(f"\n⚠️  ALERT: {critical} CRITICAL + {high} HIGH findings — review recommended!")
        sys.exit(1)
    else:
        print(f"\n✅ No actionable alerts. Clean bill of health.")
        sys.exit(0)
else:
    print(f"❌ Report not generated at {report_path}")
    sys.exit(1)
