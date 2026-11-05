"""B96 15 分 K 成交量（GitHub Actions 抓；雲端 session 連不到證交所）：
證交所 MI_5MINS（每 5 秒累計成交金額，百萬元）每天一次 → 每 5 分鐘的成交金額（9:00～13:30，一天 54 格；13:30 收盤撮合併進 13:25 那格）
→ data/twii_5m_amt.csv（date, slot, amt）。15 分 K 的量＝三格相加（跟 research/b80 一樣的切法）"""
import csv
import datetime as dt
import os
import time

import httpx

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.twse.com.tw/"}
START, END = dt.date(2023, 10, 2), dt.date.today()
T0, T1 = 9 * 3600, 13 * 3600 + 30 * 60


def day_rows(d: dt.date):
    for k in range(5):
        try:
            j = httpx.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS",
                          params={"date": d.strftime("%Y%m%d"), "response": "json"}, headers=H, timeout=40).json()
        except Exception as e:      # noqa: BLE001
            print(d, "err", repr(e)[:120], flush=True)
            time.sleep(30 * (k + 1))
            continue
        if j.get("stat") != "OK":
            return []                                     # 休市
        out = []
        for r in j.get("data") or []:
            try:
                hh, mm, ss = (int(x) for x in str(r[0]).split(":"))
                out.append((hh * 3600 + mm * 60 + ss, float(str(r[7]).replace(",", ""))))
            except (ValueError, IndexError):
                continue
        return out
    return None


def slots(rows):
    """累計 → 每 5 分鐘一格的金額；格 i＝[9:00＋5i, 9:00＋5(i+1))，最後一格含 13:30:00"""
    rows = sorted(rows)
    n = (T1 - T0) // 300

    def cum_at(T, incl):
        v = 0.0
        for s, x in rows:
            if s < T or (incl and s == T):
                v = x
            else:
                break
        return v
    res = []
    for i in range(n):
        a, b = T0 + i * 300, T0 + (i + 1) * 300
        last = i == n - 1
        amt = cum_at(b, last) - (0.0 if i == 0 else cum_at(a, False))
        res.append((f"{a // 3600:02d}:{a % 3600 // 60:02d}", round(max(amt, 0.0), 2)))
    return res


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "twii_5m_amt.csv")
    out, ok, off = [], 0, 0
    d = START
    while d <= END:
        if d.weekday() < 5:
            rows = day_rows(d)
            if rows:
                out += [(d.isoformat(), s, a) for s, a in slots(rows)]
                ok += 1
            elif rows == []:
                off += 1
            else:
                print(d, "give up", flush=True)
            if ok and ok % 50 == 0 and rows:
                print(d, "days", ok, flush=True)
            time.sleep(3.2)
        d += dt.timedelta(days=1)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "slot", "amt"])
        w.writerows(out)
    print("done days", ok, "holidays", off, "rows", len(out), flush=True)
