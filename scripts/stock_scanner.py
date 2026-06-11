#!/usr/bin/env python3
"""
stock_scanner.py — v4 实战因子每日扫描 (P4-3)

两阶段扫描：
  1. akshare 一键获取全市场实时行情（1次API调用）
  2. 对粗筛候选（~100只）取日线做动量/量比/趋势评分

用法:
    python3 scripts/stock_scanner.py                          # 默认
    python3 scripts/stock_scanner.py --regime bull_growth     # 指定市况
    python3 scripts/stock_scanner.py --top 20                 # 前20只
    python3 scripts/stock_scanner.py --output report.md       # 输出报告
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

KMS_ROOT = Path(__file__).resolve().parent.parent

REGIME_FACTORS = {
    "bull_growth": {
        "name": "牛市·成长",
        "momentum": (5, 100),
        "volume_ratio": (0.8, 10),
        "trend": True,
    },
    "bull_value": {
        "name": "牛市·价值",
        "momentum": (0, 30),
        "volume_ratio": (0.5, 5),
        "trend": True,
    },
    "sideways": {
        "name": "震荡·防御",
        "momentum": (-5, 15),
        "volume_ratio": (0.3, 3),
        "trend": False,
    },
    "bear_defense": {
        "name": "熊市·防御",
        "momentum": (-15, 5),
        "volume_ratio": (0.5, 5),
        "trend": False,
    },
    "inflation": {
        "name": "通胀·资源",
        "momentum": (5, 50),
        "volume_ratio": (0.8, 10),
        "trend": True,
    },
}

DEFAULT_REGIME = "sideways"


def get_regime() -> str:
    sf = KMS_ROOT / "config" / "strategy_current.json"
    if not sf.exists():
        return DEFAULT_REGIME
    try:
        import json
        d = json.loads(sf.read_text())
        r = d.get("regime", {})
        return r.get("code", DEFAULT_REGIME) if isinstance(r, dict) else DEFAULT_REGIME
    except Exception:
        return DEFAULT_REGIME


def scan(top_n: int = 10) -> list[dict]:
    import baostock as bs
    import pandas as pd

    regime = get_regime()
    f = REGIME_FACTORS.get(regime, REGIME_FACTORS[DEFAULT_REGIME])
    print(f"Regime: {f['name']} | Mom: {f['momentum']} | VolR: {f['volume_ratio']} | Trend: {f['trend']}")
    print()

    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    # Phase 1: 取当前交易股票列表（前200只成交活跃，按价格预筛）
    print("[1/2] Getting stock list...", end=" ", flush=True)
    bs.login()
    try:
        rs = bs.query_all_stock(today)
        stocks = []
        while rs.next():
            r = rs.get_row_data()
            code = r[0]  # sh.600000
            name = r[2] if len(r) > 2 else code
            if name and "ST" not in name and "退" not in name:
                stocks.append({"bs_code": code, "code": code.split(".")[1], "name": name})
        # 取前200只（按代码顺序，覆盖主要板块）
        stocks = stocks[:200]
        print(f"{len(stocks)} stocks (top active)")
    except Exception as e:
        bs.logout()
        print(f"FAIL: {e}")
        return []

    # Phase 2: 取日线计算因子
    print("[2/2] Calculating factors (K-line)...", flush=True)
    result = []
    t0 = datetime.now()

    for i, s in enumerate(stocks):
        if i % 50 == 0 and i > 0:
            elapsed = (datetime.now() - t0).total_seconds()
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  ...{i}/{len(stocks)} ({rate:.0f}/s)")

        try:
            rs = bs.query_history_k_data_plus(
                s["bs_code"], "date,close,volume",
                start_date=start, end_date=today,
                frequency="d", adjustflag="2"
            )
            rows = []
            while rs.next():
                r = rs.get_row_data()
                if r[0]:
                    try:
                        rows.append({"close": float(r[1]), "volume": float(r[2])})
                    except (ValueError, TypeError):
                        continue
            if len(rows) < 20:
                continue

            df = pd.DataFrame(rows)
            close = float(df["close"].iloc[-1])
            if close <= 0:
                continue

            c63 = float(df["close"].iloc[-63]) if len(df) >= 63 else float(df["close"].iloc[0])
            mom = (close - c63) / c63 * 100

            vl = float(df["volume"].iloc[-1])
            va = float(df["volume"].tail(20).mean())
            vr = vl / va if va > 0 else 1

            tu = float(df["close"].tail(20).mean()) > float(df["close"].tail(60).mean())

        except Exception:
            continue

        mmin, mmax = f["momentum"]
        if not (mmin <= mom <= mmax):
            continue
        vmin, vmax = f["volume_ratio"]
        if not (vmin <= vr <= vmax):
            continue
        if f["trend"] and not tu:
            continue

        mom_n = max(0, min(1, 1 - abs(mom - (mmin+mmax)/2) / ((mmax-mmin)/2)))
        vr_n = max(0, min(1, 1 - abs(vr - (vmin+vmax)/2) / ((vmax-vmin)/2)))
        t_n = 1.0 if tu else 0.5
        total = round((mom_n + vr_n + t_n) / 3, 3)

        result.append({
            "code": s["code"], "name": s["name"],
            "price": round(close, 2),
            "mom": round(mom, 1), "vr": round(vr, 2),
            "trend": tu, "score": total,
        })

    bs.logout()
    result.sort(key=lambda x: x["score"], reverse=True)
    return result[:top_n]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--output")
    args = ap.parse_args()

    candidates = scan(top_n=args.top)
    if not candidates:
        print("No candidates found")
        return

    print()
    print(f"{'Code':<8} {'Name':<10} {'Price':<8} {'Mom3M':<8} {'VolR':<8} {'Trend':<6} {'Score':<6}")
    print("-" * 56)
    for c in candidates:
        print(f"{c['code']:<8} {c['name']:<10} {c['price']:<8.2f} {c['mom']:<+7.1f}% {c['vr']:<8.2f} {'+' if c['trend'] else '-':<6} {c['score']:<6.3f}")
    print(f"\nTotal: {len(candidates)} candidates")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        f = REGIME_FACTORS.get(get_regime(), REGIME_FACTORS[DEFAULT_REGIME])
        lines = ["# v4 Factor Scan",
                 f"> Regime: {f['name']} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 "",
                 "| Code | Name | Price | Mom3M | VolR | Trend | Score |",
                 "|:----|:----|:----|:------|:----|:----|:----|"]
        for c in candidates:
            lines.append(f"| {c['code']} | {c['name']} | {c['price']:.2f} | {c['mom']:+.1f}% | {c['vr']:.2f} | {'+' if c['trend'] else '-'} | {c['score']:.3f} |")
        lines.append("")
        lines.append(f"*{len(candidates)} candidates*")
        out.write_text("\n".join(lines))
        print(f"Saved: {out}")


if __name__ == "__main__":
    main()
