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

from .parser import CAPITAL_TYPES, capital_info, classify, extract, parse_announcements, parse_detail, short_company
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
    """內文；MOPS 太頻繁會回空或錯誤 → 退避重試兩次"""
    for wait in (0, 3, 8):
        if wait:
            time.sleep(wait)
        try:
            r = client.post(f"{API}/t05st02_detail", json=params, headers=_API_HDR)
            j = r.json()
            if j.get("code") == 200:
                txt = re.sub(r"\s+", " ", " ".join(_texts(j.get("result"))))
                if len(txt) > 50:
                    return txt[:6000]
        except Exception:
            pass
    return ""


_names = None


def resolve_stock(company: str):
    """公司全名 → (代號, 簡稱)：取股票簡稱是公司名開頭的、最長的那個（精誠資訊 → 6214 精誠）"""
    global _names
    if not company:
        return None, None
    if _names is None:
        try:
            from yahoo_price import get_stock_list
            df = get_stock_list()
            _names = list(zip(df["stock_id"], df["stock_name"]))
        except Exception:
            _names = []
    sc = short_company(company)
    best = None
    for sid, nm in _names:
        nm = str(nm)
        if len(nm) >= 2 and sc.startswith(nm) and (best is None or len(nm) > len(best[1])):
            best = (sid, nm)
    return best if best else (None, None)


def build_record(ddate: str, sid: str, name: str, subject: str, kind: str, detail: str) -> dict:
    rec = {"target_id": sid, "target_name": name, "announcer_id": sid, "announce_date": roc_to_iso(ddate),
           "subject": re.sub(r"\s+", " ", subject)[:500], "deal_type": kind, "source": "MOPS 重大訊息"}
    if kind in CAPITAL_TYPES:                    # 減資／增資：不套收購欄位解析
        if detail:
            rec["notes"] = detail[:1500]
        rec.update(capital_info(subject, detail))
        return rec
    info = extract(subject)
    if detail:
        d = parse_detail(detail, subject)
        info = {**info, **{k: v for k, v in d.items() if v not in (None, "")}}
        rec["notes"] = detail[:1500]
    if info.get("deal_kind") and kind in ("合併", "收購股權"):
        k = info["deal_kind"]
        rec["deal_type"] = "股份轉換" if "轉換" in k else "合併" if "合併" in k else "收購股權" if "收購" in k or "受讓" in k else kind
    tc = info.get("target_company")
    if tc:
        tid, tname = resolve_stock(tc)
        if tid:
            rec["target_id"], rec["target_name"] = tid, tname       # 被收購的是上市櫃公司 → 以它為標的
        elif tid is None and info.get("acquirer") is None:
            info["acquirer"] = name                                  # 標的未上市：公告公司是收購方
    if info.get("stock_company"):
        sref, _ = resolve_stock(info["stock_company"])
        if sref:
            info["stock_ref"] = sref
    for k in ("offer_price", "min_shares", "max_shares", "offer_pct", "period_start", "period_end", "scope",
              "consideration", "acquirer", "target_company", "deal_kind", "stock_company", "stock_ref", "stock_ratio"):
        if info.get(k) not in (None, ""):
            rec[k] = info[k]
    if rec.get("acquirer"):
        rec["acquirer"] = re.sub(r"^(接獲|本公司|代子公司)", "", rec["acquirer"]).strip()
    return rec


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
            time.sleep(1.5)
        if detail and kind != "公開收購" and re.search(r"簡易合併|持股\s*100\s*%\s*之子公司.*?無涉換股", detail[:3000]):
            continue                                  # 跟百分之百子公司合併：跟股東無關
        rec = build_record(ddate, sid.strip(), name.strip(), subject, kind, detail)
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
