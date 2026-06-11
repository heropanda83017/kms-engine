#!/usr/bin/env python3
"""告警管理器 — 投资体系内异常行为的统一通知入口

当前输出渠道: console（醒目打印）
预留渠道: Telegram / email / webhook（通过 send_message tool）

在任何检测到异常行为的地方调用 send_alert()，系统会自动：
  1. 打印醒目告警到终端
  2. 记录到告警日志 (alerts/alarm_{YYYYMM}.txt)
  3. 未来支持 Telegram 推送（配置后自动路由）

用法:
  from alert_manager import send_alert, ALARM_DIR

  send_alert("cooling", "🧊 冷静期激活", 
             "原因: 7天内2次反转交易\n到期: 2026-06-12", 
             severity="WARNING")
"""

import os, json, sys
from datetime import datetime
from pathlib import Path

# ── 路径 ──
ALARM_DIR = Path(__file__).resolve().parent.parent / "alerts"
ALARM_DIR.mkdir(parents=True, exist_ok=True)

SEVERITY_ICONS = {
    "INFO":    "ℹ️",
    "WARNING": "⚠️",
    "ERROR":   "❌",
    "CRITICAL":"🚨",
}

# ══════════════════════════════════════════════════════════
#  核心函数
# ══════════════════════════════════════════════════════════

def send_alert(topic: str, title: str, message: str,
               severity: str = "WARNING", source: str = "system") -> None:
    """发送告警

    参数:
        topic: 主题分类 (cooling/behavior/position/strategy)
        title: 告警标题（1行）
        message: 详细内容（多行用 \\n 分隔）
        severity: INFO / WARNING / ERROR / CRITICAL
        source: 来源模块
    """
    icon = SEVERITY_ICONS.get(severity, "ℹ️")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{now}] [{severity}] [{topic}] {title}"

    # 1. 控制台输出（醒目）
    sep = "=" * 62
    print()
    print(sep)
    print(f"  {icon} [{severity}] {title}")
    print(f"  {'|':>4} 来源: {source}")
    if message:
        for line in message.strip().split("\n"):
            print(f"  {'|':>4} {line}")
    print(sep)
    print()

    # 2. 写入告警日志
    try:
        log_path = ALARM_DIR / f"alarm_{datetime.now().strftime('%Y%m')}.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{log_line}\n")
            if message:
                for line in message.strip().split("\n"):
                    f.write(f"  {line}\n")
            f.write("\n")
    except (IOError, OSError) as e:
        print(f"  [alert_manager] ⚠️ 告警日志写入失败: {e}")

    # 3. 预留：Telegram / webhook
    # TODO: 配置后自动路由到 Telegram
    # if _has_telegram():
    #     _send_telegram(topic, title, message, severity)


def send_cooling_alert(reason: str, expires_at: str,
                       current_strategy: str, score: float) -> None:
    """冷静期激活时的专用告警"""
    send_alert(
        topic="cooling",
        title="🧊 冷静期已激活 — 策略自动锁定",
        message=(
            f"当前策略: {current_strategy}\n"
            f"触发原因: {reason}\n"
            f"心理评分: {score:.0f}/100\n"
            f"到期时间: {expires_at}\n"
            f"💡 冷静期内无法切换策略"
        ),
        severity="WARNING",
        source="psych_cooling"
    )


def send_behavior_alert(summary: str, severity_label: str,
                         flags: list, score: float) -> None:
    """行为偏差检测告警"""
    sev = "CRITICAL" if severity_label == "severe" else "WARNING"
    flag_lines = "\n".join(f"  🚩 {f.get('behavior','')}: {f.get('detail','')}"
                          for f in (flags or [])[:5])
    msg = f"综合分: {score:.2f}\n{flag_lines}" if flag_lines else f"综合分: {score:.2f}"
    send_alert(
        topic="behavior",
        title=f"🧠 行为偏差检测: {severity_label.upper()}",
        message=msg,
        severity=sev,
        source="emotion_detector"
    )


def send_position_alert(warnings: list) -> None:
    """持仓健康告警"""
    if not warnings:
        return
    warn_lines = "\n".join(f"  ⚠️ {w}" for w in warnings)
    send_alert(
        topic="position",
        title=f"📊 持仓健康检查 — {len(warnings)} 项异常",
        message=warn_lines,
        severity="WARNING",
        source="position_health"
    )


# ══════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="告警管理器 — 发送/查询告警")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="发送测试告警")
    p_send.add_argument("--topic", default="test", help="主题")
    p_send.add_argument("--title", default="测试告警", help="标题")
    p_send.add_argument("--message", default="这是测试消息", help="内容")
    p_send.add_argument("--severity", default="WARNING",
                        choices=["INFO", "WARNING", "ERROR", "CRITICAL"])

    p_list = sub.add_parser("list", help="查看本月告警日志")
    p_list.add_argument("--lines", type=int, default=20, help="显示行数")

    args = parser.parse_args()

    if args.cmd == "send":
        send_alert(args.topic, args.title, args.message, severity=args.severity)

    elif args.cmd == "list":
        log_path = ALARM_DIR / f"alarm_{datetime.now().strftime('%Y%m')}.txt"
        if not log_path.exists():
            print(f"  本月暂无告警日志")
            return
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-args.lines:]:
            print(f"  {line}")


if __name__ == "__main__":
    main()
