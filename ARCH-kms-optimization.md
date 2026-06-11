# ARCH: kms-engine 全面优化
> 生成: 2026-05-28 | 基于 V4 Pro 审计 + 人工评估

## 优化范围 (三阶段)

Phase 1 — P0 堵点修复 (当前工作流断裂)
  - A: 3个 Hermes Skill 路径更新 (kms/xhs-video/systematic-learning)
  - B: kms.py status 改为 wiki 实际统计
  - C: 注册表统一 (wiki-link.py 写入 config/.link_registry.json)

Phase 2 — P1 能力补全
  - D: 视频缓存断点续传 (process_xhs_video.py checkpoint)
  - E: video_manifest.json 防重复处理
  - F: wiki-link.py 增量模式 (mtime 扫描)

Phase 3 — P2 增强
  - G: health_check.py 监控脚本
  - H: 提示词模板化 (templates/prompts/)
  - I: pytest 基础测试

## 验收标准
1. 3个 skill 路径引用全部更新为 kms-engine/
2. kms.py status 输出 wiki 真实文件数 (非0)
3. process_xhs_video.py 断点续传: 重跑跳过已完成步骤
4. video_manifest.json 存在且记录已处理视频
5. 全部 ast.parse ✅
6. V4 Pro FINAL REVIEW APPROVED
