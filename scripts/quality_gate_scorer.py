#!/usr/bin/env python3
"""
quality_gate_scorer.py — Horizon式 AI 打分门禁

用法:
  python quality_gate_scorer.py <笔记.md>                    # 对单个笔记打分
  python quality_gate_scorer.py <笔记.md> --dry-run          # 预览打分结果，不写入
  python quality_gate_scorer.py <目录> --batch               # 批量处理目录内所有 .md
  python quality_gate_scorer.py --score 6 "这是笔记正文"     # 直接传文本打分，仅输出结果

打分会追加到 frontmatter:
  score: 8          # 0-10
  score_reason: "..."      # 分值理由
  score_summary: "..."     # 一句话摘要
  score_tags: [tag1, tag2] # AI 提炼标签
  scored_at: 2026-06-09    # 打分日期

配置:
  QGS_MODEL      模型名 (默认 deepseek/deepseek-v4-flash)
  QGS_API_KEY    API Key (默认 DEEPSEEK_PRO_API_KEY env)
  QGS_API_BASE   API 地址 (默认 https://api.deepseek.com)
  QGS_MIN_SCORE  门禁阈值 (默认 6，低于此值在搜索时降权)
"""

# ── 来源 ──
# 灵感来自 Horizon (github.com/Thysrael/Horizon) 的 AI 0-10 分级打分
# 10级: 9-10=Groundbreaking / 8=Significant / 6-7=Good / 4-5=OK / 2-3=Low / 0-1=Noise
# 批处理: 10条一批，失败项=0分，重试3次+指数退避

import os, sys, re, json, time, argparse
from pathlib import Path
from datetime import date

# ── 类型体系 ──
from type_taxonomy import TYPES, detect_type_by_path, build_type_prompt_snippet

# ── 默认配置（优先读环境变量） ──
MODEL       = os.environ.get("QGS_MODEL", "deepseek/deepseek-v4-flash")
API_KEY     = os.environ.get("QGS_API_KEY") or os.environ.get("DEEPSEEK_PRO_API_KEY", "")
API_BASE    = os.environ.get("QGS_API_BASE", "https://api.deepseek.com")
MIN_SCORE   = int(os.environ.get("QGS_MIN_SCORE", "6"))


# ══════════════════════════════════════════════════
# 评分 Prompt（Horizon 10级 + 中文内容适应性）
# ══════════════════════════════════════════════════

SCORE_SYSTEM_PROMPT = """你是一个知识质量评估专家 + 分类专家。请对以下笔记/文章从两个维度打分，并判断其类型。

## 评分标准（0-10）

### 维度A：信息价值（权重60%）
- 9-10 = **开创性** (Groundbreaking) — 独家洞察、未见报道的核心判断
- 8    = **重要** (Significant) — 深度分析，有数据支撑的独特观点
- 6-7  = **良好** (Good) — 有信息增量，逻辑清晰
- 4-5  = **一般** (OK) — 常识性内容，或已熟知的信息
- 2-3  = **较低** (Low) — 信息过时、片面、或明显错误  
- 0-1  = **噪音** (Noise) — 无信息量，营销/水文

### 维度B：与我关联度（权重40%）
- 9-10 = **必读** — 直接关联投资决策或学习路径
- 6-8  = **相关** — 间接关联，值得参考
- 3-5  = **可读可不读** — 泛泛关联
- 0-2  = **不相关** — 与我的领域无关

## 类型定义（必须选一个最匹配的）
- `research` = 研究分析（分析性内容：行业/公司/策略/投资/因子）
- `lecture` = 课程笔记（来自视频/课程/演讲等学习材料）
- `reference` = 参考资料（系统文档/工具说明/配置指南/索引）
- `note` = 通用笔记（个人笔记/文章摘要/转写文本）
- `insight` = 洞察捕获（外部借鉴/对比分析/差距评估）
- `paper` = 论文精读（AI论文/学术文章精读笔记）
- `report` = 定期报告（周报/日报/系统状态报告）
- `profile` = 人物画像（用户画像/个人介绍）
- `system` = 系统文档（架构/配置/规则文档）
- `index` = 导航索引（目录页/图谱/导航）

## 输出格式（必须严格按 JSON 返回，不要额外文字）

{
  "score": <综合得分 0-10, 整数, 仅四舍五入>,
  "type": "<上述类型之一>",
  "reason": "<一句话解释核心判断理由>",
  "summary": "<15-30字的一句话摘要>",
  "tags": ["<标签1>", "<标签2>", "<标签3>"],
  "is_gatepass": <true/false, score >= 6 则 true>
}"""


# ══════════════════════════════════════════════════
# Core
# ══════════════════════════════════════════════════

def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """解析 YAML frontmatter，返回 (frontmatter_dict, body_text, raw_frontmatter_str)"""
    fm = {}
    body = text
    raw_fm = ""

    stripped = text.lstrip()
    if stripped.startswith("---"):
        # 找到第二个 ---
        end_idx = stripped.find("---", 3)
        if end_idx != -1:
            raw_fm = stripped[3:end_idx].strip()
            body = stripped[end_idx + 3:].lstrip()
            try:
                import yaml
                fm = yaml.safe_load(raw_fm) or {}
            except Exception:
                fm = {}
    return fm, body, raw_fm


def call_llm(content: str, retries: int = 3) -> dict | None:
    """调用 LLM 打分，带指数退避重试"""
    from litellm import completion

    for attempt in range(retries):
        try:
            resp = completion(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SCORE_SYSTEM_PROMPT},
                    {"role": "user", "content": content[:4000]},
                ],
                api_key=API_KEY,
                api_base=API_BASE,
                temperature=0.1,
                max_tokens=1000,
            )
            raw = resp.choices[0].message.content.strip()
            # 提取 JSON
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                # 校验必要字段
                if "score" in result:
                    result["score"] = int(round(result["score"]))
                    result["score"] = max(0, min(10, result["score"]))  # clamp 0-10
                    return result
            print(f"  ⚠️  LLM 返回格式异常 (attempt {attempt+1}): {raw[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  LLM 调用失败 (attempt {attempt+1}): {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep((2 ** attempt) * 1.5)  # 指数退避: 1.5s, 3s, 6s
    return None


def update_frontmatter(file_path: str, score_result: dict, dry_run: bool = False) -> bool:
    """将打分结果写回文件的 frontmatter"""
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")

    fm, body, raw_fm = parse_frontmatter(text)

    # 合并新字段
    fm["score"] = score_result["score"]
    fm["type"] = score_result.get("type", detect_type_by_path(file_path) or "note")
    fm["score_reason"] = score_result.get("reason", "")
    fm["score_summary"] = score_result.get("summary", "")
    fm["score_tags"] = score_result.get("tags", [])
    fm["scored_at"] = str(date.today())
    fm["is_gatepass"] = score_result.get("is_gatepass", score_result["score"] >= MIN_SCORE)

    # 重建 frontmatter
    import yaml
    new_fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    new_content = f"---\n{new_fm_str}\n---\n\n{body}"

    if dry_run:
        print(f"  📋 [DRY-RUN] 结果预览:")
        print(f"     type: {fm['type']}")
        print(f"     score: {fm['score']}/10 ({'✅ 通过' if fm['is_gatepass'] else '❌ 未通过'})")
        print(f"     reason: {fm['score_reason'][:80]}")
        print(f"     summary: {fm['score_summary'][:80]}")
        print(f"     tags: {fm['score_tags']}")
        return True

    path.write_text(new_content, encoding="utf-8")
    return True


def score_file(file_path: str, dry_run: bool = False) -> dict | None:
    """对单个文件打分"""
    path = Path(file_path)
    if not path.exists():
        print(f"  ❌ 文件不存在: {file_path}", file=sys.stderr)
        return None

    text = path.read_text(encoding="utf-8")
    fm, body, raw_fm = parse_frontmatter(text)

    # 检查是否已打分（且未过时）
    if "score" in fm and "scored_at" in fm:
        print(f"  ⏭️  已打分 (score={fm['score']}, {fm['scored_at']}), 跳过")
        return None

    # 提取内容用于评分（取 body 前 3000 字）
    content = body[:3000] if len(body) > 3000 else body
    if len(content.strip()) < 50:
        print(f"  ⚠️  内容过短 ({len(content.strip())} 字), 跳过")
        return None

    filename = path.name
    print(f"  🔍 打分: {filename} ({len(content)} 字)...", end="")
    sys.stdout.flush()

    result = call_llm(content)
    if result is None:
        print(" ❌ 失败")
        return None

    print(f" 得分 {result['score']}/10")
    update_frontmatter(file_path, result, dry_run)
    return result


def score_text(text: str) -> dict | None:
    """直接对文本打分（--score 模式），输出 JSON"""
    content = text[:3000]
    if len(content.strip()) < 50:
        print(json.dumps({"error": "内容过短"}, ensure_ascii=False))
        return None
    result = call_llm(content)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def batch_scan(directory: str, dry_run: bool = False):
    """批量处理目录内所有 .md 文件"""
    path = Path(directory)
    md_files = sorted(path.rglob("*.md"))
    print(f"📂 扫描: {directory} ({len(md_files)} 个 .md 文件)")

    results = {"scored": 0, "skipped": 0, "failed": 0, "gatepass": 0}
    for f in md_files:
        result = score_file(str(f), dry_run)
        if result is None:
            # 可能是跳过或失败，区分一下
            if f.stat().st_size < 200:
                results["skipped"] += 1
            else:
                text = f.read_text(encoding="utf-8")
                fm, _, _ = parse_frontmatter(text)
                if "score" in fm:
                    results["skipped"] += 1
                else:
                    results["failed"] += 1
        else:
            results["scored"] += 1
            if result.get("is_gatepass", False):
                results["gatepass"] += 1

    print(f"\n📊 汇总:")
    print(f"   已打分: {results['scored']}  (通过: {results['gatepass']})")
    print(f"   跳过:   {results['skipped']}")
    print(f"   失败:   {results['failed']}")


# ══════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════

def main():
    global MODEL, MIN_SCORE
    parser = argparse.ArgumentParser(
        description="Horizon式 AI 打分门禁 — 给笔记/内容打分 (0-10)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python quality_gate_scorer.py 笔记.md
  python quality_gate_scorer.py 笔记.md --dry-run
  python quality_gate_scorer.py wiki/06-reading-notes/ --batch
  python quality_gate_scorer.py --score 7 "这是要打分的文本内容"
        """,
    )
    parser.add_argument("target", nargs="?", help="笔记文件路径 或 目录(--batch)")
    parser.add_argument("--batch", action="store_true", help="批量扫描整个目录")
    parser.add_argument("--dry-run", action="store_true", help="预览打分结果，不写入文件")
    parser.add_argument("--score", type=int, help="直接对文本打分 (需提供文本)")
    parser.add_argument("text", nargs="?", help="--score 模式的文本内容")
    parser.add_argument("--model", help=f"LLM 模型 (默认 {MODEL})")
    parser.add_argument("--min-score", type=int, default=MIN_SCORE, help=f"门禁阈值 (默认 {MIN_SCORE})")

    args = parser.parse_args()

    if args.model:
        MODEL = args.model
    if args.min_score:
        MIN_SCORE = args.min_score

    # 模式: --score 直接打分文本
    if args.score is not None:
        text_input = args.text or args.target or ""
        if not text_input:
            # 尝试读 stdin
            text_input = sys.stdin.read().strip()
        if text_input:
            score_text(text_input)
        else:
            print("❌ --score 模式需要文本内容", file=sys.stderr)
            sys.exit(1)
        return

    # 模式: --batch 批量
    if args.batch:
        target = args.target or "."
        batch_scan(target, args.dry_run)
        return

    # 模式: 单个文件
    if args.target:
        result = score_file(args.target, args.dry_run)
        if result is None:
            sys.exit(0)  # 跳过/已存在不算失败
        return

    # 无参数
    parser.print_help()


if __name__ == "__main__":
    main()
