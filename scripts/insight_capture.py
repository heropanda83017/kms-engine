#!/usr/bin/env python3
"""insight_capture.py — 外部借鉴→KMS一键归档桥接脚本

KMS作为汲取底层 → investment-research-cycle作为顶层流程 → 本脚本桥接机械操作。

用法:
  insight-capture skeleton --type <type> --platform <p> --author <a> --title <t> [--url <u>] [--date <d>]
  insight-capture fusion <wiki_path>
  insight-capture link
  insight-capture finalize <wiki_path> [--date <d>]

类型 (--type):
  methodology → 08-investment/02-投研分析/外部借鉴记录/
  datasource  → 08-investment/01-数据源与工具/工具_外部信源评估_
  tool        → 08-investment/01-数据源与工具/
"""

import argparse, json, re, sys, subprocess
from datetime import date as dt_date
from pathlib import Path

# ─── 路径注入 ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, SCRIPTS_DIR

# ─── Checkpoint 工具 ─────────────────────────────────────
try:
    from scripts.checkpoint_utils import start as cp_start, step_done as cp_step_done, \
        mark_complete as cp_mark_complete, resume_from as cp_resume_from, \
        get_state as cp_get_state, clear as cp_clear
    HAS_CHECKPOINT = True
except ImportError:
    HAS_CHECKPOINT = False

# ─── 常量 ────────────────────────────────────────────────
EVOLUTION_PATH = WIKI_DIR / "EVOLUTION.md"
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "笔记模板_v2.md"

# 路径决策矩阵
ROUTE_MAP = {
    "methodology": WIKI_DIR / "08-investment" / "02-投研分析" / "外部借鉴记录",
    "datasource": WIKI_DIR / "08-investment" / "01-数据源与工具",
    "tool": WIKI_DIR / "08-investment" / "01-数据源与工具",
}

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


# ─── 辅助函数 ────────────────────────────────────────────

def _sanitize_filename(name: str) -> str:
    """替换文件系统非法字符为 -"""
    return ILLEGAL_CHARS.sub("-", name).strip("-.")[:80]


def _read(path: Path) -> str:
    """UTF-8 安全读取"""
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str):
    """UTF-8 安全写入，自动创建父目录"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _today() -> str:
    return dt_date.today().strftime("%Y-%m-%d")


def _current_month() -> str:
    return dt_date.today().strftime("%Y-%m")


# ─── Skeleton ────────────────────────────────────────────

def cmd_skeleton(args):
    """从元数据生成 wiki 笔记骨架"""
    source_route = ROUTE_MAP.get(args.type, ROUTE_MAP["methodology"])
    safe_title = _sanitize_filename(args.title)
    safe_author = _sanitize_filename(args.author or "unknown")
    date_str = args.date or _today()

    filename = f"{date_str}-{safe_author}-{safe_title}.md"
    if args.type == "datasource":
        filename = f"工具_外部信源评估_{safe_title}.md"

    out_path = source_route / filename

    # 加载模板
    template_text = ""
    if TEMPLATE_PATH.exists():
        template_text = _read(TEMPLATE_PATH)
    
    # 生成笔记内容
    note = f"""# 外部借鉴 | {args.platform} | {date_str}

## 来源元数据

| 字段 | 值 |
|:-----|:----|
| **平台** | {args.platform} |
| **作者** | {args.author or "未知"} |
| **标题** | {args.title} |
| **链接** | {args.url or "—"} |
| **日期** | {date_str} |
| **核心观点** | (待填写) |

## 核心摘要

| 维度 | 内容 |
|:-----|:-----|
| 核心框架 | (待填写) |
| 关键工具/指标 | (待填写) |
| 操作流程 | (待填写) |
| 风险提示 | (待填写) |

## 覆盖矩阵

| 来源元素 | 自有体系 | 状态 | 备注 |
|:---------|:---------|:----|:-----|
| | | — | — |

## 优化决策

| 缺口/优化点 | 优先级 | 决策 | 工作量 |
|:-----------|:------|:-----|:-------|
| | | | — |

## 已执行变更

| 日期 | 变更 | 文件 | 状态 |
|:----|:-----|:-----|:----|

---

## 闭环确认

- [ ] ① 来源记录 ✓
- [ ] ② 内容提取 ✓
- [ ] ③ 覆盖矩阵 ✓
- [ ] ④ 优化决策 ✓
- [ ] ⑤ Wiki更新 ✓
- [ ] ⑥ 代码变更已完成（如有）

---
*骨架由 insight_capture.py skeleton 自动生成，内容由 agent 填充。*
"""

    if out_path.exists():
        print(f"⚠️ 文件已存在: {out_path}")
    else:
        _write(out_path, note)
        print(f"✅ 骨架文件已创建: {out_path}")

    # smart_fuse 融合检查提示
    print(f"💡 执行融合检查: insight-capture fusion {out_path}")
    return out_path


# ─── Fusion ──────────────────────────────────────────────

def cmd_fusion(args):
    """对新笔记执行 smart_fuse 融合检查"""
    wiki_path = Path(args.wiki_path)
    if not wiki_path.exists():
        print(f"❌ 文件不存在: {wiki_path}")
        return

    # 检查正文长度
    content = _read(wiki_path)
    body = content.replace("---", "", 2).strip()
    words = len(body)
    print(f"📄 笔记正文: ~{words} 字")

    if words < 20:
        print("⚠️ 笔记内容过短 (<20字)，无法进行相似度匹配")
        return

    # 调 smart_fuse
    smart_fuse = SCRIPTS_DIR / "smart_fuse.py"
    if not smart_fuse.exists():
        print("❌ smart_fuse.py 未找到，跳过融合检查")
        return

    try:
        r = subprocess.run(
            [sys.executable, str(smart_fuse), str(wiki_path)],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("⚠️ smart_fuse 超时 (60s)，跳过融合检查")
        return

    if r.returncode != 0:
        print(f"⚠️ smart_fuse 返回码 {r.returncode}, stderr: {r.stderr[:500]}")
    else:
        output = r.stdout.strip()
        if output:
            print(output)
        else:
            print("🔍 smart_fuse 返回空。可能原因：")
            print("   - 笔记与其他笔记相似度均 < 0.15（无高相似候选）")
            print("   - 可独立作为新笔记归档")


# ─── Link ────────────────────────────────────────────────

def cmd_link(args):
    """调 wiki-link.py 更新全库双向链接"""
    wiki_link = SCRIPTS_DIR / "wiki-link.py"
    if not wiki_link.exists():
        print("❌ wiki-link.py 未找到")
        return

    try:
        r = subprocess.run(
            [sys.executable, str(wiki_link)],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("⚠️ wiki-link 超时 (60s)，链接更新未完成")
        return

    if r.returncode != 0:
        print(f"⚠️ wiki-link 返回码 {r.returncode}")
        print(r.stderr[:1000] if r.stderr else "❌ 无错误输出")
    else:
        print(r.stdout[-2000:] if r.stdout else "✅ wiki-link 完成")


# ─── EVOLUTION.md 结构化追加 ─────────────────────────

def _build_evolution_entry(wiki_path: Path) -> str:
    """从 wiki 笔记构建 EVOLUTION.md 条目"""
    # 尝试从文件名解析标题
    stem = wiki_path.stem  # YYYY-MM-DD-author-title
    parts = stem.split("-", 3) if "-" in stem else [stem]
    title_part = parts[3] if len(parts) >= 4 else stem

    return f"""
## {wiki_path.stem} — {title_part}

### 做了什么

- 借鉴 `{wiki_path.relative_to(WIKI_DIR)}` 外部信源
- 详情见对应笔记

### 为什么

- 外部借鉴闭环归档
"""


def _evolution_has_entry(date_str: str) -> bool:
    """检查 EVOLUTION.md 是否已有当日条目标题"""
    if not EVOLUTION_PATH.exists():
        return False
    content = _read(EVOLUTION_PATH)
    # 模式: ## YYYY-MM-DD-xxxx
    return f"## {date_str}-" in content or f"## {date_str} " in content


def _append_evolution(entry_text: str, date_str: str):
    """在 EVOLUTION.md 的正确月份节下追加条目（幂等）"""
    if _evolution_has_entry(date_str):
        print(f"⏭️  EVOLUTION.md 已有 {date_str} 条目，跳过追加")
        return

    month = date_str[:7]  # YYYY-MM
    h2_month = f"## {month}"
    h3_entry = f"## {date_str}"

    if not EVOLUTION_PATH.exists():
        # 创建新文件
        content = f"# 进化日志\n\n{h2_month}\n\n### 做了什么\n\n- 首次外部借鉴闭环\n\n### 为什么\n\n- 初始化外部借鉴闭环流程\n"
        _write(EVOLUTION_PATH, content)
        print(f"✅ 已创建 EVOLUTION.md + 追加条目")
        return

    content = _read(EVOLUTION_PATH)
    lines = content.split("\n")

    # 查找月份 H2
    month_idx = None
    next_h2_idx = None
    for i, line in enumerate(lines):
        if line.startswith(f"## ") and not line.startswith("### "):
            h2_text = line[3:].strip()
            if h2_text == month:
                month_idx = i
            elif month_idx is not None and next_h2_idx is None:
                next_h2_idx = i
                break

    if month_idx is None:
        # 月份节不存在，在文件末尾追加
        if content.endswith("\n"):
            content = content.rstrip("\n") + f"\n\n{h2_month}\n{h3_entry}\n{entry_text}\n"
        else:
            content += f"\n\n{h2_month}\n{h3_entry}\n{entry_text}\n"
        _write(EVOLUTION_PATH, content)
        print(f"✅ 已创建月份节 {h2_month} 并追加条目")
    else:
        # 在月份节末尾插入
        insert_at = next_h2_idx if next_h2_idx else len(lines)
        entry_lines = [h3_entry, entry_text.strip() + "\n"]
        new_lines = lines[:insert_at] + [""] + entry_lines + lines[insert_at:]
        _write(EVOLUTION_PATH, "\n".join(new_lines))
        print(f"✅ 已追加到 {h2_month} 节")


# ─── Finalize ────────────────────────────────────────────

def cmd_finalize(args):
    """一键闭环：fusion → link → sync-check → evolution → checklist (支持 checkpoint 中断恢复)"""
    wiki_path = Path(args.wiki_path)
    if not wiki_path.exists():
        print(f"❌ 文件不存在: {wiki_path}")
        return

    date_str = args.date or _today()
    cp_name = f"insight-finalize-{wiki_path.stem}"

    # 检查是否已有 checkpoint（中断恢复）
    resume_idx = cp_resume_from(cp_name) if HAS_CHECKPOINT else 0
    completed = set()
    if resume_idx > 0 and HAS_CHECKPOINT:
        state = cp_get_state(cp_name)
        completed = set(state.get("completed_steps", [])) if state else set()
        print(f"  🔄 检测到中断 -> resume_idx={resume_idx}, 已跳过 {len(completed)} 个步骤")

    # 定义步骤
    steps_plan = [
        {"id": "fusion_check", "name": "融合检查 (smart_fuse)"},
        {"id": "link_update", "name": "链接更新 (wiki-link)"},
        {"id": "sync_check", "name": "同步检查 (sync-check)"},
        {"id": "evolution_update", "name": "EVOLUTION.md 更新"},
        {"id": "checklist", "name": "闭环确认清单"},
    ]

    # 启动 checkpoint（幂等，重复传入只更新 metadata）
    if HAS_CHECKPOINT:
        cp_start(cp_name, len(steps_plan), steps_plan=steps_plan,
                 metadata={"wiki_path": str(wiki_path), "date": date_str})

    # ── 打标横幅 ──
    print("=" * 50)
    print("  🚀 KMS 一键归档 — finalize" + (" (checkpoint 恢复)" if resume_idx > 0 else ""))
    print(f"  笔记: {wiki_path}")
    print(f"  日期: {date_str}")
    print("=" * 50)

    # ── Step 1: smart_fuse ──
    if "fusion_check" not in completed:
        print("\n[[1/5] 🔍 融合检查 (smart_fuse)")
        cmd_fusion(args)
        if HAS_CHECKPOINT:
            cp_step_done(cp_name, "fusion_check")
    else:
        print("\n[[1/5] 🔍 融合检查 ✅ (已跳过)")

    # ── Step 2: wiki-link ──
    if "link_update" not in completed:
        print("\n[[2/5] 🔗 链接更新 (wiki-link)")
        cmd_link(args)
        if HAS_CHECKPOINT:
            cp_step_done(cp_name, "link_update")
    else:
        print("\n[[2/5] 🔗 链接更新 ✅ (已跳过)")

    # ── Step 3: sync-check ──
    if "sync_check" not in completed:
        print("\n[[3/5] 📋 同步检查 (sync-check report)")
        sync_check = SCRIPTS_DIR / "wiki_sync_check.py"
        if sync_check.exists():
            try:
                r = subprocess.run(
                    [sys.executable, str(sync_check)],
                    capture_output=True, text=True, timeout=60,
                )
                print(r.stdout[-1500:] if r.stdout else "  sync-check 完成")
            except subprocess.TimeoutExpired:
                print("  ⚠️ sync-check 超时，跳过")
        else:
            print("  ❌ wiki_sync_check.py 未找到，跳过")
        if HAS_CHECKPOINT:
            cp_step_done(cp_name, "sync_check")
    else:
        print("\n[[3/5] 📋 同步检查 ✅ (已跳过)")

    # ── Step 4: EVOLUTION.md ──
    if "evolution_update" not in completed:
        print("\n[[4/5] 📝 EVOLUTION.md 更新")
        entry = _build_evolution_entry(wiki_path)
        _append_evolution(entry, date_str)
        if HAS_CHECKPOINT:
            cp_step_done(cp_name, "evolution_update")
    else:
        print("\n[[4/5] 📝 EVOLUTION.md 更新 ✅ (已跳过)")

    # ── Step 5: Checklist ──
    if "checklist" not in completed:
        print("\
[5/6] ✅ 闭环确认清单")
        print()
        print("  - [ ] ① 来源记录 ✓ (skeleton 生成)")
        print("  - [ ] ② 内容提取 ✓ (agent 填写)")
        print("  - [ ] ③ 覆盖矩阵 ✓ (agent 填写)")
        print("  - [ ] ④ 优化决策 ✓ (agent 填写)")
        print("  - [ ] ⑤ Wiki更新 ✓ (本脚本已创建)")
        print("  - [ ] ⑥ 代码变更已完成 (如有)")
        print()
        print("  💡 agent 需手动填写 ②③④⑥ 后闭环")
        print()
        if HAS_CHECKPOINT:
            cp_step_done(cp_name, "checklist")
    else:
        print("\
[5/6] ✅ 闭环确认清单 ✅ (已跳过)")

    # ── Step 6: KG 实体抽取 ──
    if "kg_extract" not in completed:
        print("\
[6/6] 🧠 知识图谱实体抽取")
        _run_kg_extract(wiki_path)
        if HAS_CHECKPOINT:
            cp_step_done(cp_name, "kg_extract")
    else:
        print("\
[6/6] 🧠 知识图谱实体抽取 ✅ (已跳过)")

    print("=" * 50)
    print("  🎉 一键归档完成")
    if HAS_CHECKPOINT:
        cp_mark_complete(cp_name)
        print(f"  📍 Checkpoint '{cp_name}' 已完成")
    print("=" * 50)


def _run_kg_extract(wiki_path: Path):
    """调用 kg_extract.py 提取笔记中的实体和关系"""
    kg_extract = SCRIPTS_DIR / "kg_extract.py"
    if not kg_extract.exists():
        print("  ⚠️  kg_extract.py 未安装，跳过实体抽取")
        return
    try:
        r = subprocess.run(
            [sys.executable, str(kg_extract), str(wiki_path)],
            capture_output=True, text=True, timeout=90,
        )
        if r.returncode == 0:
            # 在输出中找提取结果行
            for line in r.stdout.split("\\n"):
                if "提取" in line and "实体" in line:
                    print(f"  ✅ {line.strip()}")
                    break
            else:
                # 显示最后输出行
                last = [l.strip() for l in r.stdout.split("\\n") if l.strip()]
                if last:
                    print(f"  ✅ {last[-1]}")
        else:
            err = r.stderr[:300] if r.stderr else "无错误输出"
            print(f"  ⚠️  kg_extract 返回码 {r.returncode}: {err}")
    except subprocess.TimeoutExpired:
        print("  ⚠️  kg_extract 超时 (90s)，跳过实体抽取")
    except Exception as e:
        print(f"  ⚠️  kg_extract 异常: {e}")


# ─── 入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="KMS 外部借鉴一键归档桥接脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # skeleton
    p_s = sub.add_parser("skeleton", help="生成 wiki 笔记骨架")
    p_s.add_argument("--type", choices=["methodology", "datasource", "tool"],
                     default="methodology", help="借鉴类型（决定输出路径）")
    p_s.add_argument("--platform", required=True, help="来源平台")
    p_s.add_argument("--author", default="", help="作者")
    p_s.add_argument("--title", required=True, help="标题")
    p_s.add_argument("--url", default="", help="链接")
    p_s.add_argument("--date", default="", help="日期 YYYY-MM-DD")

