#!/usr/bin/env python3
"""
KMS Output Guard — 笔记写入前的敏感信息检测

借鉴 Agent River 的 LeakDetection，扫描笔记内容中的敏感模式。

用法:
    python3 kms_guard.py 笔记路径        # 检测敏感信息
    python3 kms_guard.py 笔记路径 --fix  # 替换敏感信息为 [REDACTED]
"""

import re
import sys
from pathlib import Path


# 敏感模式列表
LEAK_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', 'API Key (sk-***)'),
    (r'ghp_[a-zA-Z0-9]{36}', 'GitHub Token (ghp_***)'),
    (r'gho_[a-zA-Z0-9]{36}', 'GitHub OAuth Token'),
    (r'xox[baprs]-[a-zA-Z0-9\-]{24,}', 'Slack Token'),
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key'),
    (r'-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----', 'Private Key'),
    (r'eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+', 'JWT Token'),
]


def scan(note_path: str) -> list[dict]:
    """扫描笔记中的敏感信息

    Returns:
        [{"pattern": str, "line": int, "preview": str}, ...]
    """
    path = Path(note_path)
    if not path.exists():
        return [{"pattern": "文件不存在", "line": 0, "preview": str(note_path)}]

    findings = []
    lines = path.read_text(encoding="utf-8").split("\n")

    for i, line in enumerate(lines, 1):
        for pattern, desc in LEAK_PATTERNS:
            match = re.search(pattern, line)
            if match:
                preview = line[:60].strip()
                findings.append({
                    "pattern": desc,
                    "line": i,
                    "preview": preview,
                })
                break  # 每行只报告第一个匹配

    return findings


def fix(note_path: str) -> int:
    """替换笔记中的敏感信息

    Returns:
        替换数量
    """
    path = Path(note_path)
    if not path.exists():
        return 0

    content = path.read_text(encoding="utf-8")
    original = content
    count = 0

    for pattern, desc in LEAK_PATTERNS:
        new_content, n = re.subn(pattern, f"[REDACTED:{desc}]", content)
        if n > 0:
            count += n
            content = new_content

    if count > 0:
        path.write_text(content, encoding="utf-8")
        print(f"  🔒 已替换 {count} 处敏感信息: {note_path}")

    return count


def cli():
    if len(sys.argv) < 2:
        print("用法: python3 kms_guard.py <笔记路径> [--fix]")
        return

    note_path = sys.argv[1]
    do_fix = "--fix" in sys.argv

    if do_fix:
        count = fix(note_path)
        if count == 0:
            print(f"  ✅ 无敏感信息: {note_path}")
    else:
        findings = scan(note_path)
        if findings:
            print(f"  🔴 发现 {len(findings)} 处敏感信息:")
            for f in findings:
                print(f"    L{f['line']}: {f['pattern']} → \"{f['preview']}\"")
        else:
            print(f"  ✅ 无敏感信息: {note_path}")


if __name__ == "__main__":
    cli()
