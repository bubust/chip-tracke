"""
Fetches TAIEX OHLCV and TX futures OHLCV.
TX futures: use FinMind TaiwanFuturesDaily (contract TX, continuous front month).
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx

from .db import get_conn, upsert_market_daily, DB_PATH
import os

log = logging.getLogger(__name__)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA")


async def fetch_taiex_ohlcv(days: int = 400) -> list[dict]:
    """Fetch TAIEX OHLCV from FinMind Y9999 (primary) or Yahoo Finance ^TWII (fallback)."""
    # ── FinMind TaiwanStockPrice Y9999 (TAIEX) ──
    if FINMIND_TOKEN:
        try:
            fm_url = "https://api.finmindtrade.com/api/v4/data"
            fm_start = (date.today() - timedelta(days=days + 30)).strftime("%Y-%m-%d")
            async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=30) as fm_client:
                fm_r = await fm_client.get(fm_url, params={
                    "dataset": "TaiwanStockPrice", "data_id": "Y9999",
                    "start_date": fm_start, "token": FINMIND_TOKEN,
                })
                fm_data = fm_r.json().get("data", [])
                if fm_data:
                    rows = []
                    for item in fm_data:
                        dt = item.get("date", "")[:10]
                        rows.append({
                            "observation_date": dt,
                            "taiex_open": item.get("open"),
                            "taiex_high": item.get("max"),
                            "taiex_low": item.get("min"),
                            "taiex_close": item.get("close"),
                            "taiex_volume": item.get("Trading_Volume"),
                        })
                    rows = [r for r in rows if r["taiex_close"]]
                    if rows:
                        log.info(f"[relationship] TAIEX from FinMind Y9999: {len(rows)} rows")
                        return rows
        except Exception as e:
            log.warning(f"[relationship] FinMind Y9999 failed: {e}")

    range_str = f"{min(days // 250 + 1, 5)}y"
    urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range={range_str}",
        f"https://query2.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range={range_str}",
    ]
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=30, follow_redirects=True
    ) as client:
        for url in urls:
            try:
                r = await client.get(url)
                j = r.json()
                result = j["chart"]["result"][0]
                timestamps = result["timestamp"]
                q = result["indicators"]["quote"][0]
                rows = []
                for i, ts in enumerate(timestamps):
                    dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                    rows.append({
                        "observation_date": dt,
                        "taiex_open": q["open"][i],
                        "taiex_high": q["high"][i],
                        "taiex_low": q["low"][i],
                        "taiex_close": q["close"][i],
                        "taiex_volume": q["volume"][i] if q["volume"][i] else None,
                    })
                return [r for r in rows if r["taiex_close"] is not None]
            except Exception as e:
                log.warning(f"TAIEX OHLCV from {url}: {e}")
    return []


async def fetch_tx_futures_ohlcv(days: int = 400) -> list[dict]:
    """Fetch TX futures OHLCV from FinMind TaiwanFuturesDaily.
    Falls back to Yahoo ^TWII (TAIEX spot) when FinMind fails.
    Note: Yahoo fallback yields tx_volume=None, total_oi=None; basis metrics will be absent.
    """
    result = await _fetch_tx_finmind(days)
    if result:
        return result
    log.warning("[relationship] FinMind TX 失敗，改用 Yahoo ^TWII 估代（basis 指標不可用）")
    return await _fetch_tx_yahoo_fallback(days)


async def _fetch_tx_finmind(days: int) -> list[dict]:
    if not FINMIND_TOKEN:
        log.warning("FINMIND_TOKEN not set, TX futures unavailable")
        return []
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanFuturesDaily",
        "data_id": "TX",
        "start_date": start,
        "token": FINMIND_TOKEN,
    }
    async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=60) as client:
        try:
            r = await client.get(url, params=params)
            j = r.json()
            data = j.get("data", [])
            if not data:
                return []
            # Group by date: highest-volume contract for price; sum OI across all contracts
            price_by_date: dict[str, dict] = {}
            oi_by_date: dict[str, float] = {}
            for item in data:
                dt = item.get("date", "")[:10]
                vol = item.get("trading_volume", 0) or 0
                oi = item.get("open_interest", 0) or 0
                oi_by_date[dt] = oi_by_date.get(dt, 0) + oi
                if dt not in price_by_date or vol > (price_by_date[dt].get("_vol", 0)):
                    price_by_date[dt] = {
                        "tx_open": item.get("open"),
                        "tx_high": item.get("max"),
                        "tx_low": item.get("min"),
                        "tx_close": item.get("close"),
                        "tx_volume": item.get("trading_volume"),
                        "_vol": vol,
                    }
            return [{"observation_date": dt, **v, "total_oi": oi_by_date.get(dt)}
                    for dt, v in sorted(price_by_date.items())]
        except Exception as e:
            log.warning(f"TX futures FinMind: {e}")
            return []


async def _fetch_tx_yahoo_fallback(days: int) -> list[dict]:
    """Yahoo Finance ^TWII 作為 TX 代理（缺 basis，但趨勢方向判斷有效）"""
    from datetime import datetime, timezone
    range_str = f"{min(days // 250 + 1, 5)}y"
    urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range={range_str}",
        f"https://query2.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range={range_str}",
    ]
    async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=30) as client:
        for url in urls:
            try:
                r = await client.get(url)
                j = r.json()
                results_list = (j.get("chart") or {}).get("result") or []
                if not results_list:
                    continue
                result = results_list[0]
                timestamps = result["timestamp"]
                q = result["indicators"]["quote"][0]
                rows = []
                for i, ts in enumerate(timestamps):
                    c = q["close"][i]
                    if c is None:
                        continue
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    rows.append({
                        "observation_date": dt,
                        "tx_open": q["open"][i], "tx_high": q["high"][i],
                        "tx_low": q["low"][i],   "tx_close": c,
                        "tx_volume": None, "total_oi": None, "_vol": 1,
                    })
                if rows:
                    return rows
            except Exception as e:
                log.warning(f"[relationship] Yahoo TX fallback {url}: {e}")
    return []


async def fetch_all(days: int = 400):
    """Fetch and merge TAIEX + TX data, save to DB."""
    taiex_rows, tx_rows = await asyncio.gather(
        fetch_taiex_ohlcv(days),
        fetch_tx_futures_ohlcv(days),
    )

    # Build TX lookup
    tx_map = {r["observation_date"]: r for r in tx_rows}

    conn = get_conn()
    saved = 0
    prev_taiex = None
    prev_tx = None
    prev_oi = None
    rolling_closes: list = []  # for MA20/MA60 calculation

    # Sort by date ascending so we can compute returns in order
    taiex_rows.sort(key=lambda x: x["observation_date"])

    for row in taiex_rows:
        dt = row["observation_date"]
        tx = tx_map.get(dt, {})

        # Returns
        taiex_ret = None
        tx_ret = None
        if prev_taiex and row["taiex_close"] and prev_taiex > 0:
            taiex_ret = round((row["taiex_close"] - prev_taiex) / prev_taiex * 100, 4)
        if prev_tx and tx.get("tx_close") and prev_tx > 0:
            tx_ret = round((tx["tx_close"] - prev_tx) / prev_tx * 100, 4)
        tx_rel = round(tx_ret - taiex_ret, 4) if tx_ret is not None and taiex_ret is not None else None

        # OI change
        total_oi = tx.get("total_oi")
        oi_change = None
        if prev_oi is not None and total_oi is not None:
            oi_change = round(total_oi - prev_oi, 0)

        # MA20 / MA60
        if row["taiex_close"]:
            rolling_closes.append(row["taiex_close"])
        ma20 = round(sum(rolling_closes[-20:]) / len(rolling_closes[-20:]), 2) if len(rolling_closes) >= 2 else None
        ma60 = round(sum(rolling_closes[-60:]) / len(rolling_closes[-60:]), 2) if len(rolling_closes) >= 2 else None

        merged = {
            "observation_date": dt,
            "taiex_open": row["taiex_open"],
            "taiex_high": row["taiex_high"],
            "taiex_low": row["taiex_low"],
            "taiex_close": row["taiex_close"],
            "taiex_volume": row["taiex_volume"],
            "taiex_return_1d": taiex_ret,
            "taiex_ma20": ma20,
            "taiex_ma60": ma60,
            "tx_open": tx.get("tx_open"),
            "tx_high": tx.get("tx_high"),
            "tx_low": tx.get("tx_low"),
            "tx_close": tx.get("tx_close"),
            "tx_volume": tx.get("tx_volume"),
            "tx_return_1d": tx_ret,
            "tx_relative_return": tx_rel,
            "total_oi": total_oi,
            "oi_change_1d": oi_change,
        }
        upsert_market_daily(conn, merged)
        saved += 1
        if row["taiex_close"]:
            prev_taiex = row["taiex_close"]
        if tx.get("tx_close"):
            prev_tx = tx["tx_close"]
        if total_oi:
            prev_oi = total_oi

    conn.commit()
    conn.close()
    log.info(f"[relationship] saved {saved} rows")
    return saved
