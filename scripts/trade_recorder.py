#!/usr/bin/env python3
"""统一交易记录器 — 投资体系内所有调仓行为的唯一写入入口

功能：
  1. 回测/信号脚本导入调用 → 自动写 TradeLedger CSV
  2. CLI 手动记录（适配器模式） → 一条命令记一笔交易
  3. 自动格式映射（backtest_futures trade_log → TradeLedger schema）

用法:
  # 手动录一笔
  python3 scripts/trade_recorder.py record --action BUY --code IM --price 4880 --volume 1 --reason "基差策略开仓"

  # 导入使用
  from trade_recorder import record_trade, record_backtest
  
  record_trade(code='IM', action='BUY', price=4880.0, volume=1, reason='基差策略开仓', source='manual')
  
  record_backtest(result_dict, code='IM', strategy='basis')

数据流:
  任何调仓行为 → trade_recorder.record_trade() → TradeLedger CSV → D10 emotion_detector 每日自检
"""

import sys, os, json, argparse
from datetime import datetime
from pathlib import Path

# ── TradeLedger 路径 ──
DEFAULT_LEDGER_DIR = Path(os.environ.get("BLACKHORSE_LEDGER_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "输出" / "investment-engine" / "data" / "ledger")))

# ── 回测 trade_log 到 TradeLedger 的字段映射 ──
BACKTEST_FIELD_MAP = {
    "date": "date",
    "price": "price",
    "reason": "reason",
}
# backtest action: BUY/SELL → TradeLedger action（不变）
# backtest pnl → 不直接写入 TradeLedger（汇总层，不在明细层）

# ══════════════════════════════════════════════════════════
#  核心函数
# ══════════════════════════════════════════════════════════

def _get_ledger():
    """延迟导入 TradeLedger，避免循环依赖"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "输出" / "investment-engine" / "strategies"))
        from trade_ledger import TradeLedger
        return TradeLedger(str(DEFAULT_LEDGER_DIR))
    except ImportError as e:
        print(f"  [trade_recorder] ⚠️ TradeLedger 模块不可用: {e}")
        print(f"  请确认 : {DEFAULT_LEDGER_DIR}")
        raise


def record_trade(code: str, action: str, price: float, volume: int,
                 reason: str = "", signal: str = "HOLD",
                 position_pct: float = 0.0, name: str = "",
                 status: str = "EXECUTED",
                 date: str = None,
                 source: str = "manual",
                 awareness_log: str = "") -> str:
    """统一记录一笔交易到 TradeLedger

    参数:
        code: 品种代码 (IM/IC/IF/IH/股票代码)
        action: BUY/SELL/ADD/REDUCE
        price: 成交价格
        volume: 成交数量（手/股）
        reason: 原因描述（开仓/止损/止盈/信号反转）
        signal: 触发信号（BUY/HOLD/SELL/ADD/REDUCE/SKIP）
        position_pct: 该笔占仓位比例
        name: 品种名称
        status: EXECUTED(默认) / PENDING / PARTIAL / CANCELLED
        date: 交易日期（默认今天）
        source: 数据来源 (manual/backtest/live/backfill)
        awareness_log: 觉察日志 JSON 字符串

    返回:
        record_id: "日期_代码" 格式
    """
    if action not in ("BUY", "SELL", "ADD", "REDUCE"):
        raise ValueError(f"不支持的动作: {action}，仅支持 BUY/SELL/ADD/REDUCE")

    _date = date or datetime.now().strftime("%Y-%m-%d")
    _signal = signal if signal != "HOLD" else (action if action in ("BUY", "SELL") else "HOLD")

    ledger = _get_ledger()
    record = {
        "date": _date,
        "code": code,
        "name": name or code,
        "signal": _signal,
        "action": action,
        "position_pct": position_pct,
        "price": price,
        "volume": volume,
        "reason": reason,
        "status": status,
        "awareness_log": awareness_log,
    }
    record_id = ledger.add_record(record)
    print(f"  ✓ 已记录: {code} {action} {volume}手@{price} → {record_id} (来源: {source})")
    return record_id


def record_backtest(result: dict, code: str = "", strategy: str = "",
                    source: str = "backtest") -> int:
    """回测结果落地 TradeLedger

    读取 result['trade_log'] 中的交易记录（开仓/平仓/强平），
    自动转换成 TradeLedger 格式写入。

    返回:
        写入的记录数
    """
    trade_log = result.get("trade_log", [])
    if not trade_log:
        print("  [trade_recorder] 回测无交易记录可落地")
        return 0

    count = 0
    for t in trade_log:
        date = t.get("date")
        # date 可能是 datetime 或 string
        if hasattr(date, 'strftime'):
            date = date.strftime("%Y-%m-%d")
        else:
            date = str(date)[:10]

        action = t.get("action", "")
        reason = t.get("reason", "")
        price = t.get("price", 0.0)

        # 将 backtest action 映射到 TradeLedger schema
        # BUY → BUY, SELL → SELL, FORCE_CLOSE → SELL
        mapped_action = "SELL" if action in ("SELL", "FORCE_CLOSE") else "BUY"

        # 计算 volume（从 pnl 和 price 反推，backtest_futures 固定1手）
        volume = 1  # backtest_futures 固定1手

        record_trade(
            code=code,
            action=mapped_action,
            price=float(price),
            volume=volume,
            reason=reason,
            signal=mapped_action,
            date=date,
            source=source,
        )
        count += 1

    print(f"  [trade_recorder] 回测结果已落地: {count} 笔交易 → TradeLedger")
    return count


def record_batch(trades: list) -> int:
    """批量记录（用于数据迁移/回填）"""
    count = 0
    for t in trades:
        record_trade(**t)
        count += 1
    return count


# ══════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="统一交易记录器 — TradeLedger 写入入口")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── record ──
    p_record = sub.add_parser("record", help="记录一笔交易")
    p_record.add_argument("--code", required=True, help="品种代码 (IM/IC/IF/IH/股票)")
    p_record.add_argument("--action", required=True, choices=["BUY", "SELL", "ADD", "REDUCE"], help="买卖动作")
    p_record.add_argument("--price", type=float, required=True, help="成交价格")
    p_record.add_argument("--volume", type=int, required=True, help="成交数量(手/股)")
    p_record.add_argument("--reason", default="", help="原因")
    p_record.add_argument("--signal", default="", help="信号 (BUY/HOLD/SELL)")
    p_record.add_argument("--date", default="", help="交易日期 (默认今天)")
    p_record.add_argument("--name", default="", help="品种名称")
    p_record.add_argument("--source", default="cli", help="数据来源")

    # ── backtest ──
    p_bt = sub.add_parser("backtest", help="回测结果落地 TradeLedger (从回测结果 JSON 文件)")
    p_bt.add_argument("--result", required=True, help="回测结果 JSON 文件路径")
    p_bt.add_argument("--code", default="IM", help="期货合约代码")
    p_bt.add_argument("--strategy", default="basis", help="策略名称")

    # ── list ──
    p_list = sub.add_parser("list", help="查看最近交易记录")
    p_list.add_argument("--limit", type=int, default=20, help="显示条数")
    p_list.add_argument("--code", default="", help="按代码过滤")

    args = parser.parse_args()

    if args.cmd == "record":
        record_trade(
            code=args.code,
            action=args.action,
            price=args.price,
            volume=args.volume,
            reason=args.reason,
            signal=args.signal or args.action,
            date=args.date or None,
            name=args.name or args.code,
            source=args.source,
        )

    elif args.cmd == "backtest":
        path = Path(args.result)
        if not path.exists():
            print(f"❌ 回测结果文件不存在: {path}")
            sys.exit(1)
        with open(path, "r") as f:
            result = json.load(f)
        record_backtest(result, code=args.code, strategy=args.strategy)

    elif args.cmd == "list":
        ledger = _get_ledger()
        rows = ledger.query(code=args.code or None, limit=args.limit)
        if not rows:
            print("  TradeLedger: 空（暂无交易记录）")
            return
        print(f"\n  {'日期':<12} {'代码':<8} {'动作':<8} {'价格':<10} {'数量':<6} {'原因':<14} {'觉察':<6}")
        print(f"  {'-'*64}")
        for r in rows:
            awareness = "✓" if r.get("awareness_log", "") else ""
            print(f"  {r.get('date','')[:10]:<12} {r.get('code',''):<8} {r.get('action',''):<8} "
                  f"{r.get('price',''):<10} {r.get('volume',''):<6} {r.get('reason','')[:14]:<14} {awareness:<6}")


if __name__ == "__main__":
    main()
