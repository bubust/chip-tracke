"""B118 回測資料（GitHub Actions 跑）：Yahoo 日 K 5 年（1,990 檔）→ data/daily.csv.gz；成交金額前 300 檔的 60 分 K → data/h60.csv.gz"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def chart(tk, interval, rng):
    for k in range(3):
        for host in ("query1", "query2"):
            try:
                r = httpx.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{tk}", params={"interval": interval, "range": rng},
                              headers=UA, timeout=40)
                if r.status_code == 429:
                    time.sleep(5 + 5 * k)
                    continue
                res = (r.json().get("chart") or {}).get("result")
                if not res:
                    return None
                res = res[0]
                q = res["indicators"]["quote"][0]
                off = int(res["meta"].get("gmtoffset") or 28800)
                df = pd.DataFrame({"ts": res.get("timestamp") or [], "o": q.get("open"), "h": q.get("high"), "l": q.get("low"),
                                   "c": q.get("close"), "v": q.get("volume")}).dropna(subset=["o", "h", "l", "c"])
                df["t"] = pd.to_datetime(df.ts + off, unit="s").dt.strftime("%Y-%m-%d" if interval == "1d" else "%Y-%m-%d %H:%M")
                df["tk"] = tk
                return df.drop(columns="ts").drop_duplicates("t", keep="last")
            except Exception as e:      # noqa: BLE001
                print(tk, interval, host, repr(e)[:100], flush=True)
        time.sleep(2)
    return None


def grab(tks, interval, rng, workers=6):
    out = []
    with ThreadPoolExecutor(workers) as ex:
        for i, df in enumerate(ex.map(lambda t: chart(t, interval, rng), tks)):
            if df is not None and len(df):
                out.append(df)
            if i % 100 == 0:
                print(interval, i, len(out), flush=True)
    return pd.concat(out, ignore_index=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    u = json.load(open(os.path.join(HERE, "universe.json")))
    d = grab(u["all"], "1d", "5y")
    d.to_csv(os.path.join(OUT, "daily.csv.gz"), index=False)
    print("daily", d.tk.nunique(), len(d), flush=True)
    last = d[d.t >= sorted(d.t.unique())[-60]]
    liq = (last.c * last.v).groupby(last.tk).mean().sort_values(ascending=False)
    top = list(liq.index[:300])
    h = grab(top, "60m", "730d", workers=4)
    h.to_csv(os.path.join(OUT, "h60.csv.gz"), index=False)
    print("60m", h.tk.nunique(), len(h), flush=True)
