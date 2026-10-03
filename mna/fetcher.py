"""
抓 MOPS 重大訊息（依日期），挑出收購併購。新舊 MOPS 網域、歷史查詢（t05st02）與當日列表（t05sr01_1）依序嘗試；
連續 3 天都抓不到就停，把回應開頭存進狀態，方便判斷是被擋還是格式改了。
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

import httpx

from .parser import parse_announcements

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_HOSTS = ["https://mopsov.twse.com.tw", "https://mops.twse.com.tw"]
_THROTTLE = ("查詢過於頻繁", "Overrun", "請稍後再查詢")


def fetch_day(d: date, client: httpx.Client) -> tuple:
    """回傳 (records, ok, snippet)。ok=True 代表有拿到重大訊息表格（即使沒有收購類）"""
    form = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "all",
            "year": str(d.year - 1911), "month": f"{d.month:02d}", "day": f"{d.day:02d}"}
    snippet = ""
    targets = [("ajax_t05st02", form)]
    if d == date.today():
        targets.append(("ajax_t05sr01_1", {"encodeURIComponent": "1", "step": "0", "firstin": "1", "off": "1", "TYPEK": "all"}))
    for host in _HOSTS:
        for path, data in targets:
            url = f"{host}/mops/web/{path}"
            for attempt in range(2):
                try:
                    r = client.post(url, data=data, headers={"Referer": url.replace("ajax_", "")})
                    text = r.text
                    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:300]
                    if any(k in text for k in _THROTTLE):
                        time.sleep(8)
                        continue
                    if r.status_code == 200 and "主旨" in text:
                        return parse_announcements(text), True, ""
                    break
                except Exception as e:
                    snippet = f"{type(e).__name__}: {e}"[:300]
                    break
    return [], False, snippet


def fetch_range(days: int = 14, pause: float = 2.5, progress=None) -> dict:
    out, errors, snippet = [], [], ""
    d = date.today()
    targets = []
    while len(targets) < days:
        if d.weekday() < 5:
            targets.append(d)
        d -= timedelta(days=1)
    fails = 0
    with httpx.Client(timeout=30.0, verify=False, follow_redirects=True, headers={"User-Agent": _UA}) as c:
        for k, day in enumerate(targets, 1):
            recs, ok, snip = fetch_day(day, c)
            out.extend(recs)
            if ok:
                fails = 0
            else:
                fails += 1
                errors.append(f"{day}：抓不到重大訊息表格")
                snippet = snippet or snip
                if fails >= 3 and not out:
                    errors.append("連續 3 天失敗，先停止")
                    if progress:
                        progress(len(targets), len(targets))
                    break
            if progress:
                progress(k, len(targets))
            time.sleep(pause)
    return {"records": out, "errors": errors, "snippet": snippet}
