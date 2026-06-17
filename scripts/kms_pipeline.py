#!/usr/bin/env python3
"""
KMS Content Pipeline — 6 阶段内容创建流水线

借鉴 ECC 8 角色流水线 + checkpoint 中断恢复。
封装 Validate → Fuse → Link → Enrich → Review → Publish。

用法:
    python3 kms_pipeline.py <笔记路径>
    python3 kms_pipeline.py <笔记路径> --skip validate,review
    python3 kms_pipeline.py <笔记路径> --resume    # 从中断处恢复
"""

import sys
import time
from pathlib import Path


PHASES = [
    ("validate", "VALIDATE", "4 路并行验证"),
    ("fuse",     "FUSE",     "smart_fuse 融合检查"),
    ("link",     "LINK",     "kms link 更新链接"),
    ("enrich",   "ENRICH",   "KG 实体抽取"),
    ("review",   "REVIEW",   "quality_gate 打分"),
    ("publish",  "PUBLISH",  "归档确认 + 清理"),
]


def run_pipeline(note_path: str, skip: set = None, resume: bool = False):
    """执行内容创建流水线"""
    if skip is None:
        skip = set()

    abs_path = str(Path(note_path).resolve())
    print(f"\n{'='*55}")
    print(f"📋 KMS 内容流水线: {Path(note_path).name}")
    print(f"{'='*55}")

    # Checkpoint 恢复
    resume_from = None
    if resume:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from scripts.checkpoint_utils import resume_from as _resume
            checkpoint_data = _resume("kms-pipeline")
            if checkpoint_data:
                resume_from = checkpoint_data.get("step", 0)
                print(f"  🔄 从第 {resume_from + 1} 阶段恢复")
        except Exception:
            pass

    completed = 0
    skipped = 0
    failed = 0
    total = len(PHASES)

    for i, (key, name, desc) in enumerate(PHASES):
        phase_num = i + 1

        # 跳过处理
        if key in skip:
            print(f"\n  ⏭️  [{phase_num}/{total}] {name}: 已跳过")
            skipped += 1
            continue

        # 恢复处理
        if resume_from is not None and i < resume_from:
            print(f"  ⏭️  [{phase_num}/{total}] {name}: 已恢复，跳过")
            completed += 1
            continue

        t0 = time.time()
        print(f"\n  🚀 [{phase_num}/{total}] {name}: {desc}")

        try:
            if key == "validate":
                _run_validate(abs_path)
            elif key == "fuse":
                _run_fuse(abs_path)
            elif key == "link":
                _run_link()
            elif key == "enrich":
                _run_enrich(abs_path)
            elif key == "review":
                _run_review(abs_path)
            elif key == "publish":
                _run_publish(abs_path)

            elapsed = time.time() - t0
            print(f"  ✅ [{phase_num}/{total}] {name} ({elapsed:.1f}s)")
            completed += 1

            # 保存 checkpoint
            _save_checkpoint(i + 1)

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ [{phase_num}/{total}] {name}: {e} ({elapsed:.1f}s)")
            failed += 1
            print(f"\n  ⛔ 流水线中断于第 {phase_num} 阶段: {name}")
            print(f"  💡 修复后运行: python3 kms_pipeline.py \"{abs_path}\" --resume")
            return

    # 完成报告
    print(f"\n{'='*55}")
    if failed == 0:
        print(f"✅ 流水线完成: {completed}/{total} 阶段通过 ({skipped} 跳过)")
    else:
        print(f"⚠️ 流水线完成，{failed} 阶段失败")


def _save_checkpoint(step: int):
    """保存 checkpoint"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.checkpoint_utils import start, step_done
        try:
            start("kms-pipeline", total_steps=len(PHASES),
                  steps_plan=[p[1] for p in PHASES])
        except Exception:
            pass
        step_done("kms-pipeline", f"step_{step}")
    except Exception:
        pass


def _run_validate(note_path: str):
    """Phase 1: 验证"""
    import subprocess as sp
    sp.run(["python3", str(Path(__file__).resolve().parent / "kms_validator.py"),
            note_path], check=True)


def _run_fuse(note_path: str):
    """Phase 2: 融合检查"""
    import subprocess as sp
    sp.run(["python3", str(Path(__file__).resolve().parent.parent / "scripts" / "smart_fuse.py"),
            note_path], check=True)


def _run_link():
    """Phase 3: 更新链接"""
    import subprocess as sp
    sp.run(["python3", str(Path(__file__).resolve().parent / "kms.py"), "link"], check=True)


def _run_enrich(note_path: str):
    """Phase 4: 实体抽取"""
    import subprocess as sp
    sp.run(["python3", str(Path(__file__).resolve().parent / "kms.py"),
            "kg", "extract", note_path], check=True)


def _run_review(note_path: str):
    """Phase 5: 打分"""
    import subprocess as sp
    sp.run(["python3", str(Path(__file__).resolve().parent / "kms.py"),
            "score", note_path], check=True)


def _run_publish(note_path: str):
    """Phase 6: 发布 — 安全检查 + 清理"""
    import subprocess as sp
    # 安全检查
    sp.run(["python3", str(Path(__file__).resolve().parent / "kms_guard.py"),
            note_path], check=False)
    # 清理缓存
    sp.run(["python3", str(Path(__file__).resolve().parent / "kms.py"),
            "cleanup"], check=True)
    print(f"  📄 笔记已就绪: {note_path}")


def cli():
    if len(sys.argv) < 2:
        print("用法: python3 kms_pipeline.py <笔记路径> [选项]")
        print("选项:")
        print("  --skip <阶段1,阶段2>  跳过指定阶段 (validate,fuse,link,enrich,review,publish)")
        print("  --resume             从中断处恢复")
        print("示例:")
        print("  kms_pipeline.py /path/to/note.md")
        print("  kms_pipeline.py /path/to/note.md --skip review,publish")
        print("  kms_pipeline.py /path/to/note.md --resume")
        return

    note_path = sys.argv[1]
    skip = set()
    resume = False

    for arg in sys.argv[2:]:
        if arg.startswith("--skip"):
            parts = arg.split("=") if "=" in arg else [arg, ""]
            skip_str = parts[1] if len(parts) > 1 else ""
            if not skip_str and sys.argv.index(arg) + 1 < len(sys.argv):
                skip_str = sys.argv[sys.argv.index(arg) + 1]
            skip = set(s.strip() for s in skip_str.split(",") if s.strip())
        elif arg == "--resume":
            resume = True

    run_pipeline(note_path, skip=skip, resume=resume)


if __name__ == "__main__":
    cli()
