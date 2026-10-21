"""B75 研究資料（PLAN-B75 §2.3、§4.2、§6.1）→ research/futures/data/
- FinMind：TX／MTX 日 K（日盤＋夜盤，2017 起）、小台三大法人（FINMIND_TOKEN 從環境變數讀）
- Yahoo：^TWII 60 分 K 2 年（twii_60m.csv）、5 分 K 60 天（twii_5m.csv）
- 期交所：近 30 個交易日逐筆檔 → 台指期 5 分 K（tx_5m.csv，用網站同一支 wave.futdata.fetch_taifex_day）
其他（加權日 K、費半、外資現貨、台指期法人、融資、選擇權法人）沿用 research/wave/data
用法：.venv/Scripts/python research/futures/fetch.py [--skip-finmind] [--skip-taifex]"""
import os
import sys
import time
from datetime import date

import httpx
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from wave import futdata as FD  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def finmind(ds, start, **kw):
    r = httpx.get("https://api.finmindtrade.com/api/v4/data",
                  params={"dataset": ds, "start_date": start, "token": os.environ.get("FINMIND_TOKEN", ""), **kw}, timeout=180)
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"{ds}: {j.get('msg')}")
    return pd.DataFrame(j["data"])


def yahoo_intraday(interval, rng):
    j = httpx.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII", params={"interval": interval, "range": rng},
                  headers=UA, timeout=60).json()
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return pd.DataFrame({"ts": r["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"], "v": q["volume"]}).dropna(subset=["c"])


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if "--skip-finmind" not in sys.argv:
        for name, ds, did in (("fut_tx_daily", "TaiwanFuturesDaily", "TX"), ("fut_mtx_daily", "TaiwanFuturesDaily", "MTX"),
                              ("fm_fut_mtx", "TaiwanFuturesInstitutionalInvestors", "MTX")):
            df = finmind(ds, "2017-01-01", data_id=did)
            df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False, encoding="utf-8")
            print(name, len(df), df.date.min(), df.date.max())
            time.sleep(2)
    for iv, rng, nm in (("60m", "730d", "twii_60m"), ("5m", "60d", "twii_5m")):
        df = yahoo_intraday(iv, rng)
        df.to_csv(os.path.join(OUT, f"{nm}.csv"), index=False)
        print(nm, len(df))
        time.sleep(1)
    if "--skip-taifex" not in sys.argv:
        fd = FD.select_continuous(pd.read_csv(os.path.join(OUT, "fut_tx_daily.csv"), dtype={"contract_date": str}))
        days = sorted(set(fd[fd.sess == "day"].date))[-30:]
        rows = []
        for d in days:
            try:
                t0 = time.time()
                r = FD.fetch_taifex_day(date.fromisoformat(d))
                rows += r
                print(d, len(r), f"{time.time() - t0:.1f}s")
            except Exception as e:      # noqa: BLE001
                print(d, "失敗", e)
            time.sleep(2)
        pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).drop_duplicates("ts").sort_values("ts").to_csv(
            os.path.join(OUT, "tx_5m.csv"), index=False)
        print("tx_5m", len(rows))
