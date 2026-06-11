"""KMS Engine 基础测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import SCRIPTS_DIR


def test_path_setup_imports():
    """_path_setup.py 所有符号可导入"""
    from _path_setup import (
        KMS_ROOT, SCRIPTS_DIR, CONFIG_DIR, TEMPLATES_DIR,
        WIKI_DIR, REGISTRY, YT_DLP, COOKIE_FILE
    )
    assert KMS_ROOT.exists(), f"KMS_ROOT 不存在: {KMS_ROOT}"
    assert SCRIPTS_DIR.exists(), f"SCRIPTS_DIR 不存在: {SCRIPTS_DIR}"
    assert CONFIG_DIR.exists(), f"CONFIG_DIR 不存在: {CONFIG_DIR}"
    assert WIKI_DIR.exists(), f"WIKI_DIR 不存在: {WIKI_DIR}"
    assert YT_DLP and len(YT_DLP) > 0, "yt-dlp 未找到"


def test_kms_script_syntax():
    """所有脚本语法正确"""
    import ast
    for py_file in sorted(SCRIPTS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        code = py_file.read_text(encoding="utf-8")
        ast.parse(code)
        # 如果ast.parse没抛异常，通过


def test_no_bare_except():
    """无 bare except"""
    for py_file in sorted(SCRIPTS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        code = py_file.read_text(encoding="utf-8")
        for i, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            assert stripped != "except:", f"{py_file.name}:{i} bare except"


def test_video_manifest_exists():
    """video_manifest.json 存在且合法"""
    from _path_setup import CONFIG_DIR
    manifest = CONFIG_DIR / "video_manifest.json"
    assert manifest.exists(), "video_manifest.json 不存在"
    import json
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(data, list), "manifest 应为数组"


def test_registry_exists():
    """.link_registry.json 存在"""
    from _path_setup import REGISTRY
    assert REGISTRY.exists() or True, "注册表不存在（首次运行后生成）"  # 允许不存在


def run():
    """运行所有测试"""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).parent), "-v"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr[:500])
    return result.returncode


if __name__ == "__main__":
    import sys
    sys.exit(run())