#!/usr/bin/env python3
"""
KMS 路径配置 — 所有硬编码路径统一管理

用法:
    from _path_setup import (
        KMS_ROOT, WIKI_DIR, OUTPUT_DIR, IE_DIR,
        SCRIPTS_DIR, CONFIG_DIR, TEMPLATES_DIR
    )
"""
from pathlib import Path

# ── 根目录（基于本文件位置自动推导，消除硬编码）──
KMS_ROOT = Path(__file__).resolve().parent.parent          # kms-engine/
SCRIPTS_DIR = KMS_ROOT / "scripts"                          # kms-engine/scripts/
CONFIG_DIR = KMS_ROOT / "config"                            # kms-engine/config/
TEMPLATES_DIR = KMS_ROOT / "templates"                      # kms-engine/templates/

# ── 外部依赖目录（基于 KMS_ROOT 推导）──
WIKI_DIR = KMS_ROOT.parent / "wiki-AIGC-KB"                 # AIGC-KB/wiki-AIGC-KB/
OUTPUT_DIR = KMS_ROOT.parent / "输出"                       # AIGC-KB/输出/
IE_DIR = KMS_ROOT.parent / "investment-engine"               # AIGC-KB/investment-engine/

# ── 推荐用法 ──
# 所有脚本统一从此文件导入路径，而非硬编码。
# 新增路径时只需在此文件添加一行，所有脚本自动获得。
