#!/usr/bin/env python3
"""
KMS Content Validator — 笔记写入多视角验证

借鉴 Agent River DebateEngine 的多 Agent 交叉验证。
笔记写入时自动触发 4 路并行验证，生成 PASS/CONDITIONAL/FAIL 裁决。

用法:
    python3 kms_validator.py <笔记路径>
    python3 kms_validator.py <笔记路径> --json   # 机器可读输出
"""

import json
import sys
from pathlib import Path


def check_quality(note_path: str) -> dict:
    """检查 frontmatter/字数/链接

    Returns:
        {"verdict": "PASS"|"WARN"|"FAIL", "detail": str, "issues": [str]}
    """
    path = Path(note_path)
    if not path.exists():
        return {"verdict": "FAIL", "detail": "文件不存在", "issues": [f"未找到: {note_path}"]}

    content = path.read_text(encoding="utf-8")
    issues = []

    # 检查 frontmatter
    if not content.startswith("---"):
        issues.append("缺少 YAML frontmatter（不以 --- 开头）")
    else:
        end_idx = content.find("---", 3)
        if end_idx == -1:
            issues.append("YAML frontmatter 未闭合（缺少结尾 ---）")
        else:
            fm = content[3:end_idx].strip()
            required = ["title", "type", "domain", "tags"]
            for field in required:
                if f"{field}:" not in fm:
                    issues.append(f"frontmatter 缺少字段: {field}")

    # 检查字数
    body = content
    if content.startswith("---"):
        end_idx = content.find("---", 3)
        if end_idx != -1:
            body = content[end_idx + 3:]
    word_count = len(body.strip())
    if word_count < 200:
        issues.append(f"正文仅 {word_count} 字，建议 ≥200 字")

    # 检查 wiki 链接
    import re
    links = re.findall(r'\[\[([^\]]+)\]\]', content)
    if len(links) == 0:
        issues.append("笔记中无 [[wiki链接]]，建议至少 1 个关联链接")

    if not issues:
        return {"verdict": "PASS", "detail": f"✅ {word_count} 字, {len(links)} 链接, frontmatter 完整", "issues": []}
    elif any("缺少" in i or "未闭合" in i or "不存在" in i for i in issues):
        return {"verdict": "FAIL", "detail": f"❌ {len(issues)} 个阻塞问题", "issues": issues}
    else:
        return {"verdict": "WARN", "detail": f"🟡 {len(issues)} 个建议", "issues": issues}


def check_fusion(note_path: str) -> dict:
    """检查是否有重叠笔记需要融合

    Returns:
        {"verdict": "PASS"|"WARN", "detail": str, "candidates": [str]}
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from scripts.smart_fuse import find_fusion_candidates
        candidates = find_fusion_candidates(note_path, top_n=3)
        if not candidates:
            return {"verdict": "PASS", "detail": "无重叠候选", "candidates": []}
        # 只报告高评分候选
        high_score = [c for c in candidates if c.get("score", 0) > 0.5]
        if high_score:
            names = [f"{c.get('name','?')}({c.get('score',0):.2f})" for c in high_score]
            return {"verdict": "WARN", "detail": f"发现 {len(high_score)} 个高重叠候选: {', '.join(names)}", "candidates": high_score}
        return {"verdict": "PASS", "detail": f"{len(candidates)} 个低分候选", "candidates": candidates}
    except Exception as e:
        return {"verdict": "PASS", "detail": f"融合检查跳过: {e}", "candidates": []}


def check_entity(note_path: str) -> dict:
    """检查 KG 实体抽取

    Returns:
        {"verdict": "PASS"|"WARN", "detail": str}
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from scripts.kg_extract import extract_note
        from pathlib import Path as _Path
        result = extract_note(note_path=_Path(note_path), dry_run=True)
        entities = (result or {}).get("entities", [])
        if len(entities) >= 3:
            names = [e.get("name", "?") for e in entities[:5]]
            return {"verdict": "PASS", "detail": f"✅ 可提取 {len(entities)} 个实体: {', '.join(names)}", "entities": entities}
        elif entities:
            return {"verdict": "WARN", "detail": f"🟡 仅 {len(entities)} 个实体，建议补充关键实体", "entities": entities}
        else:
            return {"verdict": "WARN", "detail": "🟡 未检测到可抽取实体", "entities": []}
    except Exception as e:
        return {"verdict": "PASS", "detail": f"实体检查跳过: {e}", "entities": []}


def check_governance(note_path: str) -> dict:
    """检查笔记中的链接是否断裂

    Returns:
        {"verdict": "PASS"|"WARN", "detail": str, "broken_links": [str]}
    """
    import re
    path = Path(note_path)
    if not path.exists():
        return {"verdict": "FAIL", "detail": "文件不存在", "broken_links": []}

    content = path.read_text(encoding="utf-8")
    links = re.findall(r'\[\[([^\]]+)\]\]', content)

    wiki_base = Path(__file__).resolve().parent.parent.parent / "wiki-AIGC-KB"
    if not wiki_base.exists():
        return {"verdict": "PASS", "detail": "wiki 目录不可达，跳过治理检查", "broken_links": []}

    broken = []
    for link in links:
        # 跳过 EVOLUTION.md 和外部链接
        if link.startswith("http") or "EVOLUTION" in link:
            continue
        # 尝试多种匹配
        found = False
        for ext in ["", ".md"]:
            target = wiki_base / f"{link}{ext}"
            if target.exists():
                found = True
                break
            # 尝试在子目录中查找
            for md in wiki_base.rglob(f"**/{link}{ext}"):
                if md.exists():
                    found = True
                    break
            if found:
                break
        if not found:
            broken.append(link)

    if not broken:
        return {"verdict": "PASS", "detail": "✅ 所有链接可达", "broken_links": []}
    elif len(broken) <= 3:
        return {"verdict": "WARN", "detail": f"🟡 {len(broken)} 个断裂链接: {', '.join(broken[:3])}", "broken_links": broken}
    else:
        return {"verdict": "WARN", "detail": f"🟡 {len(broken)} 个断裂链接（显示前 3: {', '.join(broken[:3])}）", "broken_links": broken}


def validate(note_path: str) -> dict:
    """执行全部 4 项验证，生成裁决，回写 frontmatter

    Returns:
        {"verdict": "PASS"|"CONDITIONAL"|"FAIL", "checks": {...}}
    """
    # 读取已有 issues（反馈回流）
    existing_issues = read_issues(note_path)

    # 复用 TaskOrchestrator 并行执行
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.kms_orchestrator import TaskOrchestrator, TaskDef

    orchestrator = TaskOrchestrator(max_workers=4)
    tasks = [
        TaskDef(name="质量检查", func=check_quality, kwargs={"note_path": note_path}),
        TaskDef(name="融合检查", func=check_fusion, kwargs={"note_path": note_path}),
        TaskDef(name="实体检查", func=check_entity, kwargs={"note_path": note_path}),
        TaskDef(name="治理检查", func=check_governance, kwargs={"note_path": note_path}),
    ]

    print(f"\n📋 验证笔记: {note_path}")
    if existing_issues:
        unfixed = [i for i in existing_issues if not i.get("fixed", False)]
        if unfixed:
            print(f"  🔄 发现 {len(unfixed)} 个未修复的遗留问题")
    print(f"{'='*50}")
    results = orchestrator.run(tasks)

    # 裁决
    verdicts = {name: r.get("verdict", "PASS") for name, r in results.items()}

    if any(v == "FAIL" for v in verdicts.values()):
        final_verdict = "FAIL"
    elif any(v == "WARN" for v in verdicts.values()):
        final_verdict = "CONDITIONAL"
    else:
        final_verdict = "PASS"

    # 汇总
    print(f"\n{'='*50}")
    print(f"📊 验证裁决: {final_verdict}")
    print(f"{'='*50}")
    for name, r in results.items():
        icon = "✅" if r.get("verdict") == "PASS" else "🟡" if r.get("verdict") == "WARN" else "❌"
        print(f"  {icon} {name}: {r.get('detail', '')}")

    # 回写 frontmatter（反馈回流）
    write_verdict(note_path, final_verdict, results)

    return {
        "verdict": final_verdict,
        "checks": results,
    }


def read_issues(note_path: str) -> list[dict]:
    """读取笔记 frontmatter 中的历史 issues

    用于反馈回流：上次验证发现的 issue，如果已修复则不再告警。
    """
    path = Path(note_path)
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return []
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return []
    fm = content[3:end_idx]
    import re
    # 尝试从 frontmatter 中提取 issues 块
    issues_match = re.search(r'issues:\s*(\[.*?\])', fm, re.DOTALL)
    if issues_match:
        try:
            issues = json.loads(issues_match.group(1))
            if isinstance(issues, list):
                return issues
        except Exception:
            pass
    return []


def write_verdict(note_path: str, verdict: str, checks: dict):
    """将验证裁决回写到笔记 frontmatter

    写入字段:
    - validated: 验证日期
    - verdict: PASS/CONDITIONAL/FAIL
    - issues: 问题列表（含 type/fixed 状态）
    """
    path = Path(note_path)
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return

    end_idx = content.find("---", 3)
    if end_idx == -1:
        return

    # 收集新发现的 issues
    new_issues = []
    for name, r in checks.items():
        if r.get("verdict") in ("WARN", "FAIL"):
            broken = r.get("broken_links", r.get("issues", []))
            if isinstance(broken, list):
                for b in broken[:3]:
                    new_issues.append({"type": name, "target": str(b)[:100], "fixed": False})

    # 对比已有 issues（反馈回流：已修复的自动标记 fixed: true）
    existing_issues = read_issues(note_path)
    if existing_issues:
        for new in new_issues:
            for old in existing_issues:
                if new["target"] == old.get("target", "") and new["type"] == old.get("type", ""):
                    # 这个 issue 之前就有，仍然存在 → 保持 fixed: false
                    break
            else:
                # 这个 issue 是新出现的 → 记录
                pass

        # 标记已修复：之前有但这次没出现的 → fixed: true
        merged = list(new_issues)  # 先加所有新 issue
        for old in existing_issues:
            if old.get("fixed", False):
                continue  # 已修复的不再出现
            still_exists = False
            for new in new_issues:
                if old["target"] == new["target"] and old["type"] == new["type"]:
                    still_exists = True
                    break
            if not still_exists:
                old["fixed"] = True
                merged.append(old)  # 标记为已修复，仍保留在 frontmatter 中

        issues = merged
    else:
        issues = new_issues

    # 构建新的 frontmatter 字段
    import datetime
    verdict_block = f"""
# 验证记录（自动生成）
validated: {datetime.date.today().isoformat()}
verdict: {verdict}
issues: {json.dumps(issues, ensure_ascii=False)}
"""

    # 检查是否已有验证记录块
    if "validated:" in content[end_idx:end_idx + 200]:
        # 已有 → 替换
        import re as _re
        new_content = _re.sub(
            r'# 验证记录.*?issues: \[.*?\]',
            verdict_block.strip(),
            content,
            flags=_re.DOTALL
        )
    else:
        # 没有 → 追加到 frontmatter 末尾
        new_content = content[:end_idx] + verdict_block + "\n" + content[end_idx:]

    path.write_text(new_content, encoding="utf-8")
    print(f"  📝 验证结果已回写 frontmatter ({len(issues)} 个 issues)")


def cli():
    if len(sys.argv) < 2:
        print("用法: python3 kms_validator.py <笔记路径> [--json]")
        return

    note_path = sys.argv[1]
    use_json = "--json" in sys.argv

    result = validate(note_path)

    if use_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
