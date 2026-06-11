# KMS 使用指南

## 概述

KMS Engine 是知识管理系统的集中化引擎，统一管理笔记处理、wiki链接更新、笔记融合等工作流。

## 脚本说明

| 脚本 | 功能 | 调用方式 |
|:-----|:-----|:---------|
| `kms.py` | 统一入口 | `python scripts/kms.py <命令>` |
| `wiki-link.py` | wiki双向链接生成 | `python scripts/kms.py link` |
| `archive_note.py` | 笔记归档 | 由 kms.py 自动调用 |
| `fill_note.py` | LLM笔记填充 | 由 video 管线调用 |
| `fuse.py` | 笔记融合 | `python scripts/kms.py fuse` |
| `process_xhs_video.py` | 视频处理 | 由 kms video 管线调用 |
| `export_xhs_cookies.py` | Cookie导出 | 一次性设置 |

## 路径配置

所有路径集中在 `_path_setup.py` 管理。如需修改，只改这一个文件。