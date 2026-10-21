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

def _roc_to_ymd(s) -> str:
    """openapi 的 Date（民國 1151002）→ 20261002；格式不對回空字串"""
    s = str(s or "").strip()
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911}{s[3:]}"
    return ""


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
            records.append({"stock_id": sid, "open": open_, "high": high, "low": low, "close": close, "volume": vol,
                            "date": _roc_to_ymd(row.get("Date"))})
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
            records.append({"stock_id": sid, "open": open_, "high": high, "low": low, "close": close, "volume": vol,
                            "date": _roc_to_ymd(row.get("Date"))})
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
    抓 TWSE + TPEx openapi 全市場收盤並存入 DB（2 個請求）。
    openapi 常延遲到隔天才更新 → 一律用資料裡的 Date 當日期（舊版用「今天」，結果把昨天的價格存成今天）。
    """
    twse = _fetch_twse_today()
    tpex = _fetch_tpex_today()
    by_date: dict = {}
    for r in twse + tpex:
        if r.get("date"):
            by_date.setdefault(r["date"], []).append(r)
    n = sum(store_prices(d, recs) for d, recs in by_date.items())
    log.info(f"[prices] openapi 存入 {n} 筆，日期 {sorted(by_date)}（TWSE={len(twse)}, TPEx={len(tpex)}）")
    return {"dates": sorted(by_date), "twse": len(twse), "tpex": len(tpex), "stored": n}


def sync_from_price_cache(days: int = 200, full: bool = False) -> dict:
    """
    從主價格快取（cache.db 的 price_daily：全市場掃描／每日收盤更新，日期正確、有 2 年歷史）同步到 sector_stock_daily。
    price_daily 成交量是「張」，這裡換成「股」（×1000）跟 openapi 一致。
    某天在 price_daily 有 ≥ 1000 支（完整的一天）→ 先清掉該天舊資料再寫入（清掉以前存錯日期的列）。
    PLAN-B77 A2：以前每次把 200 天 × 2,100 檔（約 28 萬列）一次讀進記憶體再整段重寫（正式站 +170MB）；
    現在預設只同步 sector_stock_daily 最新日期往前 10 天之後的日子、一天一天讀寫；
    sector_stock_daily 不到 60 天或 full=True（產業頁「計算」按鈕）才同步整個 days 天。
    """
    import sqlite3
    from datetime import datetime as _dtm, timedelta as _td
    try:
        from chip_tracker_v2 import DB_PATH as _CACHE_DB
    except Exception as e:
        return {"error": f"找不到價格快取：{e}"}
    init_db()
    cutoff = (date.today() - _td(days=days)).strftime("%Y%m%d")
    with db() as conn:
        mapped = {r[0] for r in conn.execute("SELECT stock_id FROM stock_sector_map").fetchall()}
        last, n_days = conn.execute("SELECT MAX(date), COUNT(DISTINCT date) FROM sector_stock_daily").fetchone()
    mode = "full"
    if not full and last and n_days >= 60:
        try:
            inc = (_dtm.strptime(str(last), "%Y%m%d").date() - _td(days=10)).strftime("%Y%m%d")
            if inc > cutoff:
                cutoff, mode = inc, "incremental"
        except ValueError:
            pass
    src = sqlite3.connect(str(_CACHE_DB), timeout=30)
    total, stock_set, n_seen, full_days = 0, set(), 0, 0
    try:
        dates = [r[0] for r in src.execute(
            "SELECT DISTINCT date FROM price_daily WHERE date >= ? ORDER BY date", (cutoff,)).fetchall()]
        for d in dates:
            if len(str(d)) != 8:
                continue
            rows = [(d, sid, o, h, l, c, (v or 0) * 1000) for sid, o, h, l, c, v in src.execute(
                "SELECT stock_id, open, high, low, close, volume FROM price_daily WHERE date = ? AND close > 0", (d,))
                if sid in mapped]
            if not rows:
                continue
            n_seen += 1
            with db() as conn:
                if len(rows) >= 1000:
                    conn.execute("DELETE FROM sector_stock_daily WHERE date = ?", (d,))
                    full_days += 1
                conn.executemany(
                    """INSERT OR REPLACE INTO sector_stock_daily (date, stock_id, open, high, low, close, volume)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""", rows)
            total += len(rows)
            stock_set.update(r[1] for r in rows)
    finally:
        src.close()
    log.info(f"[prices] 從價格快取同步（{mode}，從 {cutoff}）{total} 筆、{len(stock_set)} 支、{n_seen} 天（完整 {full_days} 天）")
    return {"rows": total, "stocks": len(stock_set), "days": n_seen, "full_days": full_days, "mode": mode, "since": cutoff}


def update_prices(full: bool = False) -> dict:
    """每日更新：先從價格快取同步（預設增量，full=True 整段），再用 openapi 補最新一天（快取沒有的話）"""
    out = {"cache": sync_from_price_cache(days=200, full=full)}
    try:
        out["openapi"] = fetch_and_store_today()
    except Exception as e:
        out["openapi"] = {"error": str(e)}
    return out


def backfill(days: int = 120) -> dict:
    """
    初始化歷史價格：用 Yahoo Finance async 批次抓全市場股票近 days 天資料。
    每支股票只需 1 個 HTTP request（Yahoo 回傳完整歷史），並行度 120。
    """
    import asyncio
    import httpx as _httpx
    from pathlib import Path as _Path
    import pandas as _pd

    init_db()

    # 查已有幾天資料
    with db() as conn:
        existing_dates = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM sector_stock_daily"
        ).fetchone()[0]

    if existing_dates >= days // 2:
        log.info(f"[prices] DB 已有 {existing_dates} 天，跳過 backfill")
        return {"skipped": True, "existing_dates": existing_dates}

    # 讀 stocks.csv 取得所有股票
    try:
        import pandas as _pd
        stocks_csv = _Path(__file__).parent.parent / "stocks.csv"
        sdf = _pd.read_csv(str(stocks_csv), dtype=str, encoding="utf-8")
        stock_list = [(r["stock_id"], r.get("type", "twse")) for _, r in sdf.iterrows()]
    except Exception as e:
        log.error(f"[prices] 無法讀取 stocks.csv: {e}")
        return {"error": str(e)}

    log.info(f"[prices] 開始 Yahoo backfill：{len(stock_list)} 支股票，{days} 天")

    now_ts = int(time.time())
    p1 = now_ts - (days + 30) * 86400  # 多抓 30 天 buffer
    _UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

    async def _fetch_one(client, stock_id, mkt):
        suffixes = [".TW"] if mkt == "twse" else [".TWO", ".TW"]
        params = {"interval": "1d", "period1": p1, "period2": now_ts}
        for suffix in suffixes:
            for host in ["query2", "query1"]:
                url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
                try:
                    r = await client.get(url, params=params)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    result_list = (data.get("chart") or {}).get("result") or []
                    if not result_list:
                        continue
                    res = result_list[0]
                    quote = res["indicators"]["quote"][0]
                    ts = res.get("timestamp", [])
                    if not ts:
                        continue
                    import pandas as _pd2
                    _TW = _pd2.Timedelta(hours=8)
                    idx = (_pd2.to_datetime(ts, unit="s", utc=True) + _TW).tz_localize(None)
                    closes = quote.get("close", [])
                    opens  = quote.get("open",  [])
                    highs  = quote.get("high",  [])
                    lows   = quote.get("low",   [])
                    vols   = quote.get("volume",[])
                    rows = []
                    for i, dt in enumerate(idx):
                        try:
                            c = float(closes[i]) if closes[i] is not None else None
                        except Exception:
                            c = None
                        if not c or c <= 0:
                            continue
                        def _g(arr, j):
                            try: return float(arr[j]) if arr[j] is not None else c
                            except: return c
                        rows.append({
                            "date":     dt.strftime("%Y%m%d"),
                            "stock_id": stock_id,
                            "open":     _g(opens,  i),
                            "high":     _g(highs,  i),
                            "low":      _g(lows,   i),
                            "close":    c,
                            "volume":   _g(vols,   i),
                        })
                    return rows
                except Exception:
                    continue
        return []

    # 分批處理：每批 CHUNK_SIZE 支，立即存 DB 後釋放記憶體，防止 OOM
    CHUNK_SIZE = 300
    SEM_PER_CHUNK = 40

    async def _run_chunked():
        total = 0
        for chunk_start in range(0, len(stock_list), CHUNK_SIZE):
            chunk = stock_list[chunk_start: chunk_start + CHUNK_SIZE]
            sem = asyncio.Semaphore(SEM_PER_CHUNK)
            limits = _httpx.Limits(max_connections=60, max_keepalive_connections=30)
            timeout = _httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

            async def _fetch_with_sem(sid, mkt, _sem=sem):
                async with _sem:
                    return await _fetch_one(client, sid, mkt)

            try:
                async with _httpx.AsyncClient(
                    headers={"User-Agent": _UA, "Accept": "application/json"},
                    verify=False, timeout=timeout, limits=limits,
                    follow_redirects=True,
                ) as client:
                    tasks = [_fetch_with_sem(sid, mkt) for sid, mkt in chunk]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as chunk_e:
                log.error(f"[prices] chunk {chunk_start} fetch 失敗: {chunk_e}")
                continue

            # 立即存入 DB，再釋放記憶體
            chunk_rows = []
            for res in results:
                if isinstance(res, list):
                    chunk_rows.extend(res)
            del results

            if chunk_rows:
                by_date: dict = {}
                for row in chunk_rows:
                    by_date.setdefault(row["date"], []).append(row)
                for d, rows_d in sorted(by_date.items()):
                    total += store_prices(d, rows_d)
            del chunk_rows
            log.info(f"[prices] backfill {min(chunk_start + CHUNK_SIZE, len(stock_list))}/{len(stock_list)} 完成，累計 {total} 筆")

        return total

    # 單一 event loop，try/finally 確保一定關閉
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        total_stored = loop.run_until_complete(_run_chunked())
    except Exception as e:
        log.error(f"[prices] backfill 失敗: {e}")
        return {"error": str(e)}
    finally:
        loop.close()

    log.info(f"[prices] backfill 全部完成：{total_stored} 筆")
    return {"stored": total_stored}


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
    # PLAN-B77：以前 fetchall 一次把約 26 萬列變成 Python tuple 再轉 DataFrame（正式站尖峰 +160MB）；
    # 改成分批（每批 4 萬列）讀進 DataFrame 再接起來，記憶體尖峰只剩一批
    with db() as conn:
        parts = list(pd.read_sql_query(
            f"""SELECT date, stock_id, open, high, low, close, volume
                FROM sector_stock_daily
                WHERE stock_id IN ({placeholders})
                ORDER BY stock_id, date""",
            conn, params=stock_ids, chunksize=40000))
    if not parts:
        return {}
    df_all = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    del parts
    if df_all.empty:
        return {}
    for _c in ("open", "high", "low", "close", "volume"):       # 某一批整欄是空值時會變 object，統一成數字（跟以前一次讀一樣）
        if df_all[_c].dtype == object:
            df_all[_c] = pd.to_numeric(df_all[_c], errors="coerce")

    result = {}
    for sid, grp in df_all.groupby("stock_id"):
        grp = grp.drop(columns=["stock_id"]).reset_index(drop=True)
        grp = grp[grp["close"] > 0].copy()
        if len(grp) >= min_dates:
            result[str(sid)] = grp

    return result
