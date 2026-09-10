"""
Regime Engine — 資料抓取
Sprint 1: Yahoo Finance TAIEX/OTC/SOX/VIX/US10Y/USDTWD/TSM_ADR/SP500/NASDAQ
Sprint 2: 市場廣度(>50MA%) + A/D線 + TAIFEX外資期貨 + 中位數漲跌幅
"""
import logging
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
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


# ── Sprint 2 ──────────────────────────────────────────────────────────────────

# 主 DB 路徑（cache.db 有 price_daily）
_MAIN_DB = Path(__file__).parent.parent / "chip_data" / "cache.db"


def _open_main_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_MAIN_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fetch_breadth_ad(lookback: int = 90):
    """
    從 price_daily 計算並寫入:
    - BREADTH_50MA: 全市場站上50日均線比例(0~100)
    - AD_LINE     : 漲家數 - 跌家數（每日）
    - MEDIAN_RET  : 全市場中位數漲跌幅(%)
    lookback: 計算最近幾天的資料
    """
    if not _MAIN_DB.exists():
        log.warning("[fetcher] cache.db 不存在，跳過 breadth 計算")
        return

    try:
        conn = _open_main_db()
        # 取最近 (lookback + 60) 天資料，多抓 60 天供 50MA 計算
        cutoff = (date.today() - timedelta(days=lookback + 65)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT date, stock_id, close FROM price_daily WHERE date >= ? AND close IS NOT NULL ORDER BY stock_id, date",
            (cutoff,),
        ).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"[fetcher] 讀取 price_daily 失敗: {e}")
        return

    if not rows:
        return

    # 按股票分組取收盤序列
    from collections import defaultdict
    stock_closes: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        stock_closes[r["stock_id"]].append((r["date"], float(r["close"])))

    # 取所有需計算的日期（最近 lookback 天）
    cutoff_target = (date.today() - timedelta(days=lookback)).strftime("%Y-%m-%d")
    all_dates_in_range: set[str] = set()
    for closes in stock_closes.values():
        for dt, _ in closes:
            if dt >= cutoff_target:
                all_dates_in_range.add(dt)
    sorted_dates = sorted(all_dates_in_range)

    # 對每個日期計算廣度指標
    date_above50: dict[str, list[int]] = defaultdict(list)
    date_changes:  dict[str, list[float]] = defaultdict(list)
    date_ad:       dict[str, int] = defaultdict(int)

    for sid, closes in stock_closes.items():
        if len(closes) < 2:
            continue
        prices_arr = [c for _, c in closes]
        dates_arr  = [d for d, _ in closes]

        for i, (dt, px) in enumerate(closes):
            if dt < cutoff_target:
                continue
            # 50MA: 使用到當日為止的最多50筆
            start = max(0, i - 49)
            window = prices_arr[start:i + 1]
            if len(window) >= 10:  # 至少10筆才算
                ma50 = sum(window) / len(window)
                date_above50[dt].append(1 if px > ma50 else 0)

            # A/D + 中位數漲跌幅：比前一日
            if i > 0:
                prev_px = prices_arr[i - 1]
                if prev_px > 0:
                    chg_pct = (px - prev_px) / prev_px * 100
                    date_changes[dt].append(chg_pct)
                    date_ad[dt] += (1 if chg_pct > 0 else (-1 if chg_pct < 0 else 0))

    with db() as conn:
        for dt in sorted_dates:
            # BREADTH_50MA
            above50 = date_above50.get(dt, [])
            if above50:
                pct = round(sum(above50) / len(above50) * 100, 2)
                upsert_series(conn, dt, "BREADTH_50MA", pct, "PRICE_DAILY")

            # AD_LINE
            ad = date_ad.get(dt)
            if ad is not None:
                upsert_series(conn, dt, "AD_LINE", ad, "PRICE_DAILY")

            # MEDIAN_RET
            changes = date_changes.get(dt, [])
            if changes:
                sorted_chgs = sorted(changes)
                n = len(sorted_chgs)
                med = (sorted_chgs[n // 2] if n % 2 == 1
                       else (sorted_chgs[n // 2 - 1] + sorted_chgs[n // 2]) / 2)
                upsert_series(conn, dt, "MEDIAN_RET", round(med, 4), "PRICE_DAILY")

    log.info(f"[fetcher] Breadth/AD/MedianRet: {len(sorted_dates)} 天 寫入完成")


def fetch_taifex_foreign_futures():
    """
    TAIFEX 外資期貨未平倉淨部位 → series: FOREIGN_FUTURES_NET (張)
    資料來源: TAIFEX 盤後資訊 - 交易人期貨與選擇權未平倉量彙整表
    """
    today_str = date.today().strftime("%Y/%m/%d")
    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA, "Referer": "https://www.taifex.com.tw/"}, verify=False) as c:
            r = c.post(url, data={
                "queryStartDate": today_str,
                "queryEndDate": today_str,
                "commodityId": "TXF",  # 台指期
            })
        # 解析 CSV (TAIFEX 回傳格式為 CSV)
        lines = r.text.strip().split("\n")
        net_lot = None
        for line in lines:
            if "外資" in line or "Foreign" in line.lower():
                parts = line.replace('"', '').split(",")
                # 外資買方 - 賣方未平倉
                try:
                    # 典型格式: 日期, 商品名稱, 身份別, 多方口數, 多方契約金額, 空方口數, 空方契約金額, 多空淨額口數, ...
                    net_str = parts[7].replace(",", "").strip()
                    net_lot = int(net_str)
                    break
                except Exception:
                    continue
        if net_lot is not None:
            dt = date.today().strftime("%Y-%m-%d")
            with db() as conn:
                upsert_series(conn, dt, "FOREIGN_FUTURES_NET", net_lot, "TAIFEX")
            log.info(f"[fetcher] FOREIGN_FUTURES_NET: {net_lot} 張")
    except Exception as e:
        log.warning(f"[fetcher] TAIFEX 外資期貨 失敗: {e}")
