#!/usr/bin/env python3
"""
market_daily_pipeline.py — 每日市场信号管线 (P4-1)

全自动编排: 采集数据 → 分类市况 → 锁定策略 → 生成报告

用法:
    python3 scripts/market_daily_pipeline.py              # 全流程
    python3 scripts/market_daily_pipeline.py --report-only # 仅输出报告(不锁定)
    python3 scripts/market_daily_pipeline.py --cache-clear # 清除缓存
    python3 scripts/market_daily_pipeline.py --dry-run     # 试跑不写文件
"""

import json, sys
from datetime import datetime
from pathlib import Path

# ── 路径 ──
KMS_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = KMS_ROOT / "scripts"
REPORT_DIR = Path("/mnt/e/AIGC-KB/wiki-AIGC-KB/08-investment/01-数据源与工具")
DASHBOARD_DIR = REPORT_DIR / "dashboard"

sys.path.insert(0, str(SCRIPTS_DIR))

REGIME_LABELS = {
    "bull_growth": "🐂 牛市·成长主线",
    "bull_value": "🐂 牛市·价值修复",
    "sideways": "🐢 震荡·方向不明",
    "bear_defense": "🐻 熊市·防御",
    "inflation": "🔥 通胀·资源行情",
}


def fetch_and_classify(dry_run: bool = False) -> dict:
    """采集+分类一体化"""
    from auto_market_fetch import fetch_index_data, compute_signals
    from market_classifier import classify

    print("[1/4] 采集指数行情...", end=" ", flush=True)
    index_data = fetch_index_data()
    print(f"{len(index_data)} 个指数")

    if "error" in index_data:
        print(f"❌ 采集失败: {index_data['error']}")
        return {"error": index_data["error"]}

    for name, d in index_data.items():
        if "close" in d:
            print(f"  {name}: {d['close']} ({d['pct_1d']:+.2f}%) 60日:{d['pct_60d']:+.2f}%")

    print("[2/4] 计算信号...", end=" ", flush=True)
    signals = compute_signals(index_data)
    print("完成")

    print("[3/4] 市场分类...", end=" ", flush=True)
    result = classify(signals)
    from market_classifier import print_report
    print_report(result)
    print()

    return {
        "timestamp": datetime.now().isoformat(),
        "index_data": index_data,
        "signals": signals,
        "classification": result,
    }


def auto_lock(result: dict, dry_run: bool = False):
    """自动锁定策略"""
    classification = result.get("classification", {})
    if not classification:
        print("⏭️  跳过策略锁定（无分类结果）")
        return

    r = classification.get("regime", {})
    strategy = classification.get("recommended_strategy", {})

    from strategy_lock import lock_strategy

    code = r.get("code", "sideways")
    label = r.get("label", "未知")
    confidence = r.get("confidence", 0.5)
    primary_id = strategy.get("id", "S1")

    # 市况→辅策略映射
    regime_secondary = {
        "bull_growth": "S2",  # 成长主线→优质价值
        "bull_value": "S1",   # 价值修复→深度价值
        "sideways": "S1",     # 震荡→深度价值
        "bear_defense": "S4", # 熊市→防御红利
        "inflation": "S5",    # 通胀→周期反转
    }
    secondary_id = regime_secondary.get(code, "S1")

    if dry_run:
        print(f"  (dry-run) 锁定: {label} → {primary_id} + {secondary_id} (置信度{confidence*100:.0f}%)")
        return

    lock_strategy(
        regime_code=code,
        regime_label=label,
        confidence=confidence,
        primary_id=primary_id,
        secondary_id=secondary_id,
        locked_by="pipeline"
    )


def generate_report(result: dict, output_path: Path) -> Path:
    """生成 Markdown 报告"""
    timestamp = result.get("timestamp", datetime.now().isoformat())
    ts_date = timestamp[:10]
    ts_time = timestamp[11:19]

    lines = []
    lines.append("---")
    lines.append(f"title: 📊 每日市场信号报告 {ts_date}")
    lines.append("type: daily-report")
    lines.append("domain: 投资研究")
    lines.append("tags: [每日信号, 市场分类, 策略锁定]")
    lines.append(f"created: {ts_date}")
    lines.append("---")
    lines.append("")
    lines.append(f"# 📊 每日市场信号报告 — {ts_date}")
    lines.append("")
    lines.append(f"> 生成时间: {ts_time} | 管线: market_daily_pipeline.py")
    lines.append("")

    classification = result.get("classification", {})
    r = classification.get("regime", {})
    strategy = classification.get("recommended_strategy", {})
    signals = classification.get("signals", {})

    lines.append("## 市场环境")
    lines.append("")
    label = r.get("label", "未知")
    conf = r.get("confidence", 0)
    reasons = r.get("reasons", [])
    lines.append(f"- **市况**: {label}")
    lines.append(f"- **置信度**: {conf*100:.0f}%")
    lines.append(f"- **理由**: {'; '.join(reasons)}")
    lines.append("")
    lines.append("## 推荐策略")
    lines.append("")
    lines.append(f"- **策略**: {strategy.get('name', '?')}")
    lines.append(f"- **Track**: {strategy.get('track', '?')}")
    lines.append(f"- **条件**: {strategy.get('conditions', '?')}")
    lines.append("")

    # 信号详情表
    lines.append("## 信号详情")
    lines.append("")
    lines.append("| 信号 | 值 |")
    lines.append("|:----|:---|")
    for k, v in signals.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # 指数行情
    index_data = result.get("index_data", {})
    if index_data:
        lines.append("## 指数行情")
        lines.append("")
        lines.append("| 指数 | 收盘 | 日涨跌 | 60日涨跌 |")
        lines.append("|:----|:-----|:------|:--------|")
        for name, d in index_data.items():
            if "close" in d:
                lines.append(f"| {name} | {d['close']} | {d['pct_1d']:+.2f}% | {d['pct_60d']:+.2f}% |")
        lines.append("")
    else:
        lines.append("## 指数行情")
        lines.append("")
        lines.append("*数据采集失败*")
        lines.append("")

    lines.append("---")
    lines.append(f"*报告由 `market_daily_pipeline.py` 自动生成 — {ts_date}*")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def main():
    import argparse
    ap = argparse.ArgumentParser(description="每日市场信号管线")
    ap.add_argument("--report-only", action="store_true", help="仅输出报告不锁定策略")
    ap.add_argument("--cache-clear", action="store_true", help="清除缓存")
    ap.add_argument("--dry-run", action="store_true", help="试跑不写文件")
    args = ap.parse_args()

    if args.cache_clear:
        cache_dir = KMS_ROOT / "config" / "cache"
        for f in cache_dir.glob("*market*"):
            f.unlink()
            print(f"已清除: {f.name}")
        print("✅ 缓存已清除")
        return

    print("=" * 55)
    print(f"📊 每日市场信号管线 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 55)

    # Step 1-3: 采集+分类
    result = fetch_and_classify(dry_run=args.dry_run)
    if "error" in result:
        print(f"❌ 管线中止: {result['error']}")
        sys.exit(1)

    classification = result.get("classification", {})
    if not classification:
        print("❌ 分类无结果，管线中止")
        sys.exit(1)

    # Step 4: 自动锁定策略（除非 --report-only）
    if not args.report_only:
        print("[4/4] 自动锁定策略...")
        auto_lock(result, dry_run=args.dry_run)

    # 保存JSON缓存（供 session_health 使用）
    cache_dir = KMS_ROOT / "config" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"market_classification_{datetime.now().strftime('%Y%m%d')}.json"
    if not args.dry_run:
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        # 同时写入最新版
        latest_file = KMS_ROOT / "config" / "cache" / "market_classification_latest.json"
        latest_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 结果已缓存: {cache_file}")

    # 生成Markdown报告
    date_str = datetime.now().strftime("%Y%m%d")
    report_file = DASHBOARD_DIR / f"{date_str}-market-report.md"
    if not args.dry_run:
        report_path = generate_report(result, report_file)
        print(f"✅ 报告已生成: {report_path}")
    else:
        print(f"⏭️  (dry-run) 跳过报告写入")

    print()
    print("✅ 每日市场信号管线完成")
    return result


if __name__ == "__main__":
    main()
