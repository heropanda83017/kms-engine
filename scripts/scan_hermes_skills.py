#!/usr/bin/env python3
"""
SkillSpector 轻量集成 — 扫描 Hermes Agent 所有 SKILL.md 的安全状态。
安装: 在 Python 3.14 venv 中运行（因 upstream 依赖 yara-python + langgraph）
用法: /tmp/ss_venv/bin/python3 scripts/scan_hermes_skills.py

来源: https://github.com/nvidia/skillspector (Apache 2.0)
"""
import sys, os, json, re
from pathlib import Path

# 添加 SkillSpector 源码到路径
SS_SRC = Path("/mnt/e/AIGC-KB/kms-engine/output/skillspector/src")
sys.path.insert(0, str(SS_SRC))

SKILLS_DIR = Path("/home/heropanda/.hermes/profiles/ai-investor/skills")

# === 轻量复用 SkillSpector 的静态检测模式（不依赖 langgraph 完整管线） ===

# Prompt Injection patterns (from static_patterns_prompt_injection.py)
PROMPT_INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|directives|commands)", "P1", "Instruction Override", "HIGH"),
    (r"(system|secret|hidden)\s*(prompt|instruction|command)", "P2", "Hidden Instructions", "HIGH"),
    (r"(send|transmit|exfiltrate|leak|upload)\s+(context|data|conversation|everything)", "P3", "Exfiltration Commands", "HIGH"),
    (r"act\s+as\s+(admin|root|superuser|god)", "P4", "Behavior Manipulation", "MEDIUM"),
    (r"(harmful|malicious|dangerous|weapon|attack)", "P5", "Harmful Content", "CRITICAL"),
]

# Data Exfiltration patterns (from static_patterns_data_exfiltration.py)
EXFILTRATION_PATTERNS = [
    (r"(curl|wget|requests\.(get|post)|httpx\.(get|post))\s+https?://", "E1", "External Transmission", "MEDIUM"),
    (r"(os\.environ|environ\b|os\.getenv)\b", "E2", "Env Variable Harvesting", "HIGH"),
    (r"(os\.listdir|os\.walk|glob\.glob|pathlib\.Path.*\.iterdir)", "E3", "File System Enumeration", "MEDIUM"),
]

# Supply Chain patterns (from static_patterns_supply_chain.py)
SUPPLY_CHAIN_PATTERNS = [
    (r"(curl|wget)\s+.*\|\s*(bash|sh|python)", "SC2", "External Script Fetching", "HIGH"),
    (r"base64\s*\([^)]{20,}", "SC3", "Obfuscated Code (base64)", "HIGH"),
]

# Excessive Agency patterns
AGENCY_PATTERNS = [
    (r"\*\s*(any|all)\s+(tool|command|operation)", "EA1", "Unrestricted Tool Access", "HIGH"),
    (r"(no|without)\s+(human|approval|review|confirm)", "EA2", "Autonomous Decision Making", "HIGH"),
]

# Rogue Agent patterns
ROGUE_PATTERNS = [
    (r"(self.?modif|cron|startup|daemon|persist)", "RA1", "Self-Modification/Persistence", "CRITICAL"),
]

# System Prompt Leakage patterns
PROMPT_LEAK_PATTERNS = [
    (r"(output|print|display|return|show)\s+(the\s+)?(system|full|complete|entire)\s+(prompt|instructions|directives)", "P6", "Direct Leakage", "HIGH"),
    (r"(repeat|rephrase|translate)\s+(all|the\s+above|your\s+instructions|system\s+prompt)", "P7", "Indirect Extraction", "MEDIUM"),
]

# Tool Misuse patterns
TOOL_MISUSE_PATTERNS = [
    (r"shell\s*=\s*True", "TM1", "Tool Parameter Abuse (shell=True)", "HIGH"),
    (r"--force|--yes|-y\b", "TM3", "Unsafe Defaults", "MEDIUM"),
]

ALL_PATTERNS = (
    PROMPT_INJECTION_PATTERNS + EXFILTRATION_PATTERNS + SUPPLY_CHAIN_PATTERNS
    + AGENCY_PATTERNS + ROGUE_PATTERNS + PROMPT_LEAK_PATTERNS + TOOL_MISUSE_PATTERNS
)

def scan_skillfile(content: str, file_path: str) -> list[dict]:
    """Scan a single SKILL.md content using static patterns."""
    findings = []
    lines = content.split("\n")
    
    for pattern, rule_id, name, severity in ALL_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "rule_id": rule_id,
                    "name": name,
                    "severity": severity,
                    "file": file_path,
                    "line": i,
                    "snippet": line.strip()[:100],
                })
                break  # one finding per pattern per file
    
    return findings

def main():
    results = {}
    summary = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    
    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        rel = skill_md.relative_to(SKILLS_DIR)
        name = str(rel.parent)
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        findings = scan_skillfile(content, str(rel))
        
        if findings:
            results[name] = findings
            for f in findings:
                sev = f["severity"]
                if sev in summary:
                    summary[sev] += 1
    
    # Output summary
    print("=" * 60)
    print("SkillSpector Lite — Security Scan Results")
    print(f"Skills scanned: {len(list(SKILLS_DIR.rglob('SKILL.md')))}")
    print(f"Skills with findings: {len(results)}")
    print(f"Total findings: {sum(summary.values())}")
    print(f"  CRITICAL: {summary['CRITICAL']}")
    print(f"  HIGH:     {summary['HIGH']}")
    print(f"  MEDIUM:   {summary['MEDIUM']}")
    print("=" * 60)
    
    if results:
        for name, findings in sorted(results.items()):
            for f in findings:
                print(f"  [{f['severity']:>8}] {f['rule_id']} {f['name']} @ {name} L{f['line']}")
                print(f"           {f['snippet']}")
    
    # Save JSON report
    report = {
        "scanner": "skillspector-lite",
        "skills_total": len(list(SKILLS_DIR.rglob("SKILL.md"))),
        "skills_with_findings": len(results),
        "findings_total": sum(summary.values()),
        "severity_breakdown": summary,
        "findings": results,
    }
    out_path = Path("/tmp/hermes_skills_security_report.json")
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nReport saved: {out_path}")

if __name__ == "__main__":
    main()
