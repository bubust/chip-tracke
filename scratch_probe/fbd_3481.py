"""暫時檢查：群創 3481 為什麼不在盤中假跌破清單（S_FBD 每個條件逐項算）"""
import json
import os
import sys

import httpx
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import scanner  # noqa: E402

BASE = "https://qiangni-tactics.fly.dev"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
sp = httpx.get(f"{BASE}/api/params/strategies", timeout=60).json()
p = (sp.get("saved") or sp).get("S_FBD") if isinstance(sp, dict) else None
print("S_FBD params:", json.dumps(p, ensure_ascii=False), "| raw keys:", list(sp)[:10] if isinstance(sp, dict) else type(sp))
st = httpx.get(f"{BASE}/api/fbd-live/status", timeout=60).json()
print("fbd-live status keys:", list(st))
print(json.dumps({k: v for k, v in st.items() if k not in ("hits", "seen", "list", "items")}, ensure_ascii=False)[:800])
blob = json.dumps(st, ensure_ascii=False)
print("3481 in status?", "3481" in blob)

j = httpx.get("https://query1.finance.yahoo.com/v8/finance/chart/3481.TW", params={"interval": "1d", "range": "1y"},
              headers=UA, timeout=60).json()
r = j["chart"]["result"][0]
q = r["indicators"]["quote"][0]
df = pd.DataFrame({"date": pd.to_datetime(r["timestamp"], unit="s").tz_localize("UTC").tz_convert("Asia/Taipei").strftime("%Y-%m-%d"),
                   "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                   "volume": [None if v is None else v / 1000 for v in q["volume"]]}).dropna().reset_index(drop=True)
print("bars", len(df), "last", df.tail(1).to_dict("records"))
c = df["close"]
ma10, ma60 = c.rolling(10).mean(), c.rolling(60).mean()
ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
dif = ema12 - ema26
osc = dif - dif.ewm(span=9, adjust=False).mean()
out = df.assign(ma10=ma10.round(2), ma60=ma60.round(2), osc=osc.round(3), vol20=df["volume"].rolling(20).mean().round(0))
print(out.tail(12).to_string())
P = p or {}
mr = int(P.get("macd_ref_days", 3))
print("\n條件（今天＝最後一根）：")
print(" 收盤>min_price", float(c.iloc[-1]), ">", P.get("min_price", 10))
print(" 今天量≥min_vol_lots", float(df['volume'].iloc[-1]), ">=", P.get("min_vol_lots", 300))
print(" MA10>MA60", float(ma10.iloc[-1]), float(ma60.iloc[-1]), ma10.iloc[-1] > ma60.iloc[-1])
print(" OSC<0 且比", mr, "天前縮短", float(osc.iloc[-1]), float(osc.iloc[-1 - mr]), osc.iloc[-1] < 0 and osc.iloc[-1] > osc.iloc[-1 - mr])
print(" 收紅且站上MA10", float(df['open'].iloc[-1]), "→", float(c.iloc[-1]), "MA10", float(ma10.iloc[-1]))
print(" 昨天收盤<昨天MA10", float(c.iloc[-2]), float(ma10.iloc[-2]), c.iloc[-2] < ma10.iloc[-2])
bw = int(P.get("break_window", 4))
for i in range(1, bw + 1):
    print(f"  {i} 天前 {df['date'].iloc[-(i+1)]} 收 {float(c.iloc[-(i+1)])} MA10 {float(ma10.iloc[-(i+1)]):.2f} 跌破 {c.iloc[-(i+1)] < ma10.iloc[-(i+1)]} 量 {float(df['volume'].iloc[-(i+1)]):.0f}")
print(" screen_sfbd →", scanner.screen_sfbd({"3481": df}, {"3481": "群創"}, P))
