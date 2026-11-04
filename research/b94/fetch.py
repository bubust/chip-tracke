"""B94 回測資料（在 GitHub Actions 抓，雲端 session 連不到 Yahoo／FinMind）：
- 加權日 K 2000 起（Yahoo ^TWII）→ data/twii_d.csv
- 加權 60 分 K 近 730 天（Yahoo）→ data/twii_60m.csv
- 台指期日 K 2017 起（FinMind TaiwanFuturesDaily TX；日盤＋夜盤，網站同一套 select_continuous → full_bars）→ data/tx_d.csv"""
import os
import sys
import time

import httpx
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from wave import futdata as FD  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def yahoo(interval: str, **params) -> pd.DataFrame:
    for host in ("query1", "query2"):
        try:
            r = httpx.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/%5ETWII",
                          params={"interval": interval, **params}, headers=UA, timeout=60)
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            off = int(res["meta"].get("gmtoffset") or 0)
            df = pd.DataFrame({"ts": res["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"], "v": q["volume"]})
            df = df.dropna(subset=["o", "h", "l", "c"])
            df["date"] = pd.to_datetime(df.ts + off, unit="s").dt.strftime("%Y-%m-%d %H:%M" if interval != "1d" else "%Y-%m-%d")
            return df.drop_duplicates("date", keep="last").reset_index(drop=True)
        except Exception as e:      # noqa: BLE001
            print(interval, host, repr(e)[:160])
    raise RuntimeError(interval)


def finmind_tx() -> pd.DataFrame:
    frames = []
    for y in range(2017, 2027):                      # 一年一段（一次抓太大會逾時）
        p = {"dataset": "TaiwanFuturesDaily", "data_id": "TX", "start_date": f"{y}-01-01", "end_date": f"{y}-12-31",
             "token": os.environ.get("FINMIND_TOKEN", "")}
        for k in range(3):
            try:
                j = httpx.get("https://api.finmindtrade.com/api/v4/data", params=p, timeout=180).json()
                if j.get("status") == 200:
                    frames.append(pd.DataFrame(j["data"]))
                    break
                print("finmind", y, j.get("msg"))
            except Exception as e:      # noqa: BLE001
                print("finmind", y, repr(e)[:120])
            time.sleep(5)
        time.sleep(2)
    raw = pd.concat(frames, ignore_index=True)
    fb = FD.full_bars(FD.select_continuous(raw))
    return fb[["date", "o", "h", "l", "c", "v", "contract"]]


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    d = yahoo("1d", period1=946684800, period2=int(time.time()))
    d[["date", "o", "h", "l", "c", "v"]].to_csv(os.path.join(OUT, "twii_d.csv"), index=False)
    print("twii_d", len(d), d.date.iloc[0], d.date.iloc[-1])
    m = yahoo("60m", range="730d")
    m[["date", "o", "h", "l", "c", "v"]].to_csv(os.path.join(OUT, "twii_60m.csv"), index=False)
    print("twii_60m", len(m), m.date.iloc[0], m.date.iloc[-1])
    try:
        tx = finmind_tx()
        tx.to_csv(os.path.join(OUT, "tx_d.csv"), index=False)
        print("tx_d", len(tx), tx.date.iloc[0], tx.date.iloc[-1])
    except Exception as e:      # noqa: BLE001
        print("tx_d 失敗", repr(e)[:200])
