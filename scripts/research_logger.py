#!/usr/bin/env python3
"""
research_logger — 投资研究结构化日志模块
=========================================
基于 agent-skills observability-and-instrumentation 设计。

功能:
- Structured Logging (JSON 格式)
- RED 指标追踪 (Rate/Errors/Duration)
- 症状告警

用法:
    from research_logger import log_event, record_metric, check_alert
    
    log_event("signal_generated", stock="600519", value=0.73)
    record_metric("factor_duration", 0.032, labels={"factor": "momentum"})
    check_alert("signal_zero", signal_count)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, Optional

# 配置
LOG_DIR = Path(os.environ.get("IE_ROOT", "/mnt/e/AIGC-KB/investment-engine")) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 指标存储 (内存版)
_metrics: Dict[str, list] = defaultdict(list)

# 告警规则
ALERTS = {
    "signal_zero": {
        "condition": lambda count: count == 0,
        "severity": "page",
        "message": "今日无信号生成",
    },
    "factor_anomaly_rate_high": {
        "condition": lambda rate: rate > 0.1,
        "severity": "ticket",
        "message": "因子异常率超过10%",
    },
    "backtest_drawdown_exceed": {
        "condition": lambda dd: dd < -0.2,
        "severity": "page",
        "message": "回测最大回撤超过20%",
    },
}


def log_event(event_name: str, **fields) -> str:
    """
    输出结构化日志。
    
    Args:
        event_name: 事件名称
        **fields: 其他字段
    
    Returns:
        JSON 字符串
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event_name,
        **fields
    }
    
    # 输出到控制台 (JSON 格式)
    output = json.dumps(log_entry, ensure_ascii=False)
    print(output, flush=True)
    
    # 可选：写入文件
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(output + "\n")
    except Exception:
        pass  # 静默失败，不阻塞主流程
    
    return output


def record_metric(name: str, value: float, labels: Optional[Dict] = None):
    """
    记录指标。
    
    Args:
        name: 指标名
        value: 指标值
        labels: 标签 (可选)
    """
    _metrics[name].append({
        "value": value,
        "labels": labels or {},
        "timestamp": datetime.now().timestamp()
    })


def get_metric(name: str, percentile: float = 0.95) -> float:
    """
    获取指标百分位。
    
    Args:
        name: 指标名
        percentile: 百分位 (0-1)
    
    Returns:
        百分位值
    """
    values = [m["value"] for m in _metrics.get(name, [])]
    if not values:
        return 0.0
    values.sort()
    idx = int(len(values) * percentile)
    return values[min(idx, len(values) - 1)]


def check_alert(alert_name: str, value: Any) -> Optional[Dict]:
    """
    检查告警条件。
    
    Args:
        alert_name: 告警名
        value: 当前值
    
    Returns:
        告警信息 或 None
    """
    if alert_name not in ALERTS:
        return None
    
    rule = ALERTS[alert_name]
    if rule["condition"](value):
        alert_info = {
            "alert": alert_name,
            "severity": rule["severity"],
            "message": rule["message"],
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        
        # 输出告警
        log_event("alert_triggered", **alert_info)
        
        return alert_info
    
    return None


def get_recent_events(event_name: str, hours: int = 24) -> list:
    """
    获取最近的事件。
    
    Args:
        event_name: 事件名
        hours: 小时数
    
    Returns:
        事件列表
    """
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
    if not log_file.exists():
        return []
    
    events = []
    cutoff = datetime.now().timestamp() - hours * 3600
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("event") == event_name:
                        if entry.get("timestamp", "") >= datetime.fromtimestamp(cutoff).isoformat():
                            events.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    return events


# ===== 投资研究专用便捷函数 =====

def log_signal(stock: str, factor: str, value: float, direction: str):
    """记录信号生成"""
    log_event("signal_generated",
        stock=stock,
        factor=factor,
        value=value,
        direction=direction)


def log_factor_calc(factor: str, duration: float, status: str = "success"):
    """记录因子计算"""
    log_event("factor_calculation",
        factor=factor,
        duration=duration,
        status=status)
    record_metric("factor_calculation_duration", duration, labels={"factor": factor})


def log_backtest(result: Dict):
    """记录回测结果"""
    log_event("backtest_completed",
        total_return=result.get("total_return", 0),
        sharpe=result.get("sharpe", 0),
        max_drawdown=result.get("max_drawdown", 0),
        trades=result.get("trades", 0))


def log_data_fetch(source: str, stocks: int, duration: float, status: str = "success"):
    """记录数据获取"""
    log_event("data_fetch",
        source=source,
        stocks=stocks,
        duration=duration,
        status=status)
    record_metric("data_fetch_duration", duration, labels={"source": source})


if __name__ == "__main__":
    # 测试
    print("=== Research Logger Test ===")
    
    log_event("test_event", message="hello")
    
    record_metric("test_metric", 0.5)
    record_metric("test_metric", 0.7)
    record_metric("test_metric", 0.9)
    
    print(f"p95: {get_metric('test_metric', 0.95)}")
    
    check_alert("signal_zero", 0)
    check_alert("signal_zero", 5)
    
    log_signal("600519", "momentum", 0.73, "long")
    log_factor_calc("volume_ratio", 0.032)
    log_backtest({"total_return": 0.15, "sharpe": 1.45, "max_drawdown": -0.08, "trades": 234})
    log_data_fetch("baostock", 5000, 12.5)
    
    print("=== Test Complete ===")
