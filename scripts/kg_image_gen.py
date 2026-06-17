#!/usr/bin/env python3
"""kg_image_gen.py — 笔记认知锚点 → AI配图

流程:
  1. 读取笔记的认知锚点（从 kg_store）
  2. 锚点类型 → 选择视觉模板（8种构图模式，借鉴 ian-xiaohei）
  3. 锚点内容 → 转为英文 prompt
  4. 调用 MiniMax/硅基流动 API → 生成 PNG
  5. 保存到笔记同目录 _kg/xxx-illustration-N.png
  6. 笔记底部追加 ![](引用)

用法:
  python kg_image_gen.py <笔记路径>           # 为笔记生图
  python kg_image_gen.py <笔记路径> --dry-run  # 预览prompt不生图
  python kg_image_gen.py <笔记路径> --all      # 为所有锚点生图
"""

import json, sys, os, time, urllib.request, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR

# ── API 配置（优先读环境变量） ─────────────────────────
# MiniMax 海螺AI
MINIMAX_KEY = os.environ.get("MINIMAX_CN_API_KEY", "")
MINIMAX_BASE = "https://api.minimaxi.com/v1"

# 视觉模板 — 借鉴 ian-xiaohei-illustrations 的 8 种构图模式
COMPOSITION_TEMPLATES = {
    "causality": {
        "style": "workflow flow left to right",
        "desc": "因果链 — 左输入→中处理→右输出",
        "elements": "arrows connecting steps, simple boxes",
    },
    "comparison": {
        "style": "before and after side by side",
        "desc": "前后对比 — 左混乱右有序",
        "elements": "two panels, dividing line in middle",
    },
    "process_step": {
        "style": "workflow pipeline top to bottom",
        "desc": "流程步骤 — 自上而下的步骤",
        "elements": "numbered steps, connecting lines",
    },
    "key_judgment": {
        "style": "central concept with radiating nodes",
        "desc": "核心判断 — 中心辐射图",
        "elements": "central circle, surrounding satellite nodes",
    },
    "key_data": {
        "style": "data visualization minimal",
        "desc": "关键数据 — 放大的数字+短标注",
        "elements": "large number, small label, bar or gauge",
    },
    "metaphor": {
        "style": "concept metaphor surreal",
        "desc": "概念隐喻 — 一个怪诞但成立的物理隐喻",
        "elements": "one strange machine or object, one character doing core action",
    },
}

# 锚点类型 → 默认英文 prompt 前缀
ANCHOR_PROMPTS = {
    "causality": "A simple hand-drawn causal chain diagram showing how",
    "comparison": "A split-screen before-and-after comparison showing",
    "process_step": "A clean workflow diagram showing the steps of",
    "key_judgment": "A minimalist concept diagram illustrating",
    "key_data": "A clean data visualization highlighting",
    "metaphor": "A surreal hand-drawn metaphor representing",
}

# ── 图像生成 API ──────────────────────────────────────

# 候选端点列表（按优先级）
ENDPOINTS = [
    # MiniMax 海螺AI
    {"url": f"{MINIMAX_BASE}/image/generation", "model": "image-01",
     "format": "minimax", "key": MINIMAX_KEY},
    {"url": f"{MINIMAX_BASE}/images/generations", "model": "image-01",
     "format": "openai", "key": MINIMAX_KEY},
    # OpenAI 兼容格式
    {"url": "https://api.siliconflow.cn/v1/images/generations", "model": "black-forest-labs/FLUX.1-schnell",
     "format": "openai", "key": os.environ.get("SILICONFLOW_API_KEY", "")},
]


def _find_working_endpoint():
    """自动检测可用的图像生成 API（返回第一个可用的）"""
    for ep in ENDPOINTS:
        if not ep["key"]:
            continue
        try:
            if ep["format"] == "openai":
                data = json.dumps({
                    "model": ep["model"],
                    "prompt": "test",
                    "n": 1,
                    "size": "1024x1024",
                }).encode()
                req = urllib.request.Request(
                    ep["url"], data=data,
                    headers={
                        "Authorization": f"Bearer {ep['key']}",
                        "Content-Type": "application/json",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=5)
                if resp.status == 200:
                    return ep
            elif ep["format"] == "minimax":
                data = json.dumps({
                    "model": ep["model"],
                    "prompt": "test",
                    "n": 1,
                }).encode()
                req = urllib.request.Request(
                    ep["url"], data=data,
                    headers={
                        "Authorization": f"Bearer {ep['key']}",
                        "Content-Type": "application/json",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=5)
                if resp.status == 200:
                    return ep
        except Exception:
            continue
    return None


def generate_image(prompt: str, note_name: str, index: int = 1,
                   output_dir: str = None, dry_run: bool = False) -> str | None:
    """生成一张配图

    返回: 图片路径，或 None
    """
    if dry_run:
        return prompt

    ep = _find_working_endpoint()
    if not ep:
        print("  ⚠️  无可用的图像生成 API", file=sys.stderr)
        return None

    # 构建完整 prompt（风格约束）
    full_prompt = (
        f"{prompt}. "
        "Style: minimalist hand-drawn line art, white background, "
        "black thin lines, clean and simple, "
        "16:9 illustration for Chinese article, "
        "limited red/orange/blue annotations, plenty of white space."
    )

    try:
        if ep["format"] == "openai":
            data = json.dumps({
                "model": ep["model"],
                "prompt": full_prompt,
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json",
            }).encode()
        else:
            data = json.dumps({
                "model": ep["model"],
                "prompt": full_prompt,
                "n": 1,
            }).encode()

        req = urllib.request.Request(
            ep["url"], data=data,
            headers={
                "Authorization": f"Bearer {ep['key']}",
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read().decode())

        # 解析返回的图片
        image_data = None
        if ep["format"] == "openai":
            if "data" in result and len(result["data"]) > 0:
                image_data = result["data"][0].get("b64_json")
        elif ep["format"] == "minimax":
            if "data" in result and len(result["data"]) > 0:
                image_data = result["data"][0].get("b64_json") or \
                             result["data"][0].get("image")

        if not image_data:
            print(f"  ⚠️  图片返回为空: {str(result)[:200]}", file=sys.stderr)
            return None

        # 保存
        import base64
        img_bytes = base64.b64decode(image_data)
        out_dir = Path(output_dir) if output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{note_name[:30]}-illustration-{index}.png"
        out_path.write_bytes(img_bytes)
        return str(out_path)

    except Exception as e:
        print(f"  ⚠️  生图失败: {e}", file=sys.stderr)
        return None


def generate_for_note(note_path: str, dry_run: bool = False, all_anchors: bool = False):
    """为笔记生成配图"""
    try:
        from kg_store import get_anchors_for_note, get_entities_for_note
    except ImportError:
        print("  ❌ kg_store 不可用")
        return

    full_path = Path(note_path)
    if not full_path.exists():
        full_path = WIKI_DIR / note_path
        if not full_path.exists():
            print(f"  ❌ 笔记不存在: {note_path}")
            return

    rel_path = str(full_path.relative_to(WIKI_DIR)).replace("\\", "/")
    anchors = get_anchors_for_note(rel_path)

    if not anchors:
        print(f"  ⏭️  无认知锚点，无法生图（先跑 kg_extract）")
        return

    out_dir = full_path.parent / "_kg"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = full_path.stem.replace(" ", "-")[:40]

    # 取锚点生图
    targets = anchors if all_anchors else [anchors[0]]  # 默认只生第1张
    generated = []

    for i, a in enumerate(targets):
        atype = a.get("anchor_type", "key_judgment")
        content = a.get("content", "")
        template = COMPOSITION_TEMPLATES.get(atype, COMPOSITION_TEMPLATES["key_judgment"])
        prompt_prefix = ANCHOR_PROMPTS.get(atype, "A simple diagram about")

        # 构建 prompt
        prompt = f"{prompt_prefix} {content}. {template['elements']}"

        if dry_run:
            print(f"\n  📝 [{atype.upper()}] {content}")
            print(f"     Prompt: {prompt[:150]}...")
            generated.append(prompt)
        else:
            print(f"  🎨 生成 {i+1}/{len(targets)}: [{atype}] {content[:40]}...")
            img_path = generate_image(prompt, stem, i + 1, str(out_dir))
            if img_path:
                print(f"     ✅ {img_path}")
                generated.append(img_path)
            else:
                print(f"     ❌ 失败")

    if not dry_run and generated:
        # 在笔记底部追加图片引用
        img_refs = []
        for g in generated:
            rel_img = Path(g).relative_to(full_path.parent)
            img_refs.append(f"\n![配图{i+1}]({rel_img})")
        footer = "\n\n---\n*🖼️ AI 配图*\n" + "\n".join(img_refs) + "\n"

        with open(full_path, "a", encoding="utf-8") as f:
            f.write(footer)
        print(f"  ✅ 配图已嵌入笔记底部")


def test_api():
    """测试可用的图像生成 API"""
    ep = _find_working_endpoint()
    if ep:
        print(f"✅ 可用 API: {ep['url']} (model={ep['model']})")
    else:
        print("❌ 无可用图像生成 API")
        print("   请设置环境变量:")
        print("   MINIMAX_CN_API_KEY — MiniMax 海螺AI")
        print("   SILICONFLOW_API_KEY — 硅基流动")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="笔记认知锚点 → AI配图")
    parser.add_argument("target", nargs="?", help="笔记路径")
    parser.add_argument("--dry-run", action="store_true", help="预览prompt不生图")
    parser.add_argument("--all", action="store_true", help="为所有锚点生图")
    parser.add_argument("--test", action="store_true", help="测试API连通性")
    args = parser.parse_args()

    if args.test:
        test_api()
    elif args.target:
        generate_for_note(args.target, dry_run=args.dry_run, all_anchors=args.all)
    else:
        print(__doc__)
