"""KMS Engine 健康检查测试"""
import sys, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tempfile


def _make_test_wiki():
    """创建临时 wiki 目录供测试"""
    tmp = Path(tempfile.mkdtemp())

    # 文件A: 有frontmatter + 链接 (入链=0, 会被检测为孤立)
    a = tmp / "a.md"
    a.write_text("""---
title: A
type: research
domain: test
tags: [t1]
---
内容A第一部分。内容A第二部分。内容A第三部分。内容A第四部分。
内容A第五部分。内容A第六部分。内容A第七部分。内容A第八部分。
内容A第九部分。内容A第十部分。内容A第十一部分。内容A第十二部分。
内容A第十三部分。内容A第十四部分。内容A第十五部分。内容A第十六部分。
内容A第十七部分。内容A第十八部分。内容A第十九部分。内容A第二十部分。
参考[[b]] [[c]]相关笔记。这是一个比较长的内容来确保正文超过200字符阈值。""", encoding="utf-8")

    # 文件B: 被A引用 (入链=1, 非孤立)
    b = tmp / "b.md"
    b.write_text("""---
title: B
type: note
domain: test
tags: [t2]
---
内容B第一部分。内容B第二部分。内容B第三部分。内容B第四部分。
内容B第五部分。内容B第六部分。内容B第七部分。内容B第八部分。
参考[[c]]相关笔记。这是一段比较长的内容来确保超过200字的阈值。""", encoding="utf-8")

    # 文件C: 被A和B引用 (入链=2, 非孤立)
    c = tmp / "c.md"
    c.write_text("""---
title: C
type: note
domain: test
tags: [t3]
---
内容C第一部分。内容C第二部分。内容C第三部分。内容C第四部分。
内容C第五部分。内容C第六部分。内容C第七部分。内容C第八部分。
这是C的内容，来确保超过200字的阈值。内容C的内容还算充足。""", encoding="utf-8")

    # 文件D: 无入链 (孤立)
    d = tmp / "d.md"
    d.write_text("""---
title: D
type: note
domain: test
tags: [t4]
---
内容D第一部分。内容D第二部分。内容D第三部分。内容D第四部分。
内容D第五部分。内容D第六部分。内容D第七部分。内容D第八部分。
这是D的内容，来确保超过200字的阈值。内容D的内容还算充足。""", encoding="utf-8")

    return tmp


def test_orphan_detection():
    """孤立文件检测: D 是孤岛, A/B/C 不是"""
    import inspect
    from health_check import find_md_files, build_link_index, check_orphan

    wiki = _make_test_wiki()

    # monkey-patch WIKI path
    import health_check
    original = health_check.WIKI
    health_check.WIKI = wiki

    try:
        files = find_md_files()
        assert len(files) == 4

        link_index = build_link_index(files)
        orphans = check_orphan(files, link_index)

        orphan_paths = {o["path"] for o in orphans}
        assert "a.md" in orphan_paths or "d.md" in orphan_paths, "A 和 D 均无入链"
        assert "b.md" not in orphan_paths, "B 被A引用, 非孤立"
        assert "c.md" not in orphan_paths, "C 被A和B引用, 非孤立"
    finally:
        health_check.WIKI = original
        import shutil
        shutil.rmtree(wiki)


def test_no_fm_detection():
    """无 frontmatter 检测"""
    from health_check import find_md_files, check_no_fm

    wiki = _make_test_wiki()

    import health_check
    original = health_check.WIKI
    health_check.WIKI = wiki

    try:
        files = find_md_files()
        no_fm = check_no_fm(files)
        no_fm_paths = {n["path"] for n in no_fm}
        # 所有 _make_test_wiki 的文件都有 frontmatter
        assert "a.md" not in no_fm_paths
        assert "b.md" not in no_fm_paths
    finally:
        health_check.WIKI = original
        import shutil
        shutil.rmtree(wiki)


def test_shell_detection():
    """空壳文件检测"""
    from health_check import find_md_files, check_shell

    wiki = _make_test_wiki()
    # 添加一个真正的空壳文件
    shell_f = wiki / "shell.md"
    shell_f.write_text("短", encoding="utf-8")

    import health_check
    original = health_check.WIKI
    health_check.WIKI = wiki

    try:
        files = find_md_files()
        shells = check_shell(files)
        shell_paths = {s["path"] for s in shells}
        assert "shell.md" in shell_paths, "shell.md 应为空壳"
        assert "a.md" not in shell_paths, "a.md 正文充足"
    finally:
        health_check.WIKI = original
        import shutil
        shutil.rmtree(wiki)


def test_broken_links_detection():
    """断裂链接检测: [[non_existent]] 应被检测"""
    from health_check import find_md_files, check_broken_links

    wiki = _make_test_wiki()

    import health_check
    original = health_check.WIKI
    health_check.WIKI = wiki

    try:
        files = find_md_files()
        broken = check_broken_links(files)

        # 文件A中 [[b]] 和 [[c]] 都存在, 无断裂
        # 但链接方式可能需要检查 — 实际上 b.md 和 c.md 都存在
        # 所以 A 的链接是完整的
        # 我们加一个真正断裂的
        e = wiki / "e.md"
        e.write_text("""---
title: E
type: note
domain: test
tags: [t]
---
参考[[non_existent_file]]""", encoding="utf-8")

        files2 = find_md_files()
        broken2 = check_broken_links(files2)
        broken_targets = [b["target"] for b in broken2]
        assert "non_existent_file" in broken_targets
        assert any("e.md" in b["source"] for b in broken2)
    finally:
        health_check.WIKI = original
        import shutil
        shutil.rmtree(wiki)
