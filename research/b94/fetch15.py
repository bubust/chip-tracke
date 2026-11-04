"""B94e 15 分 K 資料（GitHub Actions 抓；雲端 session 連不到證交所）：
證交所「每 5 秒指數盤後統計」MI_5MINS_INDEX 每天一次 → 加權指數 15 分 K（9:00～13:30，一天 18 根；13:30 收盤併進 13:15 那根）
→ data/twii_15m.csv；同一份資料再組 60 分 K → data/twii_60m_twse.csv（拿來核對 Yahoo 的 60 分 K）"""
import datetime as dt
import os
import time

import httpx
import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
URLS = ("https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX?date={d}&response=json",
        "https://www.twse.com.tw/exchangeReport/MI_5MINS_INDEX?response=json&date={d}")
START, END = dt.date(2023, 10, 2), dt.date.today()


def fetch_day(d: dt.date):
    """回 [(秒數, 指數)]；休市回 []；一直失敗丟例外"""
    ds = d.strftime("%Y%m%d")
    for attempt in range(5):
        for u in URLS:
            try:
                j = httpx.get(u.format(d=ds), headers=UA, timeout=40).json()
            except Exception as e:      # noqa: BLE001  （被擋時會回 HTML）
                print(ds, "err", repr(e)[:120], flush=True)
                continue
            stat = str(j.get("stat", ""))
            if stat != "OK":
                if "沒有" in stat or "查詢日期" in stat:
                    return []
                print(ds, "stat", stat[:80], flush=True)
                continue
            fields = j.get("fields") or []
            k = next((i for i, f in enumerate(fields) if "發行量加權股價指數" in f), None)
            if k is None:
                print(ds, "fields", fields[:4], flush=True)
                continue
            rows = []
            for x in j.get("data") or []:
                try:
                    hh, mm, ss = (int(v) for v in str(x[0]).split(":"))
                    rows.append((hh * 3600 + mm * 60 + ss, float(str(x[k]).replace(",", ""))))
                except (ValueError, IndexError):
                    continue
            return rows
        time.sleep(30 * (attempt + 1))
    raise RuntimeError(ds)


def bars(d: dt.date, rows, minutes: int):
    t0, t1 = 9 * 3600, 13 * 3600 + 30 * 60
    nb = (t1 - t0) // (minutes * 60)                                   # 15 分 18 根、60 分 4.5 → 5 根
    nb = nb if (t1 - t0) % (minutes * 60) == 0 else nb + 1
    out = {}
    for s, v in rows:
        if s < t0 or s > t1:
            continue
        b = min((s - t0) // (minutes * 60), nb - 1)                     # 13:30:00 收盤併進最後一根
        if b not in out:
            out[b] = [v, v, v, v]
        else:
            o = out[b]
            o[1], o[2], o[3] = max(o[1], v), min(o[2], v), v
    res = []
    for b in sorted(out):
        m = t0 + b * minutes * 60
        res.append({"date": f"{d:%Y-%m-%d} {m // 3600:02d}:{m % 3600 // 60:02d}", "o": out[b][0], "h": out[b][1], "l": out[b][2], "c": out[b][3]})
    return res


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    r15, r60, n_ok, n_off = [], [], 0, 0
    d = START
    while d <= END:
        if d.weekday() < 5:
            try:
                rows = fetch_day(d)
            except RuntimeError:
                print(d, "give up", flush=True)
                rows = None
            if rows:
                r15 += bars(d, rows, 15)
                r60 += bars(d, rows, 60)
                n_ok += 1
            elif rows == []:
                n_off += 1
            if n_ok and n_ok % 50 == 0 and rows:
                print(d, "days", n_ok, "bars", len(r15), flush=True)
                pd.DataFrame(r15).to_csv(os.path.join(OUT, "twii_15m.csv"), index=False)
            time.sleep(2.2)
        d += dt.timedelta(days=1)
    pd.DataFrame(r15).to_csv(os.path.join(OUT, "twii_15m.csv"), index=False)
    pd.DataFrame(r60).to_csv(os.path.join(OUT, "twii_60m_twse.csv"), index=False)
    print("done days", n_ok, "holidays", n_off, "15m bars", len(r15), flush=True)
