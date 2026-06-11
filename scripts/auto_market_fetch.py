#!/usr/bin/env python3
"""
自动市场数据采集 — Auto Market Data Fetcher v1

采集6路信号 → 喂给 market_classifier → 输出市况+推荐策略

数据源: akshare (指数行情) + web_search (辅助)
输出: JSON格式，可被 daily-review-orchestrator 调用
"""

import json, sys
from pathlib import Path
from datetime import datetime


def fetch_index_data() -> dict:
    """采集指数行情数据（直接 in-process，避免 CompressContext 子进程日志污染）"""
    import importlib
    try:
        ak = importlib.import_module("akshare")
    except ImportError:
        return {"error": "akshare 未安装"}

    indices = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
        "sh000688": "科创50",
        "sh899050": "北证50",
    }
    data = {}
    for code, name in indices.items():
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            if df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2]
            pct = (last["close"] - prev["close"]) / prev["close"] * 100
            idx_60 = max(0, len(df) - 60)
            close_60d = df.iloc[idx_60]["close"] if idx_60 < len(df) else df.iloc[0]["close"]
            pct_60d = (last["close"] - close_60d) / close_60d * 100
            data[name] = {
                "close": round(float(last["close"]), 2),
                "pct_1d": round(float(pct), 2),
                "pct_60d": round(float(pct_60d), 2),
                "volume": int(last["volume"]),
            }
        except Exception as e:
            data[name] = {"error": str(e)[:100]}
    return data


def compute_signals(index_data: dict) -> dict:
    """从指数数据计算分类器输入信号"""
    signals = {
        "index_60d_pct": 0,
        "volume_today": 0,
        "volatility_20d": 20,
        "growth_vs_value": 0,
        "top3_sector_pct": 25,
        "limit_up_count": 60,
        "sector_limit_up_peak": 8,
    }

    # 用沪深300或上证指数判断趋势
    if "上证指数" in index_data and "pct_60d" in index_data["上证指数"]:
        signals["index_60d_pct"] = index_data["上证指数"]["pct_60d"]

    # 用成交量估算成交额（粗略）
    if "上证指数" in index_data and "volume" in index_data["上证指数"]:
        vol = index_data["上证指数"]["volume"]
        signals["volume_today"] = round(vol / 1e8 * 5, 1)  # 粗略估算

    # 创业板 vs 上证判断风格
    if "创业板指" in index_data and "上证指数" in index_data:
        cy_pct = index_data["创业板指"].get("pct_60d", 0)
        sh_pct = index_data["上证指数"].get("pct_60d", 0)
        signals["growth_vs_value"] = round(cy_pct - sh_pct, 1)

    return signals


def main():
    print("[1/3] 采集指数数据...", end=" ", flush=True)
    index_data = fetch_index_data()
    print(f"{len(index_data)} 个指数")

    # 打印指数行情
    for name, d in index_data.items():
        if "close" in d:
            print(f"  {name}: {d['close']} ({d['pct_1d']:+.2f}%) 60日:{d['pct_60d']:+.2f}%")

    print("[2/3] 计算信号...", end=" ", flush=True)
    signals = compute_signals(index_data)
    print("完成")

    # 导入分类器
    sys.path.insert(0, "scripts")
    try:
        from market_classifier import classify, print_report
    except ImportError:
        print("❌ 无法导入 market_classifier")
        sys.exit(1)

    print("[3/3] 运行分类器...")
    result = classify(signals)
    print_report(result)

    # 输出JSON
    output = {
        "timestamp": datetime.now().isoformat(),
        "index_data": index_data,
        "signals": signals,
        "classification": {
            "regime": result["regime"]["label"],
            "confidence": result["regime"]["confidence"],
            "reasons": result["regime"]["reasons"],
            "recommended_strategy": result["recommended_strategy"]["name"],
        }
    }

    output_path = str(Path("/tmp") / "market_classification_latest.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {output_path}")

    return output


if __name__ == "__main__":
    main()
