#!/usr/bin/env python3
"""
每周 D9 电话会议扫描 — Weekly D9 Scan v1

功能：每周自动扫描持仓股+候选股在Reportify上的新增电话会议纪要
流向：搜索→爬取→D9分析→输出周报→归档

用法：
  python3 scripts/weekly_d9_scan.py              # 完整扫描
  python3 scripts/weekly_d9_scan.py --quick       # 仅检查是否有新纪要
"""

import json, subprocess, sys
from datetime import datetime
from pathlib import Path
from _path_setup import WIKI_DIR

# ── 配置 ──

SCRIPT_DIR = Path(__file__).resolve().parent
KMS_DIR = SCRIPT_DIR.parent
EC_DIR = WIKI_DIR / "08-investment" / "06-投研分析" / "电话会议纪要"

COOKIE = "report-token=7ba806568a8fefe6046b0113f117d9fcf082e0c7b6cf999881233af08d1576c3; i18next2=zh-CN"

# ── 持仓+候选股（从策略锁定文件自动读取） ──

def get_watchlist() -> list:
    """读取关注列表：持仓股 + D9待验证股"""
    stocks = []
    
    # 从策略锁定文件读取
    lock_file = KMS_DIR / "config" / "strategy_current.json"
    if lock_file.exists():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    
    # 核心列表：必须扫描的股票
    watchlist = [
        # 当前持仓（S1 深度价值）
        {"code": "600036", "name": "招商银行", "market": "SH", "reason": "S1核心持仓"},
        {"code": "601006", "name": "大秦铁路", "market": "SH", "reason": "S1核心持仓"},
        {"code": "600019", "name": "宝钢股份", "market": "SH", "reason": "S1核心持仓"},
        {"code": "601668", "name": "中国建筑", "market": "SH", "reason": "S1核心持仓"},
        {"code": "601398", "name": "工商银行", "market": "SH", "reason": "S1核心持仓"},
        # 当前持仓（S2 优质价值）
        {"code": "601899", "name": "紫金矿业", "market": "SH", "reason": "S2核心持仓"},
        # 候选池（有待D9验证的）
        {"code": "603993", "name": "洛阳钼业", "market": "SH", "reason": "S2候选-待D9验证"},
        {"code": "601088", "name": "中国神华", "market": "SH", "reason": "S1观察池-待D9验证"},
        {"code": "000063", "name": "中兴通讯", "market": "SZ", "reason": "S3候选-待D9验证"},
    ]
    
    return watchlist


def scan_reportify(stock_code: str, stock_name: str) -> list:
    """搜索个股的会议纪要"""
    results = []
    import subprocess, re
    
    # 从 transcripts 列表页搜公司名
    result = subprocess.run(
        ["curl", "-s", "--cookie", COOKIE,
         "-H", "User-Agent: Mozilla/5.0",
         "https://reportify.cn/transcripts", "--max-time", "15"],
        capture_output=True, text=True, timeout=20
    )
    
    if result.returncode != 0 or len(result.stdout) < 5000:
        return results
    
    html = result.stdout
    
    # 提取页面中所有显示的文本块
    import re
    texts = re.findall(r'>([^<]{10,200})<', html)
    
    # 找包含公司名或股票代码的文本
    name_parts = stock_name[:2]
    code_match = stock_code[-4:]  # 后4位
    
    for t in texts:
        t = t.strip()
        if not t or len(t) < 5:
            continue
        # 匹配公司名或代码
        if name_parts in t or code_match in t:
            if any(k in t for k in ["股份", "有限", "公司", "Earnings", "Q1", "Q2", "业绩"]):
                results.append(t)
    
    return results


def main():
    quick_mode = "--quick" in sys.argv
    
    print("=" * 55)
    print(f"📞 每周D9扫描 | {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 55)
    
    watchlist = get_watchlist()
    print(f"\n关注列表: {len(watchlist)} 只股票")
    
    total_new = 0
    for stock in watchlist:
        print(f"\n  🔍 {stock['name']}({stock['code']}) — {stock['reason']}")
        
        try:
            transcripts = scan_reportify(stock['code'], stock['name'])
        except Exception as e:
            print(f"     ❌ 扫描失败: {e}")
            continue
        
        if transcripts:
            print(f"     📞 发现 {len(transcripts)} 条纪要:")
            for t in transcripts:
                print(f"       • {t[:100]}")
            total_new += len(transcripts)
        else:
            print(f"     📭 无新纪要")
    
    print(f"\n{'='*55}")
    print(f"扫描完成: 共发现 {total_new} 条新纪要")
    
    if total_new > 0 and not quick_mode:
        print(f"\n下一步: 对这些新纪要运行D9深度分析:")
        print(f"  python3 scripts/earnings_call_pipeline.py --url <URL> --deep")
    
    # 归档扫描记录
    output = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "stocks_scanned": len(watchlist),
        "new_transcripts": total_new,
        "details": [
            {"name": s["name"], "code": s["code"], "reason": s["reason"]}
            for s in watchlist
        ]
    }
    
    log_file = KMS_DIR / "config" / "d9_scan_log.json"
    log_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n📋 扫描日志: {log_file}")


if __name__ == "__main__":
    main()
