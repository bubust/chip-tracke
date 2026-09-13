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
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")


async def fetch_taiex_ohlcv(days: int = 400) -> list[dict]:
    """Fetch TAIEX OHLCV from Yahoo Finance ^TWII."""
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
    """Fetch TX futures OHLCV from FinMind TaiwanFuturesDaily."""
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
            # Group by date, take the contract with most volume (front month)
            by_date: dict[str, dict] = {}
            for item in data:
                dt = item.get("date", "")[:10]
                vol = item.get("trading_volume", 0) or 0
                if dt not in by_date or vol > (by_date[dt].get("_vol", 0)):
                    by_date[dt] = {
                        "tx_open": item.get("open"),
                        "tx_high": item.get("max"),
                        "tx_low": item.get("min"),
                        "tx_close": item.get("close"),
                        "tx_volume": item.get("trading_volume"),
                        "_vol": vol,
                    }
            return [{"observation_date": dt, **v} for dt, v in sorted(by_date.items())]
        except Exception as e:
            log.warning(f"TX futures FinMind: {e}")
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

        merged = {
            "observation_date": dt,
            "taiex_open": row["taiex_open"],
            "taiex_high": row["taiex_high"],
            "taiex_low": row["taiex_low"],
            "taiex_close": row["taiex_close"],
            "taiex_volume": row["taiex_volume"],
            "taiex_return_1d": taiex_ret,
            "tx_open": tx.get("tx_open"),
            "tx_high": tx.get("tx_high"),
            "tx_low": tx.get("tx_low"),
            "tx_close": tx.get("tx_close"),
            "tx_volume": tx.get("tx_volume"),
            "tx_return_1d": tx_ret,
            "tx_relative_return": tx_rel,
        }
        upsert_market_daily(conn, merged)
        saved += 1
        if row["taiex_close"]:
            prev_taiex = row["taiex_close"]
        if tx.get("tx_close"):
            prev_tx = tx["tx_close"]

    conn.commit()
    conn.close()
    log.info(f"[relationship] saved {saved} rows")
    return saved
