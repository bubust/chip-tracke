"""
從 MOPS 抓「庫藏股買回資訊彙總」（t35sc09），依董事會決議日期區間查詢，上市（sii）＋上櫃（otc）。

MOPS 會擋太頻繁的查詢，所以每次請求間隔 3 秒、遇到「查詢過於頻繁」等 10 秒重試一次。
新舊兩個 MOPS 網域依序嘗試；抓不到時把回應開頭存進狀態，方便判斷是被擋還是格式變了。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

import httpx

from .parser import parse_html

log = logging.getLogger(__name__)

MOPS_URLS = [
    "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09",
    "https://mops.twse.com.tw/mops/web/ajax_t35sc09",
]
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_THROTTLE = ("查詢過於頻繁", "Overrun", "請稍後再查詢", "THE PAGE CANNOT BE ACCESSED")
_NO_DATA = ("查無資料", "查無所需資料", "無符合")
MARKETS = {"sii": "上市", "otc": "上櫃"}


def _roc(d: date) -> str:
    return f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"


def fetch_window(market: str, start: date, end: date, client: httpx.Client = None) -> tuple:
    """回傳 (records, error_or_None, raw_snippet)。查無資料回 ([], None, '')。"""
    form = {
        "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
        "TYPEK": market, "d1": _roc(start), "d2": _roc(end), "RD": "1",
    }
    own = client is None
    client = client or httpx.Client(timeout=30.0, verify=False, follow_redirects=True,
                                    headers={"User-Agent": _UA})
    last_err, snippet = None, ""
    try:
        for url in MOPS_URLS:
            for attempt in range(2):
                try:
                    r = client.post(url, data=form, headers={
                        "Referer": url.replace("ajax_t35sc09", "t35sc09"),
                        "Content-Type": "application/x-www-form-urlencoded"})
                    text = r.text
                    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:300]
                    if r.status_code != 200:
                        last_err = f"HTTP {r.status_code}"
                        break
                    if any(k in text for k in _THROTTLE):
                        last_err = "MOPS 回覆查詢過於頻繁"
                        time.sleep(10)
                        continue
                    recs = parse_html(text)
                    if recs:
                        for x in recs:
                            x["market"] = market
                        return recs, None, ""
                    if any(k in text for k in _NO_DATA):
                        return [], None, ""
                    last_err = "回應中找不到庫藏股表格（格式可能改了）"
                    break
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                    break
        return [], last_err, snippet
    finally:
        if own:
            client.close()


def fetch_range(start: date, end: date, window_days: int = 90, pause: float = 3.0,
                progress=None) -> dict:
    """分段抓 start~end（含），回傳 {'records': [...], 'errors': [...], 'snippet': str}"""
    out, errors, snippet = [], [], ""
    windows = []
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=window_days - 1))
        windows.append((s, e))
        s = e + timedelta(days=1)
    total = len(windows) * len(MARKETS)
    done = 0
    consecutive_fail = 0
    with httpx.Client(timeout=30.0, verify=False, follow_redirects=True,
                      headers={"User-Agent": _UA}) as client:
        for mkt in MARKETS:
            for ws, we in windows:
                recs, err, snip = fetch_window(mkt, ws, we, client)
                out.extend(recs)
                if err:
                    errors.append(f"{MARKETS[mkt]} {ws}~{we}：{err}")
                    snippet = snippet or snip
                    consecutive_fail += 1
                    # 一開始就連續 3 段失敗（通常是被擋或連不上）→ 不再浪費時間跑完全部
                    if consecutive_fail >= 3 and not out:
                        errors.append(f"連續 {consecutive_fail} 段失敗，先停止（共 {total} 段）")
                        if progress:
                            progress(total, total)
                        return {"records": out, "errors": errors, "snippet": snippet}
                else:
                    consecutive_fail = 0
                done += 1
                if progress:
                    progress(done, total)
                time.sleep(pause)
    return {"records": out, "errors": errors, "snippet": snippet}
