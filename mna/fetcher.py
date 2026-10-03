"""
抓 MOPS 重大訊息（依日期），挑出收購併購。

2026-10 實測（GitHub Actions）：
- 新版 MOPS JSON API：POST https://mops.twse.com.tw/mops/api/t05st02 {"year":"115","month":"10","day":"02"}
  → result.data = [[日期, 時間, 代號, 名稱, 主旨, {"parameters": {...}, "apiName": "t05st02_detail"}], ...]  ✅
- 舊版頁面 mops.twse.com.tw/mops/web/ajax_* 一律被防火牆擋（「因為安全性考量…」）
- mopsov.twse.com.tw/mops/web/ajax_t05st02 要多帶 step00=0 才有資料（當日全部公告內文），當備援
收購類主旨再呼叫 t05st02_detail 取內文，從內文抓收購價、數量、期間。
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

import httpx

from .parser import classify, extract, parse_announcements
from treasury.parser import roc_to_iso

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
API = "https://mops.twse.com.tw/mops/api"
_API_HDR = {"Content-Type": "application/json", "Referer": "https://mops.twse.com.tw/mops/",
            "Origin": "https://mops.twse.com.tw", "Accept": "application/json, text/plain, */*"}


def _texts(obj, out=None) -> list:
    """把 JSON 裡所有字串攤平（內文格式不固定，全部拿來比對）"""
    out = [] if out is None else out
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _texts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _texts(v, out)
    return out


def fetch_detail(params: dict, client: httpx.Client) -> str:
    try:
        r = client.post(f"{API}/t05st02_detail", json=params, headers=_API_HDR)
        j = r.json()
        if j.get("code") == 200:
            return re.sub(r"\s+", " ", " ".join(_texts(j.get("result"))))[:6000]
    except Exception:
        pass
    return ""


def _from_api(d: date, client: httpx.Client) -> tuple:
    """回傳 (records, ok, snippet)"""
    try:
        r = client.post(f"{API}/t05st02", headers=_API_HDR,
                        json={"year": str(d.year - 1911), "month": f"{d.month:02d}", "day": f"{d.day:02d}"})
        j = r.json()
    except Exception as e:
        return [], False, f"{type(e).__name__}: {e}"[:300]
    if j.get("code") != 200:
        msg = str(j.get("message") or "")
        return [], ("查無" in msg), msg[:300]          # 查無資料（假日）也算成功
    rows = ((j.get("result") or {}).get("data")) or []
    out = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        ddate, _t, sid, name, subject = (str(x) for x in row[:5])
        kind = classify(subject)
        if not kind or not re.fullmatch(r"[0-9A-Z]{4,6}", sid.strip()):
            continue
        detail = ""
        if len(row) > 5 and isinstance(row[5], dict) and isinstance(row[5].get("parameters"), dict):
            detail = fetch_detail(row[5]["parameters"], client)
            time.sleep(1.0)
        rec = {"target_id": sid.strip(), "target_name": name.strip(), "announce_date": roc_to_iso(ddate),
               "subject": subject[:500], "deal_type": kind, "source": "MOPS 重大訊息"}
        info = extract(subject)
        if detail:
            info = {**extract(detail), **{k: v for k, v in info.items() if v not in (None, "")}}
            rec["notes"] = detail[:1500]
        rec.update(info)
        out.append(rec)
    return out, True, ""


def _from_mopsov(d: date, client: httpx.Client) -> tuple:
    url = "https://mopsov.twse.com.tw/mops/web/ajax_t05st02"
    form = {"encodeURIComponent": "1", "step": "1", "step00": "0", "firstin": "1", "off": "1", "TYPEK": "all",
            "year": str(d.year - 1911), "month": f"{d.month:02d}", "day": f"{d.day:02d}"}
    try:
        r = client.post(url, data=form, headers={"Referer": url.replace("ajax_", "")})
        if r.status_code == 200 and ("主旨" in r.text or "查無" in r.text):
            return parse_announcements(r.text), True, ""
        return [], False, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:300]
    except Exception as e:
        return [], False, f"{type(e).__name__}: {e}"[:300]


def fetch_day(d: date, client: httpx.Client) -> tuple:
    recs, ok, snip = _from_api(d, client)
    if ok:
        return recs, True, ""
    recs2, ok2, snip2 = _from_mopsov(d, client)
    return recs2, ok2, snip2 or snip


def fetch_range(days: int = 14, pause: float = 2.0, progress=None) -> dict:
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
                errors.append(f"{day}：{snip[:80] or '抓不到重大訊息'}")
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
