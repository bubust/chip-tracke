"""
Fetches TAIEX OHLCV and TX futures OHLCV.
TX futures: 期交所每日行情下載（一般時段、成交量最大的單月契約），FinMind 備援。
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
    """台指期（TX）日資料：期交所下載為主（沒有次數限制），FinMind 備援。
    只取「一般」交易時段、單一月份契約（排除盤後、價差、週契約），每天取成交量最大的那個月份（近月，轉倉後換次月），
    漲跌%用同一個契約自己的漲跌（轉倉日不會跳空），未平倉量＝一般時段各月份加總。
    兩個來源都失敗就回空的：不再用加權指數假裝成期貨（會造成假的「同步／背離」訊號）。"""
    result = await _fetch_tx_taifex(days)
    if result:
        return result
    log.warning("[relationship] 期交所 TX 失敗，改用 FinMind")
    return await _fetch_tx_finmind(days)


def _num(x):
    x = (x or "").strip().replace(",", "").rstrip("%")
    if x in ("", "-"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def _pick_tx(rows_by_date: dict) -> list[dict]:
    """rows_by_date = {date: [(contract, open, high, low, close, chg_pct, volume, oi), ...]}（只放一般時段單月契約）"""
    out = []
    for dt in sorted(rows_by_date):
        rows = [r for r in rows_by_date[dt] if r[4] is not None]
        if not rows:
            continue
        best = max(rows, key=lambda r: r[6] or 0)
        oi = sum(r[7] or 0 for r in rows_by_date[dt]) or None
        out.append({"observation_date": dt, "tx_contract": best[0], "tx_open": best[1], "tx_high": best[2],
                    "tx_low": best[3], "tx_close": best[4], "tx_chg_pct": best[5], "tx_volume": best[6],
                    "total_oi": oi})
    return out


async def _fetch_tx_taifex(days: int) -> list[dict]:
    """期交所「期貨每日交易行情下載」，一次查 30 天"""
    end = date.today()
    start = end - timedelta(days=days)
    by_date: dict = {}
    async with httpx.AsyncClient(headers={"User-Agent": _UA, "Referer": "https://www.taifex.com.tw/cht/3/futDataDown"},
                                 timeout=60) as client:
        cur = start
        while cur <= end:
            to = min(cur + timedelta(days=29), end)
            text = ""
            for attempt in range(3):                                       # 偶爾整段失敗 → 重試，避免整個月缺資料
                try:
                    r = await client.post("https://www.taifex.com.tw/cht/3/futDataDown", data={
                        "down_type": "1", "commodity_id": "TX", "commodity_id2": "",
                        "queryStartDate": cur.strftime("%Y/%m/%d"), "queryEndDate": to.strftime("%Y/%m/%d")})
                    text = r.content.decode("ms950", errors="replace")
                    if r.status_code == 200 and text.startswith("交易日期"):
                        break
                except Exception as e:
                    log.warning(f"[relationship] 期交所 TX {cur}~{to} 第 {attempt + 1} 次: {e}")
                text = ""
                await asyncio.sleep(2 * (attempt + 1))
            try:
                for line in text.splitlines()[1:]:
                    c = line.split(",")
                    if len(c) < 18 or c[1].strip() != "TX" or c[17].strip() != "一般":
                        continue
                    month = c[2].strip()
                    if not (len(month) == 6 and month.isdigit()):          # 排除價差（202610/202611）與週契約
                        continue
                    dt = c[0].strip().replace("/", "-")
                    by_date.setdefault(dt, []).append(
                        (month, _num(c[3]), _num(c[4]), _num(c[5]), _num(c[6]), _num(c[8]), _num(c[9]), _num(c[11])))
            except Exception as e:
                log.warning(f"[relationship] 期交所 TX {cur}~{to}: {e}")
            cur = to + timedelta(days=1)
            await asyncio.sleep(0.5)
    out = _pick_tx(by_date)
    log.info(f"[relationship] TX from TAIFEX: {len(out)} days")
    return out


async def _fetch_tx_finmind(days: int) -> list[dict]:
    if not FINMIND_TOKEN:
        log.warning("FINMIND_TOKEN not set, TX futures unavailable")
        return []
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"dataset": "TaiwanFuturesDaily", "data_id": "TX", "start_date": start, "token": FINMIND_TOKEN}
    async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=60) as client:
        try:
            r = await client.get("https://api.finmindtrade.com/api/v4/data", params=params)
            data = r.json().get("data", [])
            by_date: dict = {}
            for it in data:
                month = str(it.get("contract_date", "")).strip()
                if it.get("trading_session", "position") != "position" or not (len(month) == 6 and month.isdigit()):
                    continue
                f = lambda k: _num(str(it.get(k))) if it.get(k) is not None else None
                by_date.setdefault(it.get("date", "")[:10], []).append(
                    (month, f("open"), f("max"), f("min"), f("close"), f("spread_per"), f("volume"), f("open_interest")))
            return _pick_tx(by_date)
        except Exception as e:
            log.warning(f"TX futures FinMind: {e}")
            return []


async def fetch_all(days: int = 400):
    """Fetch and merge TAIEX + TX data, save to DB."""
    taiex_rows, tx_rows = await asyncio.gather(
        fetch_taiex_ohlcv(days + 120),          # 多抓 120 天：MA60 與 5 日 OI 變化要有足夠歷史
        fetch_tx_futures_ohlcv(days + 10),
    )
    write_from = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Build TX lookup
    tx_map = {r["observation_date"]: r for r in tx_rows}

    conn = get_conn()
    saved = 0
    prev_taiex = None
    prev_tx = None
    prev_oi = None
    oi_hist: list = []         # for oi_change_5d
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
        if tx.get("tx_chg_pct") is not None:              # 同一個契約自己的漲跌%（轉倉日不會跳）
            tx_ret = round(tx["tx_chg_pct"], 4)
        elif prev_tx and tx.get("tx_close") and prev_tx > 0:
            tx_ret = round((tx["tx_close"] - prev_tx) / prev_tx * 100, 4)
        tx_rel = round(tx_ret - taiex_ret, 4) if tx_ret is not None and taiex_ret is not None else None

        # OI change
        total_oi = tx.get("total_oi")
        oi_change = None
        if prev_oi is not None and total_oi is not None:
            oi_change = round(total_oi - prev_oi, 0)
        oi_change_5d = round(total_oi - oi_hist[-5], 0) if total_oi is not None and len(oi_hist) >= 5 else None

        # MA20 / MA60
        if row["taiex_close"]:
            rolling_closes.append(row["taiex_close"])
        ma20 = round(sum(rolling_closes[-20:]) / 20, 2) if len(rolling_closes) >= 20 else None
        ma60 = round(sum(rolling_closes[-60:]) / 60, 2) if len(rolling_closes) >= 60 else None

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
            "oi_change_5d": oi_change_5d,
        }
        if dt >= write_from:
            upsert_market_daily(conn, merged)
            saved += 1
        if row["taiex_close"]:
            prev_taiex = row["taiex_close"]
        if tx.get("tx_close"):
            prev_tx = tx["tx_close"]
        if total_oi:
            prev_oi = total_oi
            oi_hist.append(total_oi)

    conn.commit()
    conn.close()
    log.info(f"[relationship] saved {saved} rows")
    return saved
