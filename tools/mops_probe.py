"""臨時診斷：印出幾則收購併購公告的完整內文，用來對欄位名稱"""
import sys, time, httpx
sys.path.insert(0, ".")
from mna.fetcher import API, _API_HDR, _UA, fetch_detail
want = ("公開收購", "股份轉換", "合併", "收購")
c = httpx.Client(timeout=30, verify=False, headers={"User-Agent": _UA})
seen = 0
for day in ("29", "30", "23", "22"):
    j = c.post(f"{API}/t05st02", json={"year": "115", "month": "09", "day": day}, headers=_API_HDR).json()
    for row in (j.get("result") or {}).get("data") or []:
        subj = str(row[4])
        if any(w in subj for w in want) and "營" not in subj and "財務" not in subj and isinstance(row[5], dict):
            print("=" * 100); print(row[:5])
            print(fetch_detail(row[5]["parameters"], c)[:3500])
            seen += 1; time.sleep(1.2)
        if seen >= 7:
            break
    if seen >= 7:
        break
