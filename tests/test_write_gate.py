"""KMS Engine 写入门禁测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from kms import validate_frontmatter, validate_content, validate_note, check_write_gate


# ── validate_frontmatter ─────────────────────────

def test_fm_valid():
    """完整 frontmatter → 空列表"""
    fm = {"type": "research", "domain": "投资研究", "tags": ["AI", "test"]}
    assert validate_frontmatter(fm) == []


def test_fm_missing_type():
    """缺 type → 报错"""
    fm = {"domain": "投资研究", "tags": ["AI"]}
    assert "type" in validate_frontmatter(fm)


def test_fm_missing_domain():
    """缺 domain → 报错"""
    fm = {"type": "research", "tags": ["AI"]}
    assert "domain" in validate_frontmatter(fm)


def test_fm_missing_tags():
    """缺 tags → 报错"""
    fm = {"type": "research", "domain": "投资研究"}
    missing = validate_frontmatter(fm)
    assert "tags" in missing


def test_fm_empty_tags():
    """tags 为空列表 → 报错"""
    fm = {"type": "research", "domain": "投资研究", "tags": []}
    assert "tags(非空)" in validate_frontmatter(fm)


def test_fm_empty_tags_string():
    """tags 为空字符串 → 报错"""
    fm = {"type": "research", "domain": "投资研究", "tags": "  "}
    assert "tags(非空)" in validate_frontmatter(fm)


def test_fm_multiple_missing():
    """缺多个字段 → 返回全部缺失"""
    missing = validate_frontmatter({})
    assert "type" in missing
    assert "domain" in missing
    assert "tags" in missing


# ── validate_content ────────────────────────────

def test_content_valid():
    """正文充足 + 含链接 → 空列表"""
    body = "这是一段完整的笔记正文。内容非常充足。" * 20 + "\n参考[[EVOLUTION]]相关文档\n"
    violations = validate_content(body)
    assert violations == [], f"期望空列表, 得到: {violations}"


def test_content_too_short():
    """正文不足 200 字 → 报错"""
    body = "太短了[[test]]"
    violations = validate_content(body)
    assert any("不足" in v for v in violations)


def test_content_no_links():
    """正文不含链接 → 报错"""
    body = "这是一篇完整的笔记正文，内容充足。" * 50
    violations = validate_content(body)
    assert any("链接" in v for v in violations)


def test_content_short_and_no_links():
    """正文不足 + 无链接 → 两个报错"""
    body = "很短"
    violations = validate_content(body)
    assert len(violations) == 2


def test_content_custom_min_chars():
    """自定义最小字数"""
    body = "短[[test]]"
    assert validate_content(body, min_chars=5) == []  # 5字, 够
    violations = validate_content(body, min_chars=100)  # 100字, 不够
    assert any("不足" in v for v in violations)


# ── validate_note ───────────────────────────────

def test_note_valid():
    """完整笔记 → pass"""
    content = """---
title: Test
type: research
domain: 投资研究
tags: [test]
---
这是一篇完整的笔记正文，内容充足。包含参考链接。
参考[[EVOLUTION]]相关文档。
""" * 10
    # Make it long enough
    base = "这是一篇完整的笔记正文。" * 20 + "\n参考[[EVOLUTION]]相关文档。\n"
    long_content = f"""---
title: Test
type: research
domain: 投资研究
tags: [test]
---
{base * 15}"""
    result = validate_note(long_content)
    assert result["pass"] is True, f"期望通过, 得到: {result['issues']}"
    assert len(result["issues"]) == 0


def test_note_no_frontmatter():
    """无 frontmatter → fail"""
    content = "## 正文\n没有frontmatter"
    result = validate_note(content)
    assert result["pass"] is False
    assert any("frontmatter" in i for i in result["issues"])


def test_note_empty():
    """空内容 → fail"""
    result = validate_note("")
    assert result["pass"] is False


def test_note_partial_frontmatter():
    """部分 frontmatter → fail"""
    content = """---
title: Test
tags: [a]
---
short"""
    result = validate_note(content)
    assert result["pass"] is False
    assert "domain" in str(result["issues"]) or "type" in str(result["issues"])


# ── check_write_gate ────────────────────────────

def test_gate_valid():
    """check_write_gate 返回通过消息"""
    base = "这是一篇完整的笔记正文。" * 20 + "\n参考[[EVOLUTION]]相关文档。\n"
    content = f"""---
title: Test
type: research
domain: 投资研究
tags: [test]
---
{base * 15}"""
    msg = check_write_gate(content)
    assert "通过" in msg


def test_gate_rejected():
    """check_write_gate 返回拒绝消息"""
    content = "---\n---\n短"
    msg = check_write_gate(content)
    assert "拒绝" in msg
