#!/usr/bin/env python3
"""
KMS Daily Report — 自动巡检 + 主动推送

借鉴投资体系 08:30 晨会，每日自动运行：
1. 🔍 Stale 检测 — 笔记 >30 天未更新
2. 📊 健康快照 — 断裂链接 / orphan / no-score 趋势
3. 📈 使用统计 — 最近 7 天搜索 / 命令
4. 📋 推送到微信

用法:
    python3 kms_daily_report.py          # 全量报告
    python3 kms_daily_report.py --stdout  # 仅打印，不推送
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ── 路径 ───────────────────────────────────────────────────
_KMS_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _KMS_ROOT / "scripts"
_WIKI = _KMS_ROOT.parent / "wiki-AIGC-KB"


def _run_script(name: str, *args: str) -> str:
    """运行 kms-engine 脚本，返回 stdout"""
    try:
        r = subprocess.run(
            ["python3", str(_SCRIPTS / name), *args],
            capture_output=True, text=True, timeout=30,
            cwd=str(_KMS_ROOT)
        )
        return r.stdout.strip()
    except Exception as e:
        return f"[错误] {e}"


def check_stale(days: int = 30) -> list[dict]:
    """检测超过 N 天未更新的笔记"""
    if not _WIKI.exists():
        return []

    now = datetime.now()
    stale = []
    # 加载画像关键词
    portrait_keywords = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from kms_session import load_portrait
        portrait = load_portrait()
        if portrait:
            for interest in portrait.get("interests", []):
                portrait_keywords.extend(interest.lower().split())
    except Exception:
        pass

    for f in sorted(_WIKI.rglob("*.md")):
        if ".obsidian" in str(f) or f.name in ("CHANGELOG.md", "EVOLUTION.md"):
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        age = (now - mtime).days
        if age > days:
            # 判断是否与画像相关
            fname = f.name.lower()
            is_relevant = any(kw in fname for kw in portrait_keywords) if portrait_keywords else False
            stale.append({
                "name": str(f.relative_to(_WIKI)),
                "days": age,
                "mtime": mtime.strftime("%Y-%m-%d"),
                "relevant": is_relevant,
            })

    # 画像相关笔记排前
    stale.sort(key=lambda x: (not x["relevant"], -x["days"]))
    return stale


# ── 自动抓取管线 ──────────────────────────────────────────

def _network_available() -> bool:
    """快速检测网络是否可达"""
    import subprocess
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "1", "8.8.8.8"],
            capture_output=True, timeout=3
        )
        return r.returncode == 0
    except Exception:
        return False


def fetch_arxiv_rss() -> list[dict]:
    """抓取 ArXiv AI 新论文 RSS（curl + regex，WSL 兼容）"""
    if not _network_available():
        return []
    import subprocess, re
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "10",
             "https://export.arxiv.org/rss/cs.AI"],
            capture_output=True, text=True, timeout=12
        )
        if r.returncode not in (0, 28) or not r.stdout.strip():
            return []
        # 用 regex 提取 title 和 link（XML 太大时 ET 会挂）
        titles = re.findall(r'<title>([^<]+)</title>', r.stdout)
        links = re.findall(r'<link>([^<]+)</link>', r.stdout)
        items = []
        for t, l in zip(titles[1:], links[1:]):  # skip channel title/link
            if l.startswith("http"):
                items.append({"title": t[:120], "url": l})
                if len(items) >= 5:
                    break
        return items
    except Exception:
        return []


def fetch_github_trending() -> list[dict]:
    """抓取 GitHub Trending 热门仓库（curl + regex，WSL 兼容）"""
    if not _network_available():
        return []
    import subprocess, re
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "10",
             "https://github.com/trending?since=daily"],
            capture_output=True, text=True, timeout=12
        )
        if r.returncode not in (0, 28) or not r.stdout.strip():
            return []
        # 提取 h2 内的仓库名（格式: <h2><a href="/owner/repo">）
        repos = re.findall(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', r.stdout)
        seen = set()
        items = []
        for repo in repos:
            if repo not in seen and "/" in repo and not repo.startswith("trending"):
                seen.add(repo)
                items.append({"title": repo, "url": f"https://github.com/{repo}"})
                if len(items) >= 8:
                    break
        return items
    except Exception:
        return []


def _generate_insights(report: dict) -> list[str]:
    """根据报告数据自动生成 actionable 洞察（知识→产出闭环）"""
    insights = []

    # 从 stale 中找画像相关笔记
    stale_items = report.get("stale", {}).get("items", [])
    relevant_stale = [s for s in stale_items if s.get("relevant")]
    if relevant_stale:
        top = relevant_stale[0]
        insights.append(f"⏰ 画像相关笔记待更新: {top['name']}（{top['days']}天未更新）")

    # 从 ArXiv 抓取中找与画像相关的论文
    arxiv = report.get("fetched", {}).get("arxiv", [])
    if arxiv:
        title = arxiv[0].get("title", "")
        if "LLM" in title or "Agent" in title or "Reasoning" in title:
            insights.append(f"📄 相关论文: {title[:60]}")

    # 从使用统计中找活跃主题
    usage = report.get("usage", {})
    keywords = usage.get("top_keywords", [])
    if keywords:
        kw = keywords[0]
        insights.append(f"🔍 持续关注: 「{kw}」本周搜索 {usage.get('total_searches', 0)} 次")

    return insights[:3]  # 最多 3 条


def build_report() -> dict:
    """生成完整日报"""
    report = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stale": {"count": 0, "items": []},
        "health": {},
        "usage": {},
        "fetched": {},
        "summary": "",
    }

    # 0. 自动抓取（线程隔离，硬超时 12s）
    report["fetched"]["arxiv"] = []
    report["fetched"]["github"] = []
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_arxiv = ex.submit(fetch_arxiv_rss)
            fut_github = ex.submit(fetch_github_trending)
            for fut in as_completed([fut_arxiv, fut_github], timeout=12):
                if fut == fut_arxiv:
                    report["fetched"]["arxiv"] = fut.result()
                elif fut == fut_github:
                    report["fetched"]["github"] = fut.result()
    except Exception:
        pass  # 抓取超时或失败，不影响报告

    # 1. Stale 检测
    stale_items = check_stale(30)
    report["stale"]["count"] = len(stale_items)
    report["stale"]["items"] = stale_items[:10]  # 只显示前 10

    # 2. 健康快照
    health_out = _run_script("health_check.py")
    # 解析 HEALTH| 行
    for line in health_out.split("\n"):
        if line.startswith("HEALTH|"):
            parts = line.split("|")
            if len(parts) >= 7:
                report["health"] = {
                    "files": parts[1],
                    "orphan": parts[2].split("=")[-1] if "=" in parts[2] else parts[2],
                    "broken": parts[3].split("=")[-1] if "=" in parts[3] else parts[3],
                    "noscore": parts[4].split("=")[-1] if "=" in parts[4] else parts[4],
                    "nofm": parts[5].split("=")[-1] if "=" in parts[5] else parts[5],
                    "shell": parts[6].split("=")[-1] if "=" in parts[6] else parts[6],
                }

    # 3. 使用统计
    try:
        sys.path.insert(0, str(_SCRIPTS))
        from kms_analytics import UsageTracker
        data = UsageTracker().report(days=7)
        report["usage"] = {
            "total_commands": data["total_commands"],
            "total_searches": data["total_searches"],
            "top_commands": [c["command"] for c in data.get("top_commands", [])[:5]],
            "top_keywords": [k["keyword"] for k in data.get("top_keywords", [])[:5]],
        }
    except Exception as e:
        report["usage"] = {"error": str(e)}

    # 4. 汇总摘要
    h = report["health"]
    parts = []
    broken = int(h.get("broken", "0")) if isinstance(h.get("broken"), str) and h["broken"].isdigit() else 0
    orphan = int(h.get("orphan", "0")) if isinstance(h.get("orphan"), str) and h["orphan"].isdigit() else 0
    if broken > 0:
        parts.append(f"🔗 断裂{broken}")
    if orphan > 0:
        parts.append(f"📄 孤岛{orphan}")
    if report["stale"]["count"] > 0:
        parts.append(f"⏰ 过期{ report['stale']['count'] }")
    if report["usage"].get("total_searches", 0) > 0:
        parts.append(f"🔍 搜索{ report['usage']['total_searches'] }次")
    report["summary"] = " | ".join(parts) if parts else "✅ 一切正常"

    return report


def format_report(report: dict) -> str:
    """格式化为可读文本"""
    lines = [
        f"📋 KMS 晨报 — {report['date']}",
        f"{'='*40}",
        f"",
    ]

    # 摘要
    lines.append(f"📊 {report['summary']}")
    lines.append("")

    # 健康
    h = report["health"]
    if h:
        lines.append("🔧 系统健康:")
        lines.append(f"  断裂链接: {h.get('broken', '?')}")
        lines.append(f"  孤岛文件: {h.get('orphan', '?')}")
        lines.append(f"  无评分: {h.get('noscore', '?')}")
        lines.append(f"  无frontmatter: {h.get('nofm', '?')}")
        lines.append(f"  空壳: {h.get('shell', '?')}")
        lines.append("")

    # Stale
    if report["stale"]["count"] > 0:
        lines.append(f"⏰ 过期笔记 (>30天未更新): {report['stale']['count']} 篇")
        for item in report["stale"]["items"][:5]:
            lines.append(f"  {item['name']} ({item['days']}天)")
        lines.append("")

    # 使用
    u = report["usage"]
    if u.get("total_commands", 0) > 0 or u.get("total_searches", 0) > 0:
        lines.append(f"📈 近7天使用: 命令{u.get('total_commands',0)}次 / 搜索{u.get('total_searches',0)}次")
        if u.get("top_keywords"):
            lines.append(f"  高频搜索: {' → '.join(u['top_keywords'][:3])}")
        lines.append("")

    # 今日洞察（知识→产出闭环）
    insights = _generate_insights(report)
    if insights:
        lines.append("📝 今日洞察:")
        for ins in insights:
            lines.append(f"  {ins}")
        lines.append("")

    # 自动抓取
    f = report.get("fetched", {})
    arxiv_items = f.get("arxiv", [])
    github_items = f.get("github", [])
    if arxiv_items or github_items:
        lines.append("📡 今日热点:")
        if arxiv_items and "失败" not in arxiv_items[0].get("title", ""):
            lines.append(f"  ArXiv AI: {arxiv_items[0]['title'][:80]}")
            if len(arxiv_items) > 1:
                lines.append(f"  +{len(arxiv_items)-1} 篇更多")
        if github_items and "失败" not in github_items[0].get("title", ""):
            lines.append(f"  GitHub: {github_items[0]['title']}")
            if len(github_items) > 1:
                lines.append(f"  +{len(github_items)-1} 个更多仓库")
        lines.append("")

    lines.append(f"{'='*40}")
    lines.append("💡 建议: kms health --parallel | kms analytics | kms validate <笔记>")
    return "\n".join(lines)


def push_wechat(content: str):
    """通过 Server 酱推送微信"""
    send_key_path = Path.home() / ".hermes" / ".env"
    if not send_key_path.exists():
        print("[推送] .env 不存在，跳过微信推送")
        return

    # 从 .env 读 SendKey
    send_key = None
    for line in send_key_path.read_text().split("\n"):
        if "SENDKEY" in line.upper():
            parts = line.split("=", 1)
            if len(parts) == 2:
                send_key = parts[1].strip().strip("'\"")
                break

    if not send_key:
        print("[推送] 未找到 SENDKEY，跳过")
        return

    import urllib.request
    import urllib.parse
    url = f"https://sctapi.ftqq.com/{send_key}.send"
    data = urllib.parse.urlencode({
        "title": f"KMS 晨报 — {datetime.now().strftime('%m-%d')}",
        "desp": content,
    }).encode()
    try:
        r = urllib.request.urlopen(url, data=data, timeout=15)
        print(f"[推送] ✅ 已发送 ({r.status})")
    except Exception as e:
        print(f"[推送] ❌ 失败: {e}")


def main():
    report = build_report()
    content = format_report(report)

    if "--stdout" in sys.argv:
        print(content)
        return

    # 默认行为：打印 + 推送
    print(content)
    push_wechat(content)

    # 更新 session memory
    try:
        sys.path.insert(0, str(_SCRIPTS))
        from kms_session import record_health
        h = report["health"]
        total = sum(int(h.get(k, 0)) for k in ("orphan", "broken", "noscore", "nofm", "shell") if h.get(k, "").isdigit())
        record_health(checks=6, issues=total)
    except Exception:
        pass


if __name__ == "__main__":
    main()
