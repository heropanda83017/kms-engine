# KMS Engine

> 知识管理系统 — 统一入口管理笔记 → 链接 → wiki 同步
> 类似 investment-engine 的集中化结构

## 目录结构

```
kms-engine/
├── _path_setup.py      集中式路径管理
├── scripts/             KMS 工具脚本
│   ├── kms.py           统一入口 (python kms.py --help)
│   ├── wiki-link.py     wiki 双向链接生成
│   ├── archive_note.py  笔记归档分类
│   ├── fill_note.py     LLM 笔记填充
│   ├── fuse.py          笔记融合
│   ├── process_xhs_video.py  视频处理管线
│   └── export_xhs_cookies.py Cookie导出
├── config/              配置文件
│   └── .link_registry.json  链接注册表
├── templates/           笔记模板
│   └── 笔记模板_v2.md
└── docs/                文档
    └── KMS使用指南.md
```

## 快速使用

```bash
cd E:/AIGC-KB/kms-engine
python scripts/kms.py status      # 查看系统状态
python scripts/kms.py link        # 更新 wiki 链接
python scripts/kms.py fuse        # 笔记融合
python scripts/kms.py search <关键词>  # 全文检索
python scripts/kms.py cleanup     # 清理缓存
```

## 外部依赖

- wiki: `E:/AIGC-KB/wiki-AIGC-KB/`
- 工作笔记: `E:/AIGC-KB/输出/01-学习笔记/`
- 主代码库: `E:/AIGC-KB/output/investment-engine/`