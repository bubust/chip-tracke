"""B74 研究資料：Yahoo 日 K（2000 起）＋ FinMind 大盤籌碼（2016 起）→ research/wave/data/*.csv
用法：.venv/Scripts/python research/wave/fetch.py（FINMIND_TOKEN 從環境變數讀）"""
import os, sys, time, json
import httpx
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SYMS = {"TWII": "^TWII", "SOX": "^SOX", "IXIC": "^IXIC", "GSPC": "^GSPC", "N225": "^N225", "KS11": "^KS11", "TWD": "TWD=X"}


def yahoo(sym: str) -> pd.DataFrame:
    p = {"interval": "1d", "period1": 946684800, "period2": int(time.time())}
    for host in ("query1", "query2"):
        try:
            r = httpx.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", params=p, headers=UA, timeout=40)
            res = r.json()["chart"]["result"][0]
            off = int(res["meta"].get("gmtoffset") or 0)
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame({"date": pd.to_datetime([t + off for t in res["timestamp"]], unit="s").strftime("%Y-%m-%d"),
                               "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"], "v": q["volume"]})
            return df.dropna(subset=["c"]).drop_duplicates("date", keep="last")
        except Exception as e:      # noqa: BLE001
            print(sym, host, repr(e)[:120])
    raise RuntimeError(sym)


def finmind(ds: str, start: str, **kw) -> pd.DataFrame:
    tok = os.environ.get("FINMIND_TOKEN", "")
    r = httpx.get("https://api.finmindtrade.com/api/v4/data",
                  params={"dataset": ds, "start_date": start, "token": tok, **kw}, timeout=90)
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"{ds}: {j.get('msg')}")
    return pd.DataFrame(j["data"])


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for k, s in SYMS.items():
        df = yahoo(s)
        df.to_csv(f"{OUT}/{k}.csv", index=False)
        print(k, len(df), df.date.iloc[0], df.date.iloc[-1])
        time.sleep(1)
    if os.environ.get("FINMIND_TOKEN"):
        for name, ds, st, kw in [("inst", "TaiwanStockTotalInstitutionalInvestors", "2016-01-01", {}),
                                 ("fut", "TaiwanFuturesInstitutionalInvestors", "2018-01-01", {"data_id": "TX"}),
                                 ("margin", "TaiwanStockTotalMarginPurchaseShortSale", "2016-01-01", {}),
                                 ("opt", "TaiwanOptionInstitutionalInvestors", "2018-01-01", {"data_id": "TXO"})]:
            df = finmind(ds, st, **kw)
            df.to_csv(f"{OUT}/fm_{name}.csv", index=False, encoding="utf-8")
            print(name, len(df), df.date.min(), df.date.max())
            time.sleep(2)
