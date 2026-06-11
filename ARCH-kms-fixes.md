# ARCH: kms-engine 体系修复
> 生成: 2026-05-28 | 基于 V4 Pro 审计报告 (4.5/10)

## 现状
KMS Engine 刚刚从散落位置集中到统一目录，V4 Pro 全量审计发现 6 大类问题：
- P0: 5个脚本路径导入链断裂（parent.parent.parent 应为 parent.parent）
- P1: 双注册表冲突、硬编码路径、bare except、open() 无with、subprocess无错误检查
- P2: 缺失 requirements.txt / __init__.py / .gitignore、文档不一致

## 修复方案 (6 Phase)

Phase 1: 路径导入修复 (5个脚本)
- archive_note.py, fill_note.py, fuse.py, process_xhs_video.py, wiki-link.py
- .parent.parent.parent → .parent.parent
- 同时清理重复 import

Phase 2: 双注册表冲突
- wiki-link.py: 移除 REGISTRY 覆盖行，统一使用 _path_setup.py

Phase 3: 硬编码路径 → _path_setup.py 集中管理
- yt-dlp/shutil.which() 动态发现
- cookie/edge/whisper 路径使用 Path.home()
- HF_ENDPOINT 移入 main() 避免 import 时副作用

Phase 4: 代码质量
- bare except → except Exception / except (UnicodeDecodeError, OSError)
- open() → Path.read_text()
- subprocess returncode 检查
- 移除未使用 import

Phase 5: 补全缺失基础设施
- requirements.txt, scripts/__init__.py, config/__init__.py, .gitignore

Phase 6: 文档同步
- README.md/docs 移除不存在命令引用

## 影响分析
- 所有脚本的路径引用方式改变，需验证 import 链
- _path_setup.py 成为唯一路径配置入口
- 无 API 或数据格式变更

## 验收标准
1. ast.parse 所有 10 个 .py 文件通过
2. from _path_setup import ... 实际加载成功
3. 无 parent.parent.parent 残余
4. 无 bare except 残余
5. requirements.txt / __init__.py / .gitignore 存在
6. V4 Pro FINAL REVIEW 确认

## ARCH REVIEW 结论: CONDITIONAL APPROVED (7/10)
### 已处理条件

| # | 条件 | 处理 |
|:-:|:-----|:-----|
| 1 | HF_ENDPOINT 移入 main() 副作用 | 已在 Phase 3 标注：Whisper 调用经过统一入口 process_xhs_video.py main() |
| 2 | Cronjob 路径审计 | 见下方 cronjob 检查结果 |
| 3 | 全部 .py 清单 | 10个: _path_setup.py, kms.py, archive_note.py, fill_note.py, fuse.py, process_xhs_video.py, wiki-link.py, export_xhs_cookies.py, scripts/__init__.py, config/__init__.py |
| 4 | 验收标准6 替换 | 替换为: "python -c 'from _path_setup import *' 无错误 + python scripts/kms.py status 可执行" |
| 5 | Edge cookie 路径 | 使用 os.environ.get("LOCALAPPDATA") 而非 Path.home() |

### Cronjob 检查
```

┌─────────────────────────────────────────────────────────────────────────┐
│                         Scheduled Jobs                                  │
└─────────────────────────────────────────────────────────────────────────┘

  9768bcc27709 [active]
    Name:      ie-daily-pipeline
    Schedule:  30 15 * * 1-5
    Repeat:    ∞
    Next run:  2026-05-27T15:30:00+08:00
    Deliver:   local
    Script:    pipelines/daily_pipeline.py
    Workdir:   E:\AIGC-KB\输出\investment-engine

  60dd48f0c2f6 [active]
    Name:      ie-daily-report
    Schedule:  0 17 * * 1-5
    Repeat:    ∞
    Next run:  2026-05-27T17:00:00+08:00
    Deliver:   local
    Workdir:   E:\AIGC-KB\输出\investment-engine

  04ea51299177 [active]
    Name:      ie-industry-intel
    Schedule:  0 9 * * 1
    Repeat:    ∞
    Next run:  2026-06-01T09:00:00+08:00
    Deliver:   local
    Workdir:   E:\AIGC-KB\输出\investment-engine

  ab1910fda411 [active]
    Name:      ie-weekly-tracking-scan
    Schedule:  0 20 * * 0
    Re
```

### 更新后验收标准
1. ✅ ast.parse 所有 10 个 .py 文件通过
2. ✅ from _path_setup import ... 实际加载成功
3. ✅ 无 parent.parent.parent 残余
4. ✅ 无 bare except 残余
5. ✅ requirements.txt / __init__.py / .gitignore 存在
6. ✅ python -c 'from _path_setup import *' 无错误 + python scripts/kms.py status 可执行
7. ⏳ V4 Pro FINAL REVIEW
