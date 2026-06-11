#!/usr/bin/env python3
"""
策略锁定管理器 — Strategy Lock Manager

功能：
  - 读取当前锁定策略
  - 写入新策略锁定（确认时调用）
  - 所有技能通过 get_current_strategy() 获取当前应使用的策略

用法：
  from strategy_lock import get_current, lock_strategy
  current = get_current()  # 获取当前锁定策略
  lock_strategy("S1", ...) # 锁定新策略
"""

import json
from datetime import datetime
from pathlib import Path

LOCK_FILE = Path(__file__).resolve().parent.parent / "config" / "strategy_current.json"

DEFAULT_STRATEGY = {
    "version": 1,
    "updated_at": None,
    "locked_by": "system",
    "regime": None,
    "primary": {"id": "S1", "name": "深度价值", "allocation": 0.60},
    "secondary": {"id": "S3", "name": "景气成长", "allocation": 0.20},
    "track_b": {"id": "S2", "name": "优质价值", "allocation": 0.20},
    "history": [],
}

STRATEGY_PARAMS = {
    "S1": {"name": "深度价值", "conditions": "PE<12+PB<1.5+股息率>3%+ROE>5%", "track": "Track A"},
    "S2": {"name": "优质价值", "conditions": "PE<15+ROE>15%+利润增速>10%+股息率>2%", "track": "Track B"},
    "S3": {"name": "景气成长", "conditions": "PEG<1+营收增速>30%+ROE>10%", "track": "TBD"},
    "S4": {"name": "防御红利", "conditions": "股息率>5%+PB<1+经营现金流>净利润", "track": "TBD"},
    "S5": {"name": "周期反转", "conditions": "PB<1+毛利率触底回升+库存下降", "track": "TBD"},
}


def get_current() -> dict:
    """获取当前锁定的策略"""
    if not LOCK_FILE.exists():
        return DEFAULT_STRATEGY
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_STRATEGY


def lock_strategy(regime_code: str, regime_label: str,
                  confidence: float, primary_id: str,
                  secondary_id: str = None, track_b_id: str = None,
                  locked_by: str = "user") -> dict:
    """锁定策略并写入文件"""
    current = get_current()

    # ── 心理冷却阀检查 ──
    try:
        from psych_cooling import is_cooling_active, read_cooling
        if is_cooling_active():
            current_primary = current.get("primary", {}).get("id", "")
            cooling = read_cooling()
            if primary_id != current_primary:
                print(f"🧊 冷静期阻止策略切换!")
                print(f"  当前策略: {current_primary}")
                print(f"  请求切换: {primary_id}")
                print(f"  原因: {cooling.get('reason', '未知')}")
                print(f"  到期: {cooling.get('expires_at', '?')[:19]}")
                print(f"  💡 手动解除: python3 scripts/psych_cooling.py --deactivate")
                return current
            # 同一策略→允许（可应用更新）
    except ImportError:
        pass

    # 记录历史
    if current.get("regime"):
        current.setdefault("history", []).append({
            "regime": current["regime"],
            "primary": current["primary"],
            "locked_at": current["updated_at"],
        })
        # 只保留最近10条
        current["history"] = current["history"][-10:]

    now = datetime.now().isoformat()

    # 更新锁定
    current["updated_at"] = now
    current["locked_by"] = locked_by
    current["regime"] = {"code": regime_code, "label": regime_label, "confidence": confidence}
    current["primary"] = {"id": primary_id, **STRATEGY_PARAMS.get(primary_id, {}), "allocation": 0.60}

    if secondary_id:
        current["secondary"] = {"id": secondary_id, **STRATEGY_PARAMS.get(secondary_id, {}), "allocation": 0.20}
    if track_b_id:
        current["track_b"] = {"id": track_b_id, **STRATEGY_PARAMS.get(track_b_id, {}), "allocation": 0.20}

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LOCK_FILE)

    print(f"✅ 策略已锁定: {regime_label} → {primary_id}")
    print(f"   文件: {LOCK_FILE}")
    return current


def print_status():
    """打印当前锁定状态"""
    current = get_current()
    r = current.get("regime") or {}
    p = current.get("primary", {})

    print("\n" + "=" * 45)
    print("📋 当前策略锁定状态")
    print("=" * 45)
    print(f"  市况:     {r.get('label', '未设定')} (置信度{r.get('confidence', 0)*100:.0f}%)")
    print(f"  主策略:   {p.get('name', '未设定')} — {p.get('conditions', '')}")
    print(f"  辅策略:   {current.get('secondary', {}).get('name', '未设定')}")
    print(f"  Track B:  {current.get('track_b', {}).get('name', '未设定')}")
    print(f"  锁定时间: {current.get('updated_at', '从未')}")
    print(f"  锁定人:   {current.get('locked_by', 'system')}")
    print("=" * 45)


if __name__ == "__main__":
    print_status()
