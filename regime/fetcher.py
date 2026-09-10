"""
Regime Engine — Yahoo Finance 資料抓取
Series: TAIEX, OTC, SOX, VIX, US10Y, USDTWD, TSM_ADR, SP500, NASDAQ
"""
import logging
from datetime import datetime, date, timedelta
import httpx

from .db import db, upsert_series

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

YAHOO_TICKERS = {
    "TAIEX":   "^TWII",
    "OTC":     "^TWOII",
    "SOX":     "^SOX",
    "VIX":     "^VIX",
    "US10Y":   "^TNX",
    "USDTWD":  "TWD=X",
    "TSM_ADR": "TSM",
    "SP500":   "^GSPC",
    "NASDAQ":  "^IXIC",
}

def _yahoo_close(ticker: str, days: int = 30) -> list[tuple[str, float]]:
    """回傳 [(date_str, close), ...] 最近 days 天"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": f"{days}d"}
    try:
        with httpx.Client(timeout=12, headers={"User-Agent": _UA}) as c:
            r = c.get(url, params=params)
            data = r.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            return []
        r0 = result[0]
        timestamps = r0.get("timestamp", [])
        closes = r0["indicators"]["quote"][0].get("close", [])
        out = []
        import pandas as pd
        tw_offset = pd.Timedelta(hours=8)
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            dt = (pd.Timestamp(ts, unit="s", tz="UTC") + tw_offset).strftime("%Y-%m-%d")
            out.append((dt, round(float(close), 6)))
        return out
    except Exception as e:
        log.warning(f"[fetcher] {ticker} 失敗: {e}")
        return []


def fetch_all(days: int = 60):
    """抓取所有 Yahoo Finance 系列並寫入 DB"""
    inserted = 0
    with db() as conn:
        for series, ticker in YAHOO_TICKERS.items():
            rows = _yahoo_close(ticker, days)
            for dt, val in rows:
                upsert_series(conn, dt, series, val, "YAHOO")
                inserted += 1
            log.info(f"[fetcher] {series}({ticker}): {len(rows)} 筆")
    log.info(f"[fetcher] 共寫入 {inserted} 筆")
    return inserted


def fetch_twse_margin(days: int = 5):
    """TWSE MI_MARGN — 融資餘額 (市場合計) → series: MARGIN_BALANCE"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as c:
            r = c.get(url)
            rows = r.json()
        with db() as conn:
            for row in rows:
                date_str = row.get("Date", "")
                # date format: YYYYMMDD
                if len(date_str) == 8:
                    dt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                else:
                    continue
                # 融資餘額 (股)
                val_str = str(row.get("MarginPurchaseAmount", "0")).replace(",", "")
                try:
                    val = float(val_str)
                except Exception:
                    continue
                upsert_series(conn, dt, "MARGIN_BALANCE", val, "TWSE")
        log.info(f"[fetcher] MARGIN_BALANCE: OK")
    except Exception as e:
        log.warning(f"[fetcher] MI_MARGN 失敗: {e}")


def fetch_twse_foreign_spot():
    """TWSE T86 外資現貨買賣超 → series: FOREIGN_NET_LOT (張)"""
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    from datetime import date as _date
    dt_str = _date.today().strftime("%Y%m%d")
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA, "Referer": "https://www.twse.com.tw/"}, verify=False) as c:
            r = c.get(url, params={"date": dt_str, "selectType": "ALL", "response": "json"})
            t86 = r.json()
        if t86.get("stat") != "OK":
            return
        total_foreign_net = 0
        for row in t86.get("data", []):
            try:
                total_foreign_net += float(str(row[4]).replace(",", "")) / 1000
            except Exception:
                pass
        dt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
        with db() as conn:
            upsert_series(conn, dt, "FOREIGN_NET_LOT", round(total_foreign_net), "TWSE_T86")
        log.info(f"[fetcher] FOREIGN_NET_LOT: {round(total_foreign_net)} 張")
    except Exception as e:
        log.warning(f"[fetcher] T86 失敗: {e}")
