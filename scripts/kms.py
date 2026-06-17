#!/usr/bin/env python3
"""
KMS — Knowledge Management System 统一入口 v2.0
单命令完成：链接管理 → wiki同步 → 笔记融合

用法:
  kms link                          # 更新wiki双向链接
  kms fuse                          # 融合碎片笔记
  kms status                        # KMS系统状态
  kms search <关键词>                 # wiki全文检索
  kms search <关键词> --type research  # 按类型过滤检索
  kms cleanup                         # 清理缓存
  kms checkpoint start <name>         # 启动检查点
"""

import sys, subprocess, json, argparse
from pathlib import Path

# 路径注入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _path_setup import SCRIPTS_DIR, CONFIG_DIR, WIKI_DIR, NOTES_DIR, REGISTRY


# ── 写入门禁 ─────────────────────────────────────────────
def validate_frontmatter(frontmatter: dict) -> list[str]:
    """验证 frontmatter 完整性，返回缺失字段列表

    写入门禁规则 (第二大脑健康管理系统 Layer 1):
    - type: research | note | reference | strategy | meeting | project | lecture | template | insight
    - domain: 投资研究 | AI技术 | 知识管理 | 个人成长 | 认知方法论
    - tags: 至少1个标签 (非空列表)

    Usage:
        missing = validate_frontmatter(fm_dict)
        if missing:
            print(f"❌ frontmatter 不完整: {missing}")
            return  # 拒绝写入
    """
    missing = []
    required_fields = ["type", "domain", "tags"]
    for f in required_fields:
        if f not in frontmatter:
            missing.append(f)
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list) and len(tags) == 0:
        missing.append("tags(非空)")
    elif isinstance(tags, str) and not tags.strip():
        missing.append("tags(非空)")
    return missing


def validate_content(body: str, min_chars: int = 200) -> list[str]:
    """验证正文完整性

    规则:
    - body > min_chars 字 (拒绝空壳)
    - 至少包含 1 个 [[wiki链接]]

    Returns:
        违规列表, 空列表=通过
    """
    import re
    violations = []
    text = re.sub(r'\s+', '', body)
    if len(text) < min_chars:
        violations.append(f"正文不足 {min_chars} 字 (当前 {len(text)} 字)")
    link_count = len(re.findall(r'\[\[([^\]]+)\]\]', body))
    if link_count == 0:
        violations.append("正文不含任何 [[wiki链接]]")
    return violations


def validate_note(content: str) -> dict:
    """综合验证一篇笔记是否达到写入标准

    Args:
        content: 完整的 .md 文件内容 (含 frontmatter)

    Returns:
        {"pass": True/False, "issues": [...]}
    """
    issues = []
    if not content.startswith("---"):
        return {"pass": False, "issues": ["缺少 frontmatter (--- 开头)"]}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {"pass": False, "issues": ["frontmatter 格式不完整"]}

    fm_text = parts[1]
    body = parts[2]

    # Parse frontmatter (simple YAML-like)
    fm = {}
    for line in fm_text.strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Handle YAML list: [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                import json
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
            elif value.startswith("- "):
                value = [v.strip("- ").strip() for v in value.split("\n")]
            fm[key] = value

    fm_issues = validate_frontmatter(fm)
    issues.extend(fm_issues)

    content_issues = validate_content(body)
    issues.extend(content_issues)

    return {"pass": len(issues) == 0, "issues": issues}


# ── 写入门禁 (MCP 版本) ──
def check_write_gate(content: str) -> str:
    """供 MCP 调用的写入门禁检查, 返回人类可读结果"""
    result = validate_note(content)
    if result["pass"]:
        return "✅ 写入门禁通过: frontmatter完整, 正文充足, 含wiki链接"
    else:
        return f"❌ 写入门禁拒绝:\n" + "\n".join(f"  - {i}" for i in result["issues"])


def cmd_link():
    """更新wiki双向链接"""
    linker = SCRIPTS_DIR / "wiki-link.py"
    if not linker.exists():
        print("❌ wiki-link.py 未找到")
        return
    r = subprocess.run([sys.executable, str(linker)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"⚠️ wiki-link 返回码 {r.returncode}")
        print(r.stderr[:2000] if r.stderr else "❌ 无错误输出")
    else:
        print(r.stdout[-2000:] if r.stdout else "✅ wiki-link 完成")


def cmd_fuse():
    """笔记融合"""
    fuse = SCRIPTS_DIR / "fuse.py"
    if not fuse.exists():
        print("❌ fuse.py 未找到")
        return
    r = subprocess.run([sys.executable, str(fuse)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"⚠️ fuse 返回码 {r.returncode}")
        print(r.stderr[:2000] if r.stderr else "❌ 无错误输出")
    else:
        print(r.stdout[-2000:] if r.stdout else "✅ fuse 完成")


def cmd_enrich(args):
    """背景富化：为笔记自动搜索补充背景信息"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from enrich import enrich_note
    result = enrich_note(Path(args.note), dry_run=args.dry_run, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(2 if "分数" in result.get("error", "") else 1)


def cmd_status():
    """KMS 系统状态"""
    from datetime import datetime
    
    # wiki 统计（按知识域）
    wiki_count = 0
    domain_stats = {}
    for f in WIKI_DIR.rglob("*.md"):
        if ".obsidian" in str(f) or f.name == "CHANGELOG.md":
            continue
        wiki_count += 1
        domain = f.parent.relative_to(WIKI_DIR).parts[0] if len(f.relative_to(WIKI_DIR).parts) > 1 else "root"
        domain_stats[domain] = domain_stats.get(domain, 0) + 1
    
    scripts = list(SCRIPTS_DIR.glob("*.py"))
    reg_size = REGISTRY.stat().st_size / 1024 if REGISTRY.exists() else 0
    manifest = CONFIG_DIR / "video_manifest.json"
    video_count = len(json.loads(manifest.read_text(encoding="utf-8"))) if manifest.exists() else 0
    
    print("=" * 50)
    print("  KMS v2 — 知识管理系统")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    print()
    print(f"📁 kms-engine/ ({len(scripts)} 脚本)")
    for s in scripts:
        if s.name == "__init__.py":
            continue
        print(f"    📄 {s.name}")
    print()
    print(f"🗄️  wiki 知识库 ({wiki_count} 文件)")
    for domain, count in sorted(domain_stats.items(), key=lambda x: -x[1]):
        bar = "█" * min(count // 2, 20) + "░" * max(20 - min(count // 2, 20), 0)
        print(f"    {domain:<20s} {bar} {count}篇")
    print()
    print(f"🎬 已处理视频: {video_count} 个")
    print(f"📦 注册表: {reg_size:.1f} KB ({'✅' if REGISTRY.exists() else '❌'})")
    # 会话上下文
    try:
        from kms_session import get_context
        print()
        print(get_context())
    except Exception:
        pass

def _run_smart_fuse(note_path):
    """为新笔记找融合候选"""
    import subprocess
    script = SCRIPTS_DIR / "smart_fuse.py"
    if not script.exists():
        print("❌ smart_fuse.py 未找到")
        return
    r = subprocess.run([sys.executable, str(script), note_path], capture_output=True, text=True, timeout=60)
    print(r.stdout)


def _run_sync_check(mark=False):
    """检查 wiki 内容与代码同步状态"""
    import subprocess
    script = SCRIPTS_DIR / "wiki_sync_check.py"
    if not script.exists():
        print("❌ wiki_sync_check.py 未找到")
        return
    cmd = [sys.executable, str(script)]
    if mark:
        cmd.append("--mark")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    print(r.stdout)


def _run_fusion_watch():
    """全库扫描孤岛笔记"""
    import subprocess
    script = SCRIPTS_DIR / "smart_fuse.py"
    if not script.exists():
        print("❌ smart_fuse.py 未找到")
        return
    r = subprocess.run([sys.executable, str(script), "--scan"], capture_output=True, text=True, timeout=60)
    print(r.stdout)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    cmd = sys.argv[1]
    
    cmds = {
        "link": cmd_link,
        "fuse": cmd_fuse,
        "status": cmd_status,
        "search": lambda: cmd_search(sys.argv[2]) if len(sys.argv) >= 3 else print("用法: kms search <关键词>"),
        "cleanup": cmd_cleanup,
        "smart-fuse": lambda: _run_smart_fuse(sys.argv[2]) if len(sys.argv) >= 3 else print("用法: kms smart-fuse <笔记路径>"),
        "fusion-watch": _run_fusion_watch,
        "sync-check": lambda: _run_sync_check("--mark" in sys.argv),
        "insight-capture": lambda: _run_insight_capture(),
    }
    
    if cmd in cmds:
        cmds[cmd]()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


def _run_insight_capture():
    """委派到 insight_capture.py"""
    ic = SCRIPTS_DIR / "insight_capture.py"
    if not ic.exists():
        print("❌ insight_capture.py 未找到")
        return
    r = subprocess.run(
        [sys.executable, str(ic)] + sys.argv[2:],
        capture_output=True, text=True, timeout=120,
    )
    print(r.stdout)
    if r.returncode != 0:
        print(f"⚠️ insight-capture 返回码 {r.returncode}", file=sys.stderr)
        if r.stderr:
            print(r.stderr[:1000], file=sys.stderr)
    sys.exit(r.returncode)


def cmd_search(args):
    """wiki 全文检索，支持 --type 过滤 和 --rrf 混合搜索"""
    keyword = args.query
    type_filter = getattr(args, 'type_filter', None) or ""
    use_rrf = getattr(args, 'rrf', False) or getattr(args, 'mode', None) is not None
    mode = getattr(args, 'mode', 'rrf') if use_rrf else None
    use_fusion = getattr(args, 'fusion', False)

    if use_fusion:
        # KG+RRF 融合搜索
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from kg_search import fusion_search
            result = fusion_search(keyword, boost=0.3)
            analysis = result.get("analysis", {})
            fused = result.get("fused_results", [])
            print(f"\n🧠 KG+RRF 融合搜索: \"{keyword}\"")
            if analysis.get("matched_entity"):
                print(f"  精确匹配: {analysis['matched_entity']} ({analysis.get('matched_etype', '?')})")
            if fused:
                for i, (path, final, _, rrf, kg, reasons) in enumerate(fused[:10], 1):
                    kg_tag = f" KG+{kg:.1f}" if kg > 0 else ""
                    reason_str = f" — {'; '.join(reasons[:1])}" if reasons else ""
                    print(f"  #{i:2d} {final:.3f}  {path}{kg_tag}{reason_str}")
            else:
                print("  (无融合结果)")
            return
        except ImportError as e:
            print(f"⚠️ 融合搜索不可用: {e}")
            print("  回退到 RRF 搜索...")
        except Exception as e:
            print(f"⚠️ 融合搜索失败: {e}")
            print("  回退到 RRF 搜索...")

    if use_rrf:
        # 使用 RRF 混合搜索
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from rrf_search import search_rrf
            result = search_rrf(keyword, top_k=10, mode=mode or "rrf")
            elapsed = result.get("elapsed", 0)
            print(f"\n🔍 RRF 搜索: \"{keyword}\" (mode={result.get('mode', mode)}), {elapsed:.2f}s")
            for r in result.get("results", []):
                flags = []
                if r.get("has_fts5"): flags.append("📝")
                if r.get("has_vector"): flags.append("🧠")
                flag_str = "".join(flags) if flags else "  "
                print(f"  #{r.get('final_rank', '?'):2d} {flag_str}  {r['path']}")
                if r.get("title"):
                    print(f"        {r['title']}")
                print(f"        RRF: {r.get('rrf_score', 0):.4f}")
            return
        except ImportError as e:
            print(f"⚠️ RRF 搜索不可用: {e}")
            print("  回退到关键词搜索...")
        except Exception as e:
            print(f"⚠️ RRF 搜索失败: {e}")
            print("  回退到关键词搜索...")

    # 原始关键词搜索 (fallback) — 使用TF-IDF排序
    print(f"\n🔍 搜索: {keyword}" + (f" (类型: {type_filter})" if type_filter else ""))
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from kms_search_enhance import TfIdfSearcher
        searcher = TfIdfSearcher(str(WIKI_DIR))
        tfidf_results = searcher.search(keyword, top_n=15)
        if tfidf_results:
            for r in tfidf_results:
                print(f"  {r['score']:.4f}  {r['path']}")
            return
    except Exception:
        pass
    # 降级: 原始关键词搜索 (无排序)
    results = []
    for f in WIKI_DIR.rglob("*.md"):
        if ".obsidian" in str(f):
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if keyword.lower() not in content.lower() and keyword.lower() not in str(f).lower():
                continue

            # 类型过滤：检查 frontmatter type: 字段
            if type_filter:
                fm_type = ""
                if content.startswith("---"):
                    fm_end = content.find("---", 3)
                    if fm_end != -1:
                        for line in content[3:fm_end].strip().split("\n"):
                            if line.strip().startswith("type:"):
                                fm_type = line.split(":", 1)[1].strip().strip("\"'")
                                break
                allowed_types = [t.strip() for t in type_filter.split(",")]
                if fm_type not in allowed_types:
                    continue

            rel = f.relative_to(WIKI_DIR)
            lines = [l.strip() for l in content.split("\n") if keyword.lower() in l.lower()][:2]
            results.append((str(rel), lines))
        except Exception:
            continue

    if not results:
        print("  未找到匹配内容")
        return
    print(f"  找到 {len(results)} 处匹配:\n")
    for rel, matches in results[:15]:
        print(f"  📄 {rel}")
        for m in matches:
            print(f"      ...{m[:60]}...")


def cmd_cleanup():
    """清理临时文件"""
    import shutil
    freed = 0
    for cache_dir in [Path.home() / ".cache" / "kms"]:
        if cache_dir.exists():
            size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
            shutil.rmtree(cache_dir)
            freed += size
    print(f"✅ 清理完成，释放 {freed/1024/1024:.1f} MB")


def cmd_checkpoint(args):
    """流水线检查点管理"""
    from scripts.checkpoint_utils import (
        start as cp_start, step_done as cp_step_done,
        mark_complete as cp_mark_complete, get_state as cp_get_state,
        resume_from as cp_resume_from, clear as cp_clear, list_all as cp_list,
    )

    if args.subcommand == "start":
        steps_list = [{"id": s.strip()} for s in args.steps.split(",")] if args.steps else []
        state = cp_start(args.name, len(steps_list), steps_plan=steps_list, metadata={"desc": args.desc or ""})
        print(f"✅ Checkpoint '{args.name}' 已启动 ({state['total_steps']} steps)")
    elif args.subcommand == "step":
        state = cp_step_done(args.name, args.step_id)
        print(f"✅ Step '{args.step_id}' 已完成 ({len(state['completed_steps'])}/{state['total_steps']})")
    elif args.subcommand == "done":
        state = cp_mark_complete(args.name)
        print(f"✅ Checkpoint '{args.name}' 已完成 ({state['total_steps']} steps)")
    elif args.subcommand == "status":
        state = cp_get_state(args.name)
        if not state:
            print(f"❌ Checkpoint '{args.name}' 不存在")
            return
        name_field = state.get("checkpoint_key") or state.get("pipeline", args.name)
        print(f"📋 {name_field} — {state['status']}")
        print(f"   步骤: {len(state.get('completed_steps', []))}/{state.get('total_steps', 0)}")
        print(f"   创建: {state.get('created_at', '?')}")
        print(f"   更新: {state.get('updated_at', '?')}")
    elif args.subcommand == "resume":
        state = cp_get_state(args.name)
        if not state:
            print(f"❌ Checkpoint '{args.name}' 不存在")
            return
        resume_idx = cp_resume_from(args.name)
        completed = state.get("completed_steps", [])
        steps_plan = state.get("steps_plan", [])
        print(f"📋 Resume context for '{args.name}':")
        print(f"   已完成: {len(completed)}/{state.get('total_steps', 0)} steps")
        print(f"   恢复点: 索引 {resume_idx} ({'从头' if resume_idx == 0 else '已完成' if resume_idx >= len(steps_plan) else steps_plan[resume_idx].get('id','?')})")
    elif args.subcommand == "list":
        items = cp_list()
        if not items:
            print("📭 无活跃 checkpoint")
        else:
            print(f"📋 {len(items)} 活跃 checkpoint:")
            for s in items:
                n = s.get("checkpoint_key") or s.get("pipeline", "?")
                print(f"   - {n}: {len(s.get('completed_steps',[]))}/{s.get('total_steps',0)} {s['status']}")
    elif args.subcommand == "clear":
        cp_clear(args.name)
        print(f"✅ Checkpoint '{args.name}' 已删除")


def add_checkpoint_subparser(sub):
    """注册 checkpoint 子命令"""
    p = sub.add_parser("checkpoint", help="流水线检查点管理")
    csub = p.add_subparsers(dest="subcommand", required=True)

    # checkpoint start
    cs = csub.add_parser("start", help="启动新 checkpoint")
    cs.add_argument("name", help="checkpoint 名称")
    cs.add_argument("--steps", help="步骤ID列表, 逗号分隔")
    cs.add_argument("--desc", help="描述")

    # checkpoint step
    cs2 = csub.add_parser("step", help="标记步骤完成")
    cs2.add_argument("name", help="checkpoint 名称")
    cs2.add_argument("step_id", help="步骤ID")

    # checkpoint done
    cs3 = csub.add_parser("done", help="标记整个流水线完成")
    cs3.add_argument("name", help="checkpoint 名称")

    # checkpoint status
    cs4 = csub.add_parser("status", help="查看 checkpoint 状态")
    cs4.add_argument("name", help="checkpoint 名称")

    # checkpoint resume
    cs5 = csub.add_parser("resume", help="获取恢复上下文")
    cs5.add_argument("name", help="checkpoint 名称")

    # checkpoint list
    csub.add_parser("list", help="列出所有活跃 checkpoint")

    # checkpoint clear
    cs7 = csub.add_parser("clear", help="删除 checkpoint")
    cs7.add_argument("name", help="checkpoint 名称")


def cmd_index(args):
    """RRF索引管理: build / status"""
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS_DIR))
    from rrf_search import build_index, build_index_incremental, show_status as rrf_status
    if args.index_cmd == "build":
        build_index()
    elif args.index_cmd == "update":
        build_index_incremental()
    elif args.index_cmd == "status":
        rrf_status()


def cmd_health(args):
    """第二大脑健康检查"""
    if getattr(args, 'parallel', False):
        from kms_orchestrator import run_health_parallel
        run_health_parallel()
        return
    import subprocess as _sp
    cmd = ["python3", str(SCRIPTS_DIR / "health_check.py")]
    if args.check:
        cmd.extend(["--check", args.check])
    if args.months != 6:
        cmd.extend(["--months", str(args.months)])
    if args.fix:
        cmd.append("--fix")
    if args.report:
        cmd.append("--report")
    if args.watch:
        cmd.append("--watch")
    _sp.run(cmd)


def main():
    parser = argparse.ArgumentParser(description="KMS 知识管理系统")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("link", help="更新 wiki 双向链接")
    sub.add_parser("fuse", help="笔记融合")
    sub.add_parser("status", help="查看系统状态")
    search_parser = sub.add_parser("search", help="全文检索 (默认关键词, --rrf 混合搜索)")
    search_parser.add_argument("query", help="搜索关键词")
    search_parser.add_argument("--type", dest="type_filter",
                               help="按类型过滤 (逗号分隔, 如 research,lecture)")
    search_parser.add_argument("--rrf", action="store_true",
                               help="RRF混合搜索 (关键词+语义, 须先运行 kms index build)")
    search_parser.add_argument("--mode", choices=["rrf", "fts5", "vector"], default=None,
                               help="搜索模式 (rrf=混合, fts5=纯关键词, vector=纯语义)")
    search_parser.add_argument("--fusion", action="store_true",
                               help="KG+RRF融合搜索（实验性，基于知识图谱增强排序）")
    # index
    index_parser = sub.add_parser("index", help="RRF索引管理")
    index_sub = index_parser.add_subparsers(dest="index_cmd")
    index_sub.add_parser("build", help="全量构建FTS5+向量索引")
    index_sub.add_parser("update", help="增量更新索引 (只处理变更的文件)")
    index_sub.add_parser("status", help="查看索引状态")

    cleanup_parser = sub.add_parser("cleanup", help="清理临时文件")

    # health
    health_parser = sub.add_parser("health", help="第二大脑健康检查")
    health_parser.add_argument("--check", choices=["orphan", "broken-links", "no-score", "no-fm", "shell", "stale"],
                               help="单项检查")
    health_parser.add_argument("--months", type=int, default=6,
                               help="过期检测月数阈值 (默认6个月)")
    health_parser.add_argument("--fix", action="store_true", help="自动修复低风险问题 (空壳删除)")
    health_parser.add_argument("--report", action="store_true", help="生成 Markdown 报告")
    health_parser.add_argument("--watch", action="store_true", help="持续监控 (每 30 分钟)")
    health_parser.add_argument("--parallel", action="store_true", help="并行执行 6 项检查 (默认串行)")

    # validate
    validate_parser = sub.add_parser("validate", help="笔记多视角验证: 质量/融合/实体/治理")
    validate_parser.add_argument("note", help="笔记文件路径")
    validate_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    # pipeline
    pipeline_parser = sub.add_parser("pipeline", help="内容创建流水线: 6 阶段编排")
    pipeline_parser.add_argument("note", help="笔记文件路径")
    pipeline_parser.add_argument("--skip", help="跳过阶段 (逗号分隔)")
    pipeline_parser.add_argument("--resume", action="store_true", help="从中断处恢复")

    # analytics
    analytics_parser = sub.add_parser("analytics", help="使用分析报告")
    analytics_parser.add_argument("--days", type=int, default=7, help="统计天数 (默认 7)")

    # react
    react_parser = sub.add_parser("react", help="ReAct Agent: 思考→行动→观察循环")
    react_parser.add_argument("agent", choices=["router", "validator", "pipeline", "enricher", "reviewer"], help="Agent 类型")
    react_parser.add_argument("goal", nargs="+", help="目标描述")

    add_checkpoint_subparser(sub)

    # enrich
    enrich_parser = sub.add_parser("enrich", help="背景富化: 为笔记自动搜索补充背景信息")
    enrich_parser.add_argument("note", help="笔记文件路径")
    enrich_parser.add_argument("--dry-run", action="store_true", help="预览搜索关键词")
    enrich_parser.add_argument("--force", action="store_true", help="跳过 score ≥ 6 检查")

    # resolve
    resolve_parser = sub.add_parser("resolve", help="三层Skill架构解析: 从用户查询匹配L2技能")
    resolve_parser.add_argument("query", nargs="+", help="用户查询文本")
    resolve_parser.add_argument("--top-k", type=int, default=5, help="返回前N个匹配 (默认5)")

    # kg — 知识图谱实体抽取
    kg_parser = sub.add_parser("kg", help="知识图谱管理: 实体抽取/查询")
    kg_sub = kg_parser.add_subparsers(dest="kg_cmd")
    
    kg_extract_parser = kg_sub.add_parser("extract", help="从笔记提取实体和关系")
    kg_extract_parser.add_argument("note", help="笔记文件路径")
    kg_extract_parser.add_argument("--dry-run", action="store_true", help="预览不存储")
    
    kg_stats_parser = kg_sub.add_parser("stats", help="查看实体存储统计")
    kg_search_parser = kg_sub.add_parser("search", help="搜索实体")
    kg_search_parser.add_argument("query", help="搜索关键词")
    kg_related_parser = kg_sub.add_parser("related", help="查看实体的关联")
    kg_related_parser.add_argument("name", help="实体名称")
    
    kg_scan_parser = kg_sub.add_parser("scan", help="全库扫描提取实体")
    kg_scan_parser.add_argument("--force", action="store_true", help="强制重提忽略进度")

    args = parser.parse_args()

    if args.command == "link":
        cmd_link()
    elif args.command == "fuse":
        cmd_fuse()
    elif args.command == "enrich":
        cmd_enrich(args)
    elif args.command == "status":
        cmd_status()
    elif args.command == "search":
        cmd_search(args)
        # 自动记录搜索
        try:
            from kms_analytics import UsageTracker
            UsageTracker().log_search(args.query)
        except Exception:
            pass
        try:
            from kms_session import record_search, record_command
            record_search(args.query)
            record_command()
        except Exception:
            pass
    elif args.command == "resolve":
        # delegate to three_layer.py
        query = " ".join(args.query)
        subprocess.run([
            "python3", str(SCRIPTS_DIR / "three_layer.py"),
            "--resolve", query,
            "--top-k", str(args.top_k)
        ])
    elif args.command == "index":
        cmd_index(args)
    elif args.command == "health":
        cmd_health(args)
    elif args.command == "cleanup":
        cmd_cleanup()
    elif args.command == "checkpoint":
        cmd_checkpoint(args)
    elif args.command == "kg":
        cmd_kg(args)
    elif args.command == "validate":
        # 笔记多视角验证
        from kms_validator import validate as _validate
        result = _validate(args.note)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "pipeline":
        # 内容创建流水线
        cmd = ["python3", str(SCRIPTS_DIR / "kms_pipeline.py"), args.note]
        if args.skip:
            cmd.extend(["--skip", args.skip])
        if args.resume:
            cmd.append("--resume")
        subprocess.run(cmd)
    elif args.command == "analytics":
        # 使用分析报告
        from kms_analytics import report as _analytics_report
        _analytics_report(days=args.days)
    elif args.command == "react":
        # ReAct Agent
        from kms_react import ReActRouter, ReActValidator, ReActPipeline, ReActEnricher, ReActReviewer
        goal = " ".join(args.goal)
        agents = {"router": ReActRouter, "validator": ReActValidator, "pipeline": ReActPipeline,
                  "enricher": ReActEnricher, "reviewer": ReActReviewer}
        agent_cls = agents.get(args.agent)
        if agent_cls:
            agent = agent_cls()
            agent.run(goal)


def cmd_kg(args):
    """知识图谱管理：委托给 kg_extract.py"""
    kg_extract = SCRIPTS_DIR / "kg_extract.py"
    if not kg_extract.exists():
        print("❌ kg_extract.py 未安装")
        return
    
    kg_cmd = getattr(args, "kg_cmd", None)
    if kg_cmd == "extract":
        cmd = [sys.executable, str(kg_extract), args.note]
        if args.dry_run:
            cmd.append("--dry-run")
    elif kg_cmd == "stats":
        cmd = [sys.executable, str(kg_extract), "--stats"]
    elif kg_cmd == "search":
        cmd = [sys.executable, str(kg_extract), "--search", args.query]
    elif kg_cmd == "related":
        cmd = [sys.executable, str(kg_extract), "--related", args.name]
    elif kg_cmd == "scan":
        cmd = [sys.executable, str(kg_extract), "--all"]
        if args.force:
            cmd.append("--force")
    else:
        print("用法: kms kg {extract|stats|search|related|scan}")
        return
    
    subprocess.run(cmd)


if __name__ == "__main__":
    # Intent Router: 当第一个参数不是已知子命令时走自然语言路由
    if len(sys.argv) > 1:
        known_commands = [
            "link", "fuse", "status", "search", "cleanup",
            "health", "gate", "checkpoint", "index", "kg",
            "smart-fuse", "fusion-watch", "enrich", "resolve",
            "sync-check", "score", "validate", "pipeline", "analytics", "react"
        ]
        if sys.argv[1] not in known_commands:
            from kms_router import IntentRouter
            router = IntentRouter()
            text = " ".join(sys.argv[1:])
            intent, skill, args = router.resolve(text)
            if intent:
                # 构造新的 sys.argv
                if args:
                    sys.argv = [sys.argv[0], skill] + args.split()
                else:
                    sys.argv = [sys.argv[0], skill]
            else:
                print(router.help())
                sys.exit(0)
    main()
