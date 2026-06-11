#!/usr/bin/env python3
"""
投资心理冷却阀 — 冲动交易防护（投资觉察体系 Level 1）

作用:
  当觉察体系检测到用户处于冲动交易密集期时，自动锁定当前策略，
  阻止高风险策略切换，强制冷静 N 个交易日。

原理:
  行为金融学中的「冷却期效应」(Cooling-Off Period)：
  人在情绪驱动下做决策倾向「即时满足」，冷却期打断这一机制，
  让理性信号有时间覆盖情绪信号。

触发条件（3条任意满足即可触发）:
  1. 反转交易 ≥2笔/7天（同一股票3天内买卖）
  2. 心理评分 < 40（来自 psych_check.py）
  3. 觉察覆盖率 < 30% 且交易笔数 ≥5

触发后行为:
  - 锁定当前策略 N 个交易日（默认3天）
  - 策略锁定器拒绝变更主策略
  - 每日复盘提示冷却状态和剩余天数
  - 到期自动释放

用法:
    # 检查是否处于冷静期
    python3 scripts/psych_cooling.py --check

    # 查看冷静期详细状态
    python3 scripts/psych_cooling.py --status

    # 手动激活冷静期（用于自检）
    python3 scripts/psych_cooling.py --activate "手动触发"

    # 手动解除冷静期
    python3 scripts/psych_cooling.py --deactivate

    # 作为模块导入
    from psych_cooling import is_cooling_active, activate_cooling, deactivate_cooling
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 配置 ──
COOLING_DIR = Path(__file__).resolve().parent.parent / "config"
COOLING_FILE = COOLING_DIR / "psych_cooling.json"

# 默认冷却期：3个自然日（近似3个交易日）
DEFAULT_COOLING_DAYS = 3

# 触发阈值
MIN_REVERSALS = 2          # 7天内反转交易≥2笔
MIN_PSYCH_SCORE = 40       # 心理评分<40
MIN_AWARENESS_RATE = 0.3   # 觉察覆盖率<30%
MIN_TRADES_FOR_AWARENESS = 5  # 至少5笔交易才用覆盖率规则


def _now_iso() -> str:
    return datetime.now().isoformat()


def _future_iso(days: int = DEFAULT_COOLING_DAYS) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat()


def _is_expired(expires_at: str) -> bool:
    """判断冷却期是否已过期"""
    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now() >= expiry
    except (ValueError, TypeError):
        return False


def read_cooling() -> dict:
    """读取当前冷却状态"""
    if not COOLING_FILE.exists():
        return {"active": False}
    try:
        data = json.loads(COOLING_FILE.read_text(encoding="utf-8"))
        # 自动过期检查
        if data.get("active") and data.get("expires_at"):
            if _is_expired(data["expires_at"]):
                data["active"] = False
                data["auto_expired"] = True
                write_cooling(data)
        return data
    except (json.JSONDecodeError, IOError):
        return {"active": False}


def write_cooling(data: dict) -> None:
    """写入冷却状态"""
    COOLING_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COOLING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(COOLING_FILE)


def is_cooling_active() -> bool:
    """快速检查是否处于冷静期（对外接口）"""
    return read_cooling().get("active", False)


def is_cooling_expired() -> dict:
    """检查冷却是否已过期（返回详细状态）"""
    state = read_cooling()
    if not state.get("active"):
        return {"active": False, "expired": False, "message": "未处于冷静期"}
    if state.get("auto_expired"):
        return {"active": False, "expired": True, "message": "冷却期已自动过期"}
    return {"active": True, "expired": False, "message": "冷静期中"}


def _load_trades(ledger_dir: str = None) -> list:
    """加载交易台账"""
    if not ledger_dir:
        from psych_check import DEFAULT_LEDGER_DIR
        ledger_dir = str(DEFAULT_LEDGER_DIR)
    fp = Path(ledger_dir) / "trade_ledger.csv"
    if not fp.exists():
        return []
    import csv
    with open(fp, "r", encoding="utf_8_sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _parse_date(d: str):
    """尝试解析日期"""
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(d.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def evaluate_cooling(trades: list = None,
                     days: int = 7,
                     ledger_dir: str = None) -> dict:
    """评估当前是否应触发冷却

    参数:
        trades: 交易列表（可选，不传则自动加载）
        days: 评估窗口天数
        ledger_dir: 台账目录（可选）

    返回:
        {"cooling": bool, "reason": str, "reasons": [str],
         "score": int, "reversals": int, "trades_count": int}
    """
    if trades is None:
        trades = _load_trades(ledger_dir)
    if not trades:
        return {"cooling": False, "reason": "无交易记录",
                "reasons": [], "score": 60, "reversals": 0,
                "trades_count": 0}

    # ── 导入 psych_check 做评分和反转检测 ──
    try:
        from psych_check import psych_check, _count_reversals
    except ImportError:
        # 备选：直接计算
        psych_result = {}
        reversals = 0
    else:
        psych_result = psych_check(trades, days=days)
        reversals = psych_result.get("reversal_count", 0)

    score = psych_result.get("mood_score", 60)
    trades_count = len([t for t in trades
                        if _parse_date(t.get("date", ""))])
    reasons = []
    cooling = False

    # 规则1: 反转交易过多
    if reversals >= MIN_REVERSALS:
        reasons.append(f"反转交易 {reversals}笔/近{days}天")
        cooling = True

    # 规则2: 心理评分过低
    if score < MIN_PSYCH_SCORE:
        reasons.append(f"心理评分 {score}/100")
        cooling = True

    # 规则3: 低觉察覆盖率且有足够交易
    awareness_rate = psych_result.get("awareness_rate", 0)
    if trades_count >= MIN_TRADES_FOR_AWARENESS:
        if awareness_rate < MIN_AWARENESS_RATE:
            reasons.append(
                f"觉察覆盖率 {awareness_rate:.0%}（建议 ≥30%）"
            )
            cooling = True

    return {
        "cooling": cooling,
        "reason": "；".join(reasons) if reasons else "正常",
        "reasons": reasons,
        "score": score,
        "reversals": reversals,
        "trades_count": trades_count,
        "awareness_rate": awareness_rate,
    }


def activate_cooling(reason: str,
                     score: int = 50,
                     current_strategy: str = None,
                     cooling_days: int = DEFAULT_COOLING_DAYS) -> dict:
    """激活冷静期

    参数:
        reason: 触发原因描述
        score: 触发时的心理评分
        current_strategy: 当前锁定的策略ID
        cooling_days: 冷静期天数

    返回:
        冷却状态字典
    """
    state = {
        "active": True,
        "triggered_at": _now_iso(),
        "expires_at": _future_iso(cooling_days),
        "cooling_days": cooling_days,
        "reason": reason,
        "score": score,
        "locked_strategy": current_strategy,
        "auto_expired": False,
        "history": [],
    }

    # 保留历史
    existing = read_cooling()
    if existing.get("history"):
        state["history"] = existing["history"]

    write_cooling(state)

    strat_info = f"  → 当前策略: {current_strategy}" if current_strategy else ""
    print(f"🧊 冷静期已激活（{cooling_days}天）")
    print(f"  原因: {reason}")
    print(f"  心理评分: {score}/100")
    print(f"  到期: {state['expires_at'][:10]}" + strat_info)
    print(f"  文件: {COOLING_FILE}")

    # ── 自动告警 ──
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from alert_manager import send_cooling_alert
        send_cooling_alert(reason, state['expires_at'][:10],
                           current_strategy or "未知", float(score))
    except ImportError:
        pass  # alert_manager 可选

    return state


def deactivate_cooling() -> dict:
    """手动解除冷静期"""
    existing = read_cooling()
    state = {"active": False, "deactivated_at": _now_iso()}

    if existing.get("active"):
        history = existing.get("history", [])
        history.append({
            "triggered_at": existing.get("triggered_at"),
            "expires_at": existing.get("expires_at"),
            "reason": existing.get("reason"),
            "deactivated_at": _now_iso(),
            "deactivated_by": "manual",
        })
        state["history"] = history

    write_cooling(state)
    print("✅ 冷静期已手动解除")
    return state


def get_cooling_warning() -> str:
    """获取冷却期提示文案（供每日复盘嵌入）"""
    state = read_cooling()
    if not state.get("active"):
        return ""
    try:
        expires = datetime.fromisoformat(state["expires_at"])
        remaining = (expires - datetime.now()).days
        remaining = max(0, remaining)
    except (ValueError, TypeError):
        remaining = 0

    lines = [
        "🧊 **冷静期进行中**",
        f"  触发原因: {state.get('reason', '未知')}",
        f"  心理评分: {state.get('score', '?')}/100",
        f"  剩余: {remaining}天（到期: {state.get('expires_at', '?')[:10]}）",
        "  ⚠️ 冷静期内策略切换将被自动阻止",
    ]
    return "\n".join(lines)


def format_status() -> str:
    """格式化的状态输出"""
    state = read_cooling()
    if not state.get("active"):
        return "🧊 当前无冷静期\n  状态: 正常"

    try:
        expires = datetime.fromisoformat(state["expires_at"])
        remaining = (expires - datetime.now()).days
        remaining = max(0, remaining)
    except (ValueError, TypeError):
        remaining = -1

    lines = [
        "=" * 40,
        "🧊 投资心理冷却阀 — 状态",
        "=" * 40,
        f"  状态:        🔴 冷静中",
        f"  触发原因:    {state.get('reason', '未知')}",
        f"  心理评分:    {state.get('score', '?')}/100",
        f"  锁定策略:    {state.get('locked_strategy', '未知')}",
        f"  触发时间:    {state.get('triggered_at', '?')[:19]}",
    ]
    if remaining >= 0:
        lines.append(f"  到期时间:    {state.get('expires_at', '?')[:19]}")
        lines.append(f"  剩余天数:    {remaining}天")
    else:
        lines.append(f"  到期时间:    {state.get('expires_at', '?')[:19]}")

    lines.append(f"  文件:        {COOLING_FILE}")
    lines.append("=" * 40)
    return "\n".join(lines)


def cli():
    parser = argparse.ArgumentParser(
        description="投资心理冷却阀 — 冲动交易防护",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--check", action="store_true",
                        help="检查是否处于冷静期（退出码: 0=正常, 1=冷静中）")
    parser.add_argument("--status", action="store_true",
                        help="详细状态输出")
    parser.add_argument("--activate", nargs="?", const="手动触发",
                        metavar="REASON",
                        help="手动激活冷静期")
    parser.add_argument("--deactivate", action="store_true",
                        help="手动解除冷静期")
    parser.add_argument("--days", type=int, default=7,
                        help="评估窗口天数（默认7天）")

    args = parser.parse_args()

    if args.activate:
        activate_cooling(args.activate)
        return

    if args.deactivate:
        deactivate_cooling()
        return

    if args.status:
        print(format_status())
        return

    if args.check:
        # 自动评估 + 状态检查
        evaluation = evaluate_cooling(days=args.days)

        if evaluation["cooling"]:
            # 如果未激活→自动激活
            if not is_cooling_active():
                from strategy_lock import get_current
                current = get_current()
                primary = current.get("primary", {}).get("id", "")
                activate_cooling(
                    evaluation["reason"],
                    score=evaluation["score"],
                    current_strategy=primary,
                )
            else:
                print("🧊 冷却中: " + evaluation["reason"])
                print(get_cooling_warning())
            sys.exit(1)
        else:
            # 如果已激活但评估说不需要→自动释放
            if is_cooling_active():
                print("✅ 评估正常，自动解除冷静期")
                deactivate_cooling()
            else:
                print("✅ 状态正常，无需冷静")
            sys.exit(0)

    # 无参数→默认状态输出
    print(format_status())


if __name__ == "__main__":
    cli()
