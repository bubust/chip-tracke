"""
可轉債資料來源（2026-10 用 GitHub Actions 實測可用）：
- 發行資料：櫃買 OpenAPI bond_ISSBD5_data（代號、發行公司、發行/到期日、發行額、流通在外餘額、發行時轉換價、賣回日）
- 每日行情：櫃買 storage/bond_zone/tradeinfo/cb/{yyyy}/{yyyymm}/RSta0113.{yyyymmdd}-C.csv（收市、成交張數、均價、明日參價）
- 轉換價格調整：MOPS 重大訊息 JSON API（t05st02 + t05st02_detail）主旨含「轉換價格」者
- 融券餘額：TWSE rwd MI_MARGN（selectType=ALL，可指定日期）、櫃買 /www/zh-tw/margin/balance（可指定日期）
- 月營收：TWSE OpenAPI t187ap05_L、櫃買 OpenAPI mopsfin_t187ap05_O
股價用系統既有的 price_daily 快取（chip_data/cache.db）。
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

import httpx

from .parser import (parse_bonds, parse_conv_adjust, parse_openapi_margin, parse_quotes_csv, parse_revenue,
                     parse_tpex_margin, parse_twse_margin)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def client() -> httpx.Client:
    return httpx.Client(timeout=40.0, verify=False, follow_redirects=True,
                        headers={"User-Agent": _UA, "Accept": "application/json,text/csv,*/*"})


def fetch_bonds(c: httpx.Client) -> list:
    r = c.get("https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data")
    r.raise_for_status()
    return parse_bonds(r.json())


def fetch_quotes(c: httpx.Client, d: date) -> list:
    """回傳該日行情列；非交易日／還沒出檔回 []"""
    url = f"https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/{d:%Y}/{d:%Y%m}/RSta0113.{d:%Y%m%d}-C.csv"
    r = c.get(url)
    if r.status_code != 200 or len(r.content) < 200:
        return []
    text = r.content.decode("cp950", "replace")
    dt, rows = parse_quotes_csv(text)
    if dt and dt != d.isoformat():
        return []
    return rows


def fetch_short_day(c: httpx.Client, d: date) -> dict:
    """{sid: 融券餘額（張）}：上市＋上櫃"""
    out = {}
    try:
        r = c.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                  params={"date": d.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"})
        out.update(parse_twse_margin(r.json()))
    except Exception:
        pass
    try:
        r = c.post("https://www.tpex.org.tw/www/zh-tw/margin/balance",
                   data={"date": d.strftime("%Y/%m/%d"), "response": "json"})
        out.update(parse_tpex_margin(r.json()))
    except Exception:
        pass
    return out


def fetch_short_latest(c: httpx.Client) -> dict:
    out = {}
    for u in ("https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
              "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"):
        try:
            out.update(parse_openapi_margin(c.get(u).json()))
        except Exception:
            pass
    return out


def fetch_revenue(c: httpx.Client) -> dict:
    out = {}
    for u in ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
              "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"):
        try:
            out.update(parse_revenue(c.get(u).json()))
        except Exception:
            pass
    return out


def scan_conv_adjust(c: httpx.Client, days: int, pause: float = 1.2, progress=None) -> list:
    """往回 days 個交易日的重大訊息，抓「轉換價格」公告 → [{sid, series, date, price, subject}]"""
    from mna.fetcher import API, _API_HDR, fetch_detail
    out = []
    d = date.today()
    targets = []
    while len(targets) < days:
        if d.weekday() < 5:
            targets.append(d)
        d -= timedelta(days=1)
    fails = 0
    for k, day in enumerate(targets, 1):
        try:
            r = c.post(f"{API}/t05st02", headers=_API_HDR,
                       json={"year": str(day.year - 1911), "month": f"{day.month:02d}", "day": f"{day.day:02d}"})
            rows = ((r.json().get("result") or {}).get("data")) or []
            fails = 0
        except Exception:
            rows = []
            fails += 1
            if fails >= 5:
                break
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                continue
            subject = re.sub(r"\s+", "", str(row[4]))
            if "轉換價格" not in subject or "海外" in subject:
                continue
            params = row[5].get("parameters") if isinstance(row[5], dict) else None
            if not isinstance(params, dict):
                continue
            text = fetch_detail(params, c)
            for x in parse_conv_adjust(subject, text):
                out.append({"sid": str(row[2]).strip(), "series": x["series"], "date": day.isoformat(),
                            "price": x["price"], "subject": subject[:200]})
            time.sleep(pause)
        if progress:
            progress(k, len(targets))
        time.sleep(pause)
    return out
