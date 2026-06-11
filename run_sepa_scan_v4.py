#!/usr/bin/env python3
"""SEPA全市场扫描 v4 — akshare stock_info_a_code_name + stock_zh_a_hist"""
import sys; sys.path.insert(0, ".")
import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

COL_MAP = {"日期":"date","开盘":"open","收盘":"close","最高":"high","最低":"low",
           "成交量":"volume","成交额":"amount","涨跌幅":"pctChg","换手率":"turn"}

def fetch_kl(code, days=365):
    try:
        import akshare as ak
        end = datetime.now()
        start = end - timedelta(days=int(days*1.5))
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                 start_date=start.strftime("%Y%m%d"),
                                 end_date=end.strftime("%Y%m%d"), adjust="qfq")
        if df.empty: return None
        df = df.rename(columns=COL_MAP)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except:
        return None

def rs_ret(df):
    if df is None or len(df) < 252: return None
    r = df.tail(252)
    return float((r["close"].iloc[-1] / r["close"].iloc[0] - 1) * 100)

def trend8(code, df):
    if df is None or len(df) < 200: return None, 0
    df = df.copy()
    df["ma50"] = df["close"].rolling(50).mean()
    df["ma150"] = df["close"].rolling(150).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    l = df.iloc[-1]
    pc = 0
    if l["close"] > l["ma150"] and l["close"] > l["ma200"]: pc += 1
    if l["ma150"] > l["ma200"]: pc += 1
    idx = max(0, len(df)-22)
    if l["ma200"] > df["ma200"].iloc[idx]: pc += 1
    if l["ma50"] > l["ma150"] and l["ma50"] > l["ma200"]: pc += 1
    if l["close"] > l["ma50"]: pc += 1
    low52 = df["low"].tail(250).min() if len(df)>=250 else df["low"].min()
    if (l["close"]/low52-1)*100 >= 30: pc += 1
    high52 = df["high"].tail(250).max() if len(df)>=250 else df["high"].max()
    if (1-l["close"]/high52)*100 <= 25: pc += 1
    mh = (l["close"] > l["ma50"] > l["ma150"] > l["ma200"])
    return pc >= 7 and bool(mh), pc  # C1-C7共7个条件, C8=RS已通过前面过滤

def vcp_detect(df):
    if df is None or len(df) < 100: return False, 0, 0
    tt_pass, _ = trend8("", df)
    if not tt_pass: return False, 0, 0
    r = df.tail(250).reset_index(drop=True)
    h, lo = r["high"].values, r["low"].values
    peaks, tro = [], []
    for i in range(5, len(h)-5):
        if all(h[i]>=h[i-5:i]) and all(h[i]>=h[i+1:i+6]): peaks.append(i)
        if all(lo[i]<=lo[i-5:i]) and all(lo[i]<=lo[i+1:i+6]): tro.append(i)
    rets = []
    for pi in peaks:
        ft = [t for t in tro if pi<t<pi+50]
        if not ft: continue
        d = (h[pi]-lo[ft[0]])/h[pi]*100
        if d >= 2: rets.append({"d":d, "pi":pi, "ti":ft[0], "pv":h[pi]})
    if len(rets) < 3: return False, 0, 0
    last = rets[-3:]
    ds = [x["d"] for x in last]
    if not all(ds[i]>=ds[i+1] for i in range(len(ds)-1)): return False, 0, 0
    vols = [float(r["volume"].iloc[x["pi"]:x["ti"]+1].mean()) for x in last]
    ov = float(r["volume"].mean())
    vdu = vols[-1] < ov * 0.6 if ov > 0 else False
    score = 30 + (20 if all(vols[i]>=vols[i+1] for i in range(len(vols)-1)) else 0) + (20 if vdu else 0) + (10 if len(rets)>=4 else 5)
    return True, score, float(last[-1]["pv"])

def name_of(code):
    try:
        import akshare as ak
        df = ak.stock_individual_info_em(symbol=code)
        r = df[df["item"]=="股票简称"]
        return str(r["value"].iloc[0]) if not r.empty else code
    except: return code

# === MAIN ===
t0 = time.time()
print(f"\n{'='*70}")
print(f"SEPA 全市场扫描 v4 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*70}")

# Step 1
import akshare as ak
dfl = ak.stock_info_a_code_name()
all_codes = [c for c in dfl["code"].tolist() if not c.startswith("8")]
print(f"\n[1/4] 全A股: {len(all_codes)} 只")

# Step 2
print(f"[2/4] 并行获取K线 (8线程)...")
cache, rs_dict = {}, {}
lock = __import__("threading").Lock()
def worker(c):
    try:
        d = fetch_kl(c, 365)
        if d is None: return
        with lock: cache[c] = d
        r = rs_ret(d)
        if r is not None: rs_dict[c] = r
    except: pass

with ThreadPoolExecutor(max_workers=8) as pool:
    futs = {pool.submit(worker, c): c for c in all_codes}
    done, n = 0, len(all_codes)
    for f in as_completed(futs):
        done += 1
        if done % 300 == 0:
            print(f"  {done}/{n} (K线:{len(cache)} RS:{len(rs_dict)})")

print(f"  完成: {len(cache)} K线, {len(rs_dict)} RS  {time.time()-t0:.0f}s")

# Step 3
if not rs_dict:
    print("❌ 无RS数据，扫描终止")
    sys.exit(1)

all_ret = sorted(rs_dict.values())
def rsp(r): return (sum(1 for x in all_ret if x < r)/len(all_ret))*100

high_rs = [(c, rsp(v)) for c, v in rs_dict.items() if rsp(v) >= 70]
print(f"[3/4] RS≥70%: {len(high_rs)} 只")

# Step 4
print(f"[4/4] 趋势模板+VCP...")
cands = []
for idx, (code, rp) in enumerate(high_rs):
    if idx % 100 == 0 and idx > 0:
        print(f"  {idx}/{len(high_rs)} (通过:{len(cands)})")
    df = cache.get(code)
    if df is None: continue
    ok, pc = trend8(code, df)
    if not ok: continue
    vcp, vs, pv = vcp_detect(df)
    price = float(df["close"].iloc[-1])
    in_zone = 0 <= (price/pv-1)*100 <= 5 if vcp and pv > 0 else False
    score = min(pc*5, 40) + (min(vs*0.3,30) if vcp else 0) + (20 if in_zone else 0) + min(rp*0.1,10)
    cands.append({"c":code,"n":"?","rs":rp,"tt":pc,"v":"✅" if vcp else "❌","vs":vs,
                  "e":"✅" if in_zone else "❌","pv":pv,"p":price,"s":round(score,0)})

# Names (just for top)
top = sorted(cands, key=lambda x: x["s"], reverse=True)[:30]
for c in top:
    c["n"] = name_of(c["c"])

# Output
print(f"\n{'='*100}")
if not top:
    print("❌ 全市场无 SEPA 候选股")
else:
    print(f"✅ Top {len(top)} SEPA 候选股")
    print(f"{'代码':<8} {'名称':<12} {'RS%':<5} {'TT':<4} {'VCP':<4} {'V分':<4} {'入场':<4} {'枢轴':<10} {'现价':<8} {'总分':<5}")
    print(f"{'='*100}")
    for c in top:
        print(f"{c['c']:<8} {str(c['n']):<12} {c['rs']:<5.0f} {c['tt']:<4} "
              f"{c['v']:<4} {c['vs']:<4} {c['e']:<4} {c['pv']:<10.2f} {c['p']:<8.2f} {c['s']:<5.0f}")

print(f"\n{'='*100}")
print(f"总计: {len(all_codes)} 只 | RS>70%: {len(high_rs)} | 候选: {len(cands)}")
print(f"耗时: {time.time()-t0:.0f}s")
print(f"⚠️ 仅供学习研究，不构成投资建议。")
