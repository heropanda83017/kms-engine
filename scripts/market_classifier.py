#!/usr/bin/env python3
"""
市场环境分类器 v1 — Market Regime Classifier

输入：当前市场数据（指数涨跌/成交额/波动率/风格/行业集中度）
输出：5类市况标签 + 推荐策略 + 置信度

集成：可嵌入每日复盘管线（daily-review-orchestrator）
"""

import json, math
from datetime import datetime

# ── 策略定义 ──────────────────────────────────────────────────────

STRATEGIES = {
    "S1": {"name": "深度价值", "track": "Track A", "conditions": "PE<12+PB<1.5+股息率>3%+ROE>5%"},
    "S2": {"name": "优质价值", "track": "Track B", "conditions": "PE<15+ROE>15%+利润增速>10%+股息率>2%"},
    "S3": {"name": "景气成长", "track": "TBD",     "conditions": "PEG<1+营收增速>30%+ROE>10%"},
    "S4": {"name": "防御红利", "track": "TBD",     "conditions": "股息率>5%+PB<1+经营现金流>净利润"},
    "S5": {"name": "周期反转", "track": "TBD",     "conditions": "PB<1+毛利率触底回升+库存下降"},
}

REGIME_MAP = {
    "bull_growth":   {"label": "🐂 牛市·成长主线",  "strategy": "S3", "desc": "大盘涨+高成交+成长领涨"},
    "bull_value":    {"label": "🐂 牛市·价值修复",  "strategy": "S2", "desc": "大盘涨+低估值领涨"},
    "sideways":      {"label": "🐢 震荡·方向不明", "strategy": "S1", "desc": "大盘横盘+成交正常+主线不明确"},
    "bear_defense":  {"label": "🐻 熊市·防御",     "strategy": "S4", "desc": "大盘跌+低成交+避险情绪"},
    "inflation":     {"label": "🔥 通胀·资源行情",  "strategy": "S5", "desc": "大宗商品涨+周期领涨"},
}


def classify(market_data: dict) -> dict:
    """
    市场分类主函数

    输入 market_data 格式：
    {
        "index_60d_pct": float,       # 沪深300 60日涨跌幅(%)
        "volume_20d_avg": float,      # 20日日均成交额(亿)
        "volume_today": float,        # 当日成交额(亿)
        "volatility_20d": float,      # 20日年化波动率(%)
        "growth_vs_value": float,     # 成长/价值风格相对强弱(%, >0成长强)
        "top3_sector_pct": float,     # 涨幅前3行业成交额占比(%)
        "limit_up_count": int,        # 涨停家数
        "sector_limit_up_peak": int,  # 最强板块涨停数
    }
    """
    # ── 阈值定义（可调参数） ──
    TREND_BULL = 5.0       # 60日涨>5%→牛市
    TREND_BEAR = -5.0      # 60日跌>5%→熊市
    VOL_HIGH = 25.0        # 波动率>25%→高波动
    VOLUME_HIGH = 20000    # 成交额>2万亿→活跃
    VOLUME_LOW = 10000     # 成交额<1万亿→低迷
    STYLE_GROWTH = 3.0     # 成长强于价值>3%
    CONCENTRATION = 30.0   # 前3行业占比>30%→主线明确
    LIMIT_UP_HOT = 80      # 涨停>80只→市场活跃
    SECTOR_HOT = 15        # 最强板块涨停>15只→主线确立

    signals = {}
    score = {}

    # 1. 趋势信号
    idx_pct = market_data.get("index_60d_pct", 0)
    if idx_pct > TREND_BULL:
        signals["trend"] = "bull"
        score["trend"] = min((idx_pct - TREND_BULL) / 5, 1.0)
    elif idx_pct < TREND_BEAR:
        signals["trend"] = "bear"
        score["trend"] = min((TREND_BEAR - idx_pct) / 5, 1.0)
    else:
        signals["trend"] = "sideways"
        score["trend"] = 0.5

    # 2. 成交额信号
    vol_today = market_data.get("volume_today", 15000)
    if vol_today > VOLUME_HIGH:
        signals["volume"] = "active"
    elif vol_today < VOLUME_LOW:
        signals["volume"] = "sluggish"
    else:
        signals["volume"] = "normal"

    # 3. 波动率信号
    vol = market_data.get("volatility_20d", 20)
    signals["volatility"] = "high" if vol > VOL_HIGH else "normal"

    # 4. 风格信号
    style = market_data.get("growth_vs_value", 0)
    if style > STYLE_GROWTH:
        signals["style"] = "growth"
    elif style < -STYLE_GROWTH:
        signals["style"] = "value"
    else:
        signals["style"] = "balanced"

    # 5. 主线集中度
    concentration = market_data.get("top3_sector_pct", 20)
    signals["concentration"] = "focused" if concentration > CONCENTRATION else "dispersed"

    # 6. 涨停热度
    limit_up = market_data.get("limit_up_count", 50)
    signals["limit_up"] = "hot" if limit_up > LIMIT_UP_HOT else "normal"

    sector_peak = market_data.get("sector_limit_up_peak", 5)
    signals["main_line"] = "confirmed" if sector_peak > SECTOR_HOT else "unclear"

    # ── 决策逻辑 ──
    decision = None
    confidence = 0.0
    reasons = []

    if signals["trend"] == "bull":
        if signals["style"] == "growth" and signals["main_line"] == "confirmed":
            decision = "bull_growth"
            confidence = 0.85
            reasons.append("牛市+成长领涨+主线确立")
        elif signals["style"] == "value":
            decision = "bull_value"
            confidence = 0.80
            reasons.append("牛市+价值领涨")
        elif signals["volume"] == "active" and signals["limit_up"] == "hot":
            decision = "bull_growth"
            confidence = 0.65
            reasons.append("牛市+活跃成交，疑似成长主线")
        else:
            decision = "bull_value"
            confidence = 0.55
            reasons.append("牛市+方向不明，倾向价值防御")

    elif signals["trend"] == "bear":
        if signals["volume"] == "sluggish":
            decision = "bear_defense"
            confidence = 0.85
            reasons.append("熊市+低成交，避险模式")
        else:
            decision = "bear_defense"
            confidence = 0.70
            reasons.append("熊市+防御优先")

    else:  # sideways
        # 检查是否通胀/资源行情
        if signals["style"] == "value" and signals["concentration"] == "focused":
            decision = "inflation"
            confidence = 0.70
            reasons.append("震荡+价值领涨+集中度高，疑似资源行情")
        elif signals["style"] == "growth":
            decision = "bull_growth"
            confidence = 0.50
            reasons.append("震荡+成长偏强，轻仓参与")
        else:
            decision = "sideways"
            confidence = 0.75
            reasons.append("震荡+无明确方向，深度价值防御")

    # fallback
    if decision is None:
        decision = "sideways"
        confidence = 0.50
        reasons.append("信号混乱，默认震荡")

    regime = REGIME_MAP[decision]
    strategy = STRATEGIES[regime["strategy"]]

    return {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "regime": {
            "code": decision,
            "label": regime["label"],
            "confidence": round(confidence, 2),
            "reasons": reasons,
        },
        "recommended_strategy": {
            "id": regime["strategy"],
            "name": strategy["name"],
            "track": strategy["track"],
            "conditions": strategy["conditions"],
        },
        "signals": signals,
        "market_data_snapshot": market_data,
    }


def print_report(result: dict):
    """打印分类结果"""
    r = result
    print("\n" + "=" * 55)
    print(f"📊 市场环境分类报告")
    print("=" * 55)
    print(f"  时间: {r['datetime']}")
    print()
    print(f"  🏷️  当前市况: {r['regime']['label']}")
    print(f"  🎯 置信度: {r['regime']['confidence']*100:.0f}%")
    print(f"  📌 理由: {'; '.join(r['regime']['reasons'])}")
    print()
    print(f"  🧠 推荐策略: {r['recommended_strategy']['name']}")
    print(f"     ({r['recommended_strategy']['conditions']})")
    print()
    print(f"  📡 信号详情:")
    for k, v in r['signals'].items():
        print(f"     {k}: {v}")
    print("=" * 55)


# ── 测试：用6/5复盘数据 ──
if __name__ == "__main__":
    # 6月5日真实数据
    test_data = {
        "index_60d_pct": -2.1,        # 沪深300近60日小幅下跌
        "volume_20d_avg": 28000,       # 近20日均成交额2.8万亿
        "volume_today": 31000,         # 当日3.1万亿（放量）
        "volatility_20d": 28,          # 高波动（科创50-4%/北证50+5.6%）
        "growth_vs_value": -2.0,       # 成长略弱于价值（高低切换中）
        "top3_sector_pct": 25,         # 前3板块占比25%（分散）
        "limit_up_count": 73,          # 73只涨停
        "sector_limit_up_peak": 10,    # 玻璃基板10+只涨停（但未到15只确立线）
    }

    result = classify(test_data)
    print_report(result)
