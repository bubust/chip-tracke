"""
sector/prices.py — 用 TWSE/TPEx 批次端點抓全市場股價並存入 sector_stock_daily
每次呼叫 fetch_and_store_today() 只需 2 個 HTTP 請求（TWSE + TPEx），
完全不依賴 Yahoo Finance 的個股查詢。
"""
import logging
import time
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional

import httpx

from .db import db, init_db

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
_TWSE_TODAY   = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_TWSE_HIST    = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
_TPEX_TODAY   = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
_TPEX_HIST    = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"


# ─────────────────────────────────────────────────────────────────────────────
# TWSE 批次抓取
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_twse_today() -> list[dict]:
    """抓今日 TWSE 全市場收盤資料，回傳 [{stock_id, open, high, low, close, volume}, ...]"""
    try:
        with httpx.Client(headers={"User-Agent": _UA}, timeout=30, follow_redirects=True) as c:
            r = c.get(_TWSE_TODAY)
            r.raise_for_status()
            data = r.json()
        records = []
        for row in data:
            sid  = str(row.get("Code") or row.get("stock_id") or "").strip()
            if not sid or not sid.isdigit():
                continue
            try:
                close  = float(str(row.get("ClosingPrice") or row.get("close") or "0").replace(",", "") or 0)
                open_  = float(str(row.get("OpeningPrice") or row.get("open") or close).replace(",", "") or close)
                high   = float(str(row.get("HighestPrice") or row.get("high") or close).replace(",", "") or close)
                low    = float(str(row.get("LowestPrice")  or row.get("low")  or close).replace(",", "") or close)
                vol    = float(str(row.get("TradeVolume")  or row.get("volume") or "0").replace(",", "") or 0)
            except (ValueError, TypeError):
                continue
            if close <= 0:
                continue
            records.append({"stock_id": sid, "open": open_, "high": high, "low": low, "close": close, "volume": vol})
        log.info(f"[prices] TWSE today: {len(records)} stocks")
        return records
    except Exception as e:
        log.warning(f"[prices] TWSE today failed: {e}")
        return []


def _fetch_twse_hist(date_str: str) -> list[dict]:
    """抓指定日期 TWSE 收盤（格式 YYYYMMDD），回傳同結構"""
    try:
        with httpx.Client(headers={"User-Agent": _UA}, timeout=30, follow_redirects=True) as c:
            r = c.get(_TWSE_HIST, params={"date": date_str, "response": "json"})
            r.raise_for_status()
            data = r.json()
        rows = data.get("data") or []
        fields = data.get("fields") or []
        # fields 典型: ['證券代號','證券名稱','成交股數','成交筆數','成交金額','開盤價','最高價','最低價','收盤價',...]
        f_idx = {f: i for i, f in enumerate(fields)}
        code_i  = f_idx.get("證券代號", 0)
        open_i  = f_idx.get("開盤價")
        high_i  = f_idx.get("最高價")
        low_i   = f_idx.get("最低價")
        close_i = f_idx.get("收盤價")
        vol_i   = f_idx.get("成交股數")

        if close_i is None:
            log.warning(f"[prices] TWSE hist {date_str}: fields={fields}")
            return []

        records = []
        for row in rows:
            sid = str(row[code_i]).strip()
            if not sid or not sid.isdigit():
                continue
            try:
                def _f(i): return float(str(row[i]).replace(",", "")) if i is not None and i < len(row) else 0.0
                close = _f(close_i)
                if close <= 0:
                    continue
                records.append({
                    "stock_id": sid,
                    "open":   _f(open_i)  or close,
                    "high":   _f(high_i)  or close,
                    "low":    _f(low_i)   or close,
                    "close":  close,
                    "volume": _f(vol_i),
                })
            except Exception:
                continue
        log.info(f"[prices] TWSE hist {date_str}: {len(records)} stocks")
        return records
    except Exception as e:
        log.warning(f"[prices] TWSE hist {date_str} failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# TPEx 批次抓取
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_tpex_today() -> list[dict]:
    """抓今日 TPEx 全市場收盤"""
    try:
        with httpx.Client(headers={"User-Agent": _UA}, timeout=30, follow_redirects=True) as c:
            r = c.get(_TPEX_TODAY)
            r.raise_for_status()
            data = r.json()
        records = []
        for row in data:
            sid = str(row.get("SecuritiesCompanyCode") or row.get("stock_id") or "").strip()
            if not sid or not sid.isdigit():
                continue
            try:
                close = float(str(row.get("Close") or row.get("close") or "0").replace(",", "") or 0)
                open_ = float(str(row.get("Open")  or row.get("open")  or close).replace(",", "") or close)
                high  = float(str(row.get("High")  or row.get("high")  or close).replace(",", "") or close)
                low   = float(str(row.get("Low")   or row.get("low")   or close).replace(",", "") or close)
                vol   = float(str(row.get("TradingShares") or row.get("volume") or "0").replace(",", "") or 0)
            except (ValueError, TypeError):
                continue
            if close <= 0:
                continue
            records.append({"stock_id": sid, "open": open_, "high": high, "low": low, "close": close, "volume": vol})
        log.info(f"[prices] TPEx today: {len(records)} stocks")
        return records
    except Exception as e:
        log.warning(f"[prices] TPEx today failed: {e}")
        return []


def _fetch_tpex_hist(date_str: str) -> list[dict]:
    """抓指定日期 TPEx 收盤（格式 YYYYMMDD）"""
    try:
        # TPEx 歷史格式：年份用民國年，YYYYMMDD → 取月日
        dt = datetime.strptime(date_str, "%Y%m%d")
        roc_year = dt.year - 1911
        yymm = f"{roc_year:03d}/{dt.month:02d}"
        with httpx.Client(headers={"User-Agent": _UA}, timeout=30, follow_redirects=True) as c:
            r = c.get(_TPEX_HIST, params={"d": yymm, "se": "EW", "s": "0,asc", "o": "json"})
            r.raise_for_status()
            data = r.json()

        aadata = data.get("aaData") or []
        records = []
        for row in aadata:
            if len(row) < 9:
                continue
            sid = str(row[0]).strip()
            if not sid or not sid.isdigit():
                continue
            try:
                def _f(v): return float(str(v).replace(",", "")) if v and str(v).strip() not in ("", "--") else 0.0
                # [0]=代號,[1]=名稱,[2]=收盤,[3]=漲跌,[4]=開盤,[5]=最高,[6]=最低,[7]=成交量,[8]=成交值
                close = _f(row[2])
                if close <= 0:
                    continue
                records.append({
                    "stock_id": sid,
                    "open":   _f(row[4]) or close,
                    "high":   _f(row[5]) or close,
                    "low":    _f(row[6]) or close,
                    "close":  close,
                    "volume": _f(row[7]),
                })
            except Exception:
                continue
        log.info(f"[prices] TPEx hist {date_str}: {len(records)} stocks")
        return records
    except Exception as e:
        log.warning(f"[prices] TPEx hist {date_str} failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 存入 DB
# ─────────────────────────────────────────────────────────────────────────────

def store_prices(date_str: str, records: list[dict]) -> int:
    """將一天的價格資料存入 sector_stock_daily，回傳寫入筆數"""
    if not records:
        return 0
    init_db()
    rows = [
        (date_str, r["stock_id"], r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("volume"))
        for r in records
    ]
    with db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO sector_stock_daily
               (date, stock_id, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 主要對外介面
# ─────────────────────────────────────────────────────────────────────────────

def fetch_and_store_today() -> dict:
    """
    抓今日 TWSE + TPEx 全市場價格並存入 DB。
    只需 2 個 HTTP 請求，不依賴 Yahoo。
    """
    today = date.today().strftime("%Y%m%d")
    twse = _fetch_twse_today()
    tpex = _fetch_tpex_today()
    all_rec = twse + tpex
    n = store_prices(today, all_rec)
    log.info(f"[prices] 今日存入 {n} 筆（TWSE={len(twse)}, TPEx={len(tpex)}）")
    return {"date": today, "twse": len(twse), "tpex": len(tpex), "stored": n}


def backfill(days: int = 120) -> dict:
    """
    補抓歷史價格（最近 days 個自然日，跳過已有資料的日期）。
    只查 TWSE + TPEx 批次端點，每天 2 個請求，間隔 1 秒。
    """
    init_db()
    total_stored = 0
    skipped = 0

    # 查已有哪些日期
    with db() as conn:
        existing = {row[0] for row in conn.execute("SELECT DISTINCT date FROM sector_stock_daily")}

    target_days = []
    for i in range(1, days + 1):
        d = date.today() - timedelta(days=i)
        # 跳過週末
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        if ds in existing:
            skipped += 1
            continue
        target_days.append(ds)

    log.info(f"[prices] 補抓 {len(target_days)} 天（已有 {skipped} 天跳過）")

    for ds in target_days:
        twse = _fetch_twse_hist(ds)
        tpex = _fetch_tpex_hist(ds)
        all_rec = twse + tpex
        if all_rec:
            n = store_prices(ds, all_rec)
            total_stored += n
        time.sleep(1.0)

    return {"backfilled_days": len(target_days), "stored": total_stored, "skipped": skipped}


def load_prices_from_db(stock_ids: list[str], min_dates: int = 60) -> dict:
    """
    從 sector_stock_daily 讀取指定股票清單的 DataFrame dict。
    回傳 {stock_id: pd.DataFrame(date, open, high, low, close, volume)}
    只回傳有足夠歷史（>= min_dates）的股票。
    """
    import pandas as pd

    if not stock_ids:
        return {}

    init_db()
    placeholders = ",".join("?" * len(stock_ids))
    with db() as conn:
        rows = conn.execute(
            f"""SELECT date, stock_id, open, high, low, close, volume
                FROM sector_stock_daily
                WHERE stock_id IN ({placeholders})
                ORDER BY stock_id, date""",
            stock_ids,
        ).fetchall()

    if not rows:
        return {}

    import pandas as pd
    df_all = pd.DataFrame(rows, columns=["date", "stock_id", "open", "high", "low", "close", "volume"])

    result = {}
    for sid, grp in df_all.groupby("stock_id"):
        grp = grp.drop(columns=["stock_id"]).reset_index(drop=True)
        grp = grp[grp["close"] > 0].copy()
        if len(grp) >= min_dates:
            result[str(sid)] = grp

    return result
