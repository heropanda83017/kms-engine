"""
KMS Engine — 集中式路径管理
类似于 investment-engine 的 _path_setup.py

路径兼容: Windows 原生 + WSL (自动检测转换)
"""

from pathlib import Path
import sys, platform

# ── WSL 路径兼容 ─────────────────────────────────────
# Windows 上 E:/ 直接可用，WSL/Linux 上需 /mnt/e/
_IS_WINDOWS = platform.system() == "Windows"

def _win_to_posix(raw: str) -> str:
    """E:/AIGC-KB/... → /mnt/e/AIGC-KB/... (仅在非Windows下转换)"""
    if _IS_WINDOWS:
        return raw
    # 匹配 X:/... 或 X:\... 前缀
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        drive = raw[0].lower()
        rest = raw[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return raw

# ── 根目录 ───────────────────────────────────────────
KMS_ROOT = Path(__file__).resolve().parent

# ── 核心子目录 ────────────────────────────────────────
SCRIPTS_DIR = KMS_ROOT / "scripts"
CONFIG_DIR = KMS_ROOT / "config"
TEMPLATES_DIR = KMS_ROOT / "templates"
DOCS_DIR = KMS_ROOT / "docs"

# ── 外部依赖路径（自动兼容 WSL） ─────────────────────
OUTPUT_DIR = Path(_win_to_posix(r"E:/AIGC-KB/输出"))
WIKI_DIR = Path(_win_to_posix(r"E:/AIGC-KB/wiki-AIGC-KB"))

# ── KMS 注册表 ────────────────────────────────────────
REGISTRY = CONFIG_DIR / ".link_registry.json"

# ── 工作目录 ──────────────────────────────────────────
LEARNING_NOTES = OUTPUT_DIR / "01-学习笔记"
NOTES_DIR = OUTPUT_DIR / "01-学习笔记"

# 确保 scripts/ 在 sys.path 中
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# ── 工具路径（自动发现 + 硬编码兜底） ──────────────
import shutil
YT_DLP = shutil.which("yt-dlp") or _win_to_posix(
    r"C:\Program Files\Python312\Scripts\yt-dlp.exe"
)
FFMPEG = shutil.which("ffmpeg") or None  # 会通过 imageio-ffmpeg 自动发现

# ── Cookie 路径 ────────────────────────────────────────
COOKIE_FILE = str(Path.home() / "xiaohongshu_cookies.txt")

# ── Edge 路径（仅 Win 有效，WSL 下不用） ────────────
EDGE_PATH = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if _IS_WINDOWS
    else ""
)

# ── 缓存 ──────────────────────────────────────────────
WHISPER_CACHE_DIR = str(Path.home() / ".cache" / "huggingface" / "hub")

# ── HF 镜像 ──────────────────────────────────────────
HF_ENDPOINT = "https://hf-mirror.com"

# ── 创建必要目录 ──────────────────────────────────────
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = CONFIG_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Checkpoint 子目录 ──────────────────────────────────
CHECKPOINT_DIR = CACHE_DIR / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
