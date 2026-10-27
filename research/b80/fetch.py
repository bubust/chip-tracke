"""B80 研究資料（PLAN-B80 §7）：只抓公開資料存到 research/b80/data（不進 git），可以中斷後接著抓
1. 證交所 FMTQIK 每日市場成交資訊 2000 起（成交金額）→ data/turnover.csv
2. Yahoo ^TWII 60 分 K 730 天、5 分 K 60 天 → data/twii_60m.csv、data/twii_5m.csv
3. 證交所 MI_5MINS 每 5 秒累計成交（60 分 K 期間每個交易日）→ data/mi5/YYYYMMDD.csv（時間, 累計成交金額 百萬元）
證交所請求間隔 3.2 秒（太快會被暫時封鎖）"""
import csv
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MI5 = os.path.join(DATA, "mi5")
TW = timezone(timedelta(hours=8))
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.twse.com.tw/"}
GAP = 3.2


def twse(url, params, tries=3):
    for k in range(tries):
        try:
            r = httpx.get(url, params=params, headers=H, timeout=30, verify=False)
            j = r.json()
            return j
        except Exception as e:     # noqa: BLE001
            print("  retry", k, url, params, repr(e)[:120], flush=True)
            time.sleep(30)
    return None


def fetch_turnover():
    path = os.path.join(DATA, "turnover.csv")
    have = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                have[row["date"]] = row
    today = datetime.now(TW).date()
    y, m = 2000, 1
    months_have = {d[:7] for d in have}
    while (y, m) <= (today.year, today.month):
        ym = f"{y:04d}-{m:02d}"
        cur = (y, m) == (today.year, today.month) or (y, m) == ((today - timedelta(days=31)).year, (today - timedelta(days=31)).month)
        if ym not in months_have or cur:
            j = twse("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK", {"date": f"{y:04d}{m:02d}01", "response": "json"})
            for row in (j or {}).get("data") or []:
                try:
                    ry, rm, rd = str(row[0]).strip().split("/")
                    d = f"{int(ry) + 1911:04d}-{int(rm):02d}-{int(rd):02d}"
                    have[d] = {"date": d, "shares": float(row[1].replace(",", "")), "amt": float(row[2].replace(",", ""))}
                except Exception:     # noqa: BLE001
                    continue
            print("FMTQIK", ym, len((j or {}).get("data") or []), flush=True)
            time.sleep(GAP)
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "shares", "amt"])
        w.writeheader()
        for d in sorted(have):
            w.writerow({k: have[d][k] for k in ("date", "shares", "amt")})
    print("turnover rows", len(have), flush=True)


def fetch_yahoo(interval, rng, name):
    j = httpx.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII", params={"interval": interval, "range": rng},
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=60, follow_redirects=True).json()
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = [(int(ts), q["open"][i], q["high"][i], q["low"][i], q["close"][i]) for i, ts in enumerate(r.get("timestamp") or [])
            if q["close"][i] is not None]
    with open(os.path.join(DATA, name), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "o", "h", "l", "c"])
        w.writerows(rows)
    print("yahoo", interval, len(rows), datetime.fromtimestamp(rows[0][0], TW), "→", datetime.fromtimestamp(rows[-1][0], TW), flush=True)
    return rows


def fetch_mi5(days):
    os.makedirs(MI5, exist_ok=True)
    for d in days:
        path = os.path.join(MI5, d.strftime("%Y%m%d") + ".csv")
        if os.path.exists(path):
            continue
        j = twse("https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS", {"date": d.strftime("%Y%m%d"), "response": "json"})
        rows = (j or {}).get("data") or []
        if (j or {}).get("stat") == "OK" and rows:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["time", "cum_amt", "cum_vol"])
                for r in rows:
                    w.writerow([r[0], r[7].replace(",", ""), r[6].replace(",", "")])
        print("MI5", d, len(rows), flush=True)
        time.sleep(GAP)


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    what = sys.argv[1:] or ["yahoo", "turnover", "mi5"]
    r60 = None
    if "yahoo" in what or "mi5" in what:
        r60 = fetch_yahoo("60m", "730d", "twii_60m.csv")
        fetch_yahoo("5m", "60d", "twii_5m.csv")
    if "turnover" in what:
        fetch_turnover()
    if "mi5" in what:
        days = sorted({datetime.fromtimestamp(x[0], TW).date() for x in r60})
        print("MI5 days", len(days), days[0], days[-1], flush=True)
        fetch_mi5(days)
    print("DONE", flush=True)
