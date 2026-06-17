#!/usr/bin/env python3
"""daily_brief.py — 每日简报自动推送

借鉴 Sharbel 的 Cron 主动推送理念。
每天早上 PM Agent 生成简报，通过 Server酱 推送到微信。

用法:
  python daily_brief.py                          # 生成简报
  python daily_brief.py --send                   # 生成 + 推送微信
  python daily_brief.py --topic "分析中际旭创"   # 自定义主题
"""

import json, sys, os, subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_template import _load_sessions, list_templates
from agent_protocol import MessageBus

# ── 配置 ──────────────────────────────────────────────
SERVER_CHAN_KEY = os.environ.get("SERVER_CHAN_KEY", "")


def generate_brief(topic: str = "") -> str:
    """生成每日简报"""
    sessions = _load_sessions()
    templates = list_templates()
    chains = MessageBus._trace_chains

    today = datetime.now().strftime("%Y-%m-%d")
    today_sessions = [s for s in sessions if s.get("created_at", "").startswith(today)]

    # 统计
    total = len(today_sessions)
    success = sum(1 for s in today_sessions if s.get("status") == "success")
    failed = sum(1 for s in today_sessions if s.get("status") == "failed")
    rate = round(success / total * 100, 1) if total > 0 else 0

    # Agent 排行
    from collections import Counter
    agent_counter = Counter(s.get("template_name", "?") for s in today_sessions)
    top_agents = agent_counter.most_common(5)

    # 链路统计
    chain_count = len(chains)

    lines = [
        f"# 📊 每日简报 — {today}",
        "",
        f"## 今日概览",
        f"",
        f"| 指标 | 数值 |",
        f"|:-----|:----:|",
        f"| Agent 执行 | {total} 次 |",
        f"| 成功率 | {rate}% ({success}/{total}) |",
        f"| 失败 | {failed} 次 |",
        f"| 链路追踪 | {chain_count} 条 |",
        f"| Agent 模板 | {len(templates)} 个 |",
        f"",
    ]

    if topic:
        lines.append(f"## 📌 今日关注\n\n> {topic}\n")

    if top_agents:
        lines.append(f"## 🔥 最活跃 Agent\n")
        for name, count in top_agents:
            lines.append(f"- **{name}**: {count} 次")
        lines.append("")

    if today_sessions:
        lines.append(f"## 🕐 最近执行\n")
        for s in reversed(today_sessions[-5:]):
            icon = "✅" if s.get("status") == "success" else "❌"
            t = s.get("created_at", "")[11:19]
            name = s.get("template_name", "?")
            goal = s.get("goal", "")[:30]
            lines.append(f"- {icon} [{t}] **{name}**: {goal}")
        lines.append("")

    lines.append(f"---\n*由 KMS Engine 自动生成*")

    return "\n".join(lines)


def send_to_wechat(content: str):
    """通过 Server酱 推送到微信"""
    if not SERVER_CHAN_KEY:
        print("  ⚠️  SERVER_CHAN_KEY 未配置，跳过推送")
        return False

    title = f"📊 Agent 每日简报 - {datetime.now().strftime('%Y-%m-%d')}"
    # Server酱 markdown 格式
    payload = json.dumps({"title": title, "desp": content, "tags": "简报"})

    try:
        import urllib.request
        url = f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send"
        data = urllib.parse.urlencode({"title": title, "desp": content}).encode()
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if result.get("code") == 0:
            print(f"  ✅ 已推送到微信")
            return True
        else:
            print(f"  ⚠️  推送失败: {result.get('message', '?')}")
            return False
    except Exception as e:
        print(f"  ⚠️  推送异常: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="每日简报")
    parser.add_argument("--send", action="store_true", help="推送到微信")
    parser.add_argument("--topic", default="", help="今日关注主题")
    args = parser.parse_args()

    brief = generate_brief(args.topic)
    print(brief)

    if args.send:
        send_to_wechat(brief)

    # 保存到文件
    out_dir = Path("/tmp") / "briefs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"brief_{datetime.now().strftime('%Y%m%d')}.md"
    out_path.write_text(brief, encoding="utf-8")
    print(f"\n✅ 简报已保存: {out_path}")


if __name__ == "__main__":
    main()
