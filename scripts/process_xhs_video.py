#!/usr/bin/env python3
"""
小红书视频 → 学习笔记 自动管线 v2
修复: 真实磁盘写入、cookie路径硬编码、HF_ENDPOINT镜像、Whisper术语增强
用法: python process_xhs_video.py <小红书视频URL>
"""

import os, sys, json, re, subprocess, argparse, shutil
from datetime import datetime
from pathlib import Path

# ── 镜像与镜像（避免 HuggingFace 直连超时） ──
from _path_setup import WHISPER_CACHE_DIR, HF_ENDPOINT

# ── Checkpoint 工具 ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _path_setup import WIKI_DIR, CONFIG_DIR
from scripts.checkpoint_utils import start as cp_start, step_done as cp_step_done, \
    mark_complete as cp_mark_complete, resume_from as cp_resume_from, \
    get_state as cp_get_state

# ── 路径常量 ──
YT_DLP = r"C:\Program Files\Python312\Scripts\yt-dlp.exe"
FFMPEG = r"C:\Program Files\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
COOKIE_FILE = r"C:\Users\Administrator\xiaohongshu_cookies.txt"
MANIFEST = CONFIG_DIR / "video_manifest.json"


def _video_hash(url: str) -> str:
    """由 URL 计算 12 位 hash，用作 checkpoint name。"""
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _load_manifest() -> list:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return []


def _save_manifest(manifest: list) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

NOTE_DIR = WIKI_DIR / "06-reading-notes" / "晓辉博士"
CACHE_DIR = NOTE_DIR / "视频缓存"
RAW_DIR   = NOTE_DIR / "原始转写"
OUT_DIR   = NOTE_DIR / "学习笔记"
WHISPER_CACHE = WHISPER_CACHE_DIR

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(WHISPER_CACHE, exist_ok=True)


def sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "_", s).strip()
    return s[:60]


def download_video(url: str) -> dict:
    print(f"[1/4] \u4e0b\u8f7d\u89c6\u9891: {url}")
    
    # Check cookies
    if not os.path.exists(COOKIE_FILE):
        print(f"  \u26a0 Cookie\u6587\u4ef6\u4e0d\u5b58\u5728: {COOKIE_FILE}")
        print(f"  \u8bf7\u5148\u8fd0\u884c: python export_xhs_cookies.py")
        sys.exit(1)
    
    base_cmd = [YT_DLP, "--cookies", COOKIE_FILE,
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]
    
    # Get metadata
    result = subprocess.run(base_cmd + ["--dump-json", url, "--no-playlist"],
                           capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  yt-dlp\u5931\u8d25: {result.stderr[:500]}")
        sys.exit(1)
    
    meta = json.loads(result.stdout.strip())
    title = meta.get("title", "untitled")
    safe_title = sanitize_filename(title)
    video_path = CACHE_DIR / f"{safe_title}.mp4"
    
    if video_path.exists():
        print(f"  \u89c6\u9891\u5df2\u5b58\u5728: {video_path}")
    else:
        subprocess.run(base_cmd + ["-o", str(video_path), url, "--no-playlist"],
                      capture_output=True, text=True, timeout=300)
        print(f"  \u89c6\u9891\u4e0b\u8f7d\u5b8c\u6210: {video_path} ({os.path.getsize(video_path)/1024/1024:.1f}MB)")
    
    meta["safe_title"] = safe_title
    meta["video_path"] = str(video_path)
    meta["audio_path"] = str(CACHE_DIR / f"{safe_title}.wav")
    return meta


def extract_audio(meta: dict):
    print(f"[2/4] \u63d0\u53d6\u97f3\u9891: {meta['audio_path']}")
    if os.path.exists(meta["audio_path"]):
        print(f"  \u97f3\u9891\u5df2\u5b58\u5728\uff0c\u8df3\u8fc7")
        return
    subprocess.run(
        [FFMPEG, "-i", meta["video_path"], "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", "-y", meta["audio_path"]],
        capture_output=True, text=True, timeout=300)
    print(f"  \u97f3\u9891\u5df2\u63d0\u53d6 ({os.path.getsize(meta['audio_path'])/1024/1024:.1f}MB)")


def transcribe(meta: dict, model_name: str = "base") -> tuple:
    print(f"[3/4] \u8f6c\u5199 (model={model_name})")
    
    from faster_whisper import WhisperModel
    
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         download_root=WHISPER_CACHE)
    
    # initial_prompt 帮助提升英文术语识别
    segments, info = model.transcribe(
        meta["audio_path"], language="zh", beam_size=5,
        initial_prompt="Anthropic, Claude, Colossus, Karpathy, OpenAI, xAI, GPU, SpaceX, Grok, AI, computing"
    )
    
    transcript_lines = []
    for seg in segments:
        m, s = divmod(int(seg.start), 60)
        h, m = divmod(m, 60)
        ts = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        transcript_lines.append(f"[{ts}] {seg.text.strip()}")
    
    full_text = "\n".join(transcript_lines)
    raw_path = RAW_DIR / f"{meta['safe_title']}_转写.txt"
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(f"标题: {meta.get('title','')}\n")
        f.write(f"来源: {meta.get('webpage_url', meta.get('url', ''))}\n")
        f.write(f"时长: {info.duration:.0f}s\n")
        f.write(f"语言: {info.language}\n")
        f.write("=" * 40 + "\n\n")
        f.write(full_text)
    
    print(f"  \u8f6c\u5199\u5b8c\u6210: {raw_path} ({len(transcript_lines)} \u6bb5, {len(full_text)} \u5b57)")
    return full_text, str(raw_path)


def main():
    os.environ["HF_ENDPOINT"] = HF_ENDPOINT  # set at runtime
    parser = argparse.ArgumentParser(description="小红书视频→学习笔记")
    parser.add_argument("url", help="小红书视频URL")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper模型大小 (base尺寸性价比最高)")
    parser.add_argument("--reset", action="store_true",
                        help="强制从零开始（清除已有 checkpoint）")
    args = parser.parse_args()

    vhash = _video_hash(args.url)
    cp_name = f"video-{vhash}"

    # --reset 时清除 checkpoint
    if args.reset:
        from scripts.checkpoint_utils import clear as cp_clear
        cp_clear(cp_name)
        print("  🗑️ Checkpoint 已清除，将从头开始")

    # 检查中断恢复
    resume_idx = cp_resume_from(cp_name)
    if resume_idx > 0:
        state = cp_get_state(cp_name)
        completed = len(state.get("completed_steps", [])) if state else 0
        print(f"  🔄 检测到中断 -> resume_idx={resume_idx}, 已完成 {completed}/3 步")

    # 定义步骤
    steps_plan = [
        {"id": "downloaded", "name": "下载视频"},
        {"id": "audio_extracted", "name": "提取音频"},
        {"id": "transcribed", "name": "语音转写"},
    ]
    cp_start(cp_name, 3, steps_plan=steps_plan, metadata={"url": args.url})

    print("=" * 50)
    print("  晓辉博士视频 → 学习笔记管线 v2")
    print("=" * 50)

    # 读取已完成步骤
    state = cp_get_state(cp_name)
    completed = set(state.get("completed_steps", [])) if state else set()

    # ── Step 1: 下载视频 ──
    if "downloaded" not in completed:
        meta = download_video(args.url)
        cp_step_done(cp_name, "downloaded", output={
            "title": meta.get("title", ""),
            "video_path": meta.get("video_path", ""),
        })
    else:
        print("[1/3] ✅ 视频已下载 (跳过)")
        # 仍需要 meta 给后续步骤用 — 从 checkpoint 恢复
        state = cp_get_state(cp_name)
        step_out = state.get("step_outputs", {}).get("downloaded", {})
        meta = {
            "safe_title": sanitize_filename(step_out.get("title", "untitled")),
            "video_path": step_out.get("video_path", ""),
            "audio_path": str(CACHE_DIR / f"{sanitize_filename(step_out.get('title', 'untitled'))}.wav"),
        }
        if not meta["video_path"] or not os.path.exists(meta["video_path"]):
            print("  ⚠️ 缓存信息不完整，重新下载")
            meta = download_video(args.url)
            cp_step_done(cp_name, "downloaded", output={
                "title": meta.get("title", ""),
                "video_path": meta.get("video_path", ""),
            })

    # ── Step 2: 提取音频 ──
    if "audio_extracted" not in completed:
        extract_audio(meta)
        cp_step_done(cp_name, "audio_extracted")
    else:
        print("[2/3] ✅ 音频已提取 (跳过)")

    # ── Step 3: 语音转写 ──
    transcript, raw_path = "", ""
    if "transcribed" not in completed:
        transcript, raw_path = transcribe(meta, args.model)
        cp_step_done(cp_name, "transcribed", output={
            "raw_path": raw_path,
            "transcript_length": len(transcript),
        })
    else:
        print("[3/3] ✅ 转写已完成 (跳过)")
        state = cp_get_state(cp_name)
        step_out = state.get("step_outputs", {}).get("transcribed", {})
        raw_path = step_out.get("raw_path", "")

    # ── 汇总输出 ──
    state = cp_get_state(cp_name)
    step_comp = len(state.get("completed_steps", [])) if state else 0
    print("\n" + "=" * 50)
    print(f"  {'🎉 管线完成' if step_comp >= 3 else '⚠️ 管线不完整'}!")
    print(f"  ✅ 已完成 {step_comp}/3 步")
    print(f"  🎬 视频: {meta.get('video_path','—')}")
    print(f"  🔊 音频: {meta.get('audio_path','—')}")
    print(f"  📝 转写: {raw_path or '—'}")
    print(f"  📖 笔记: python fill_note.py \"{raw_path}\"" if raw_path else "")

    # 记录到视频清单
    manifest = _load_manifest()
    if not any(e["hash"] == vhash for e in manifest):
        manifest.append({
            "hash": vhash,
            "url": args.url,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "steps": ["downloaded", "audio_extracted", "transcribed"],
            "status": "completed" if step_comp >= 3 else "partial",
        })
        _save_manifest(manifest)
        print(f"  📋 已记录到 video_manifest")

    # 全部完成才标记
    if step_comp >= 3:
        cp_mark_complete(cp_name)
        print(f"  📍 Checkpoint '{cp_name}' 已完成")
    print("=" * 50)

if __name__ == "__main__":
    main()
