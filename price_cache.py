"""
price_cache.py - 全市場日線價格快取
- Cloud Run: 使用 openapi.twse.com.tw（不受 IP 封鎖，只有最新一天）
- 本機回填: 使用 rwd STOCK_DAY_ALL（可抓指定日期歷史資料）
- 資料存 SQLite + 同步 Supabase（跨重啟持久化）
"""
import sqlite3
import asyncio
import httpx
from datetime import date, datetime, timedelta
import pandas as pd
from chip_tracker_v2 import DB_PATH, to_twse_date, last_n_trading_dates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.twse.com.tw/",
}

# ── DB init ────────────────────────────────────────────────────────────────

def init_price_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_daily (
            date      TEXT NOT NULL,
            stock_id  TEXT NOT NULL,
            open      REAL,
            high      REAL,
            low       REAL,
            close     REAL,
            volume    REAL,
            name      TEXT,
            PRIMARY KEY (date, stock_id)
        );
        CREATE INDEX IF NOT EXISTS idx_price_stock ON price_daily(stock_id, date);
    """)
    conn.commit()
    conn.close()

def _to_float(val):
    try:
        v = str(val).replace(',', '').strip()
        if v in ('', '--', 'X', '+', '-', 'N/A'):
            return None
        return float(v)
    except Exception:
        return None

def _roc_to_twse(roc_date: str) -> str:
    """民國日期 '1150831' → TWSE格式 '20260831'"""
    try:
        year = int(roc_date[:3]) + 1911
        return f"{year}{roc_date[3:]}"
    except Exception:
        return roc_date

# ── OpenAPI fetch（Cloud Run 用，只有最新一天）────────────────────────────

async def fetch_price_latest_openapi(client: httpx.AsyncClient) -> tuple[str, list]:
    """從 openapi.twse.com.tw 取得最新一天全市場收盤資料（Cloud Run 不受封鎖）"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        r = await client.get(url, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return "", []
        data = r.json()
        if not isinstance(data, list) or not data:
            return "", []
        # Date 格式是民國 e.g. '1150831'
        dt_roc = data[0].get("Date", "")
        dt_str = _roc_to_twse(dt_roc)
        if not dt_str or len(dt_str) != 8:
            return "", []
        parsed = []
        for row in data:
            sid = str(row.get("Code", "")).strip()
            if not sid or not sid[:4].isdigit():
                continue
            name = str(row.get("Name", "")).strip()
            close_p = _to_float(row.get("ClosingPrice"))
            if close_p is None or close_p <= 0:
                continue
            open_p   = _to_float(row.get("OpeningPrice"))
            high_p   = _to_float(row.get("HighestPrice"))
            low_p    = _to_float(row.get("LowestPrice"))
            vol_raw  = _to_float(row.get("TradeVolume"))
            volume_lots = round(vol_raw / 1000) if vol_raw else 0
            parsed.append({
                "date": dt_str, "stock_id": sid, "name": name,
                "open": open_p, "high": high_p, "low": low_p,
                "close": close_p, "volume": volume_lots,
            })
        print(f"[PRICE] openapi 取得 {dt_str}：{len(parsed)} 支")
        return dt_str, parsed
    except Exception as e:
        print(f"[PRICE] openapi fetch failed: {type(e).__name__}: {str(e)[:80]}")
        return "", []

async def fetch_price_latest_tpex(client: httpx.AsyncClient) -> tuple[str, list]:
    """從 tpex.org.tw 取得最新一天全市場上櫃收盤資料"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    try:
        r = await client.get(url, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return "", []
        data = r.json()
        if not isinstance(data, list) or not data:
            return "", []
        dt_roc = data[0].get("Date", "")
        dt_str = _roc_to_twse(dt_roc)
        if not dt_str or len(dt_str) != 8:
            return "", []
        parsed = []
        for row in data:
            sid = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not sid or not sid[:4].isdigit():
                continue
            name = str(row.get("CompanyName", "")).strip()
            close_p = _to_float(row.get("Close"))
            if close_p is None or close_p <= 0:
                continue
            open_p  = _to_float(row.get("Open"))
            high_p  = _to_float(row.get("High"))
            low_p   = _to_float(row.get("Low"))
            vol_raw = _to_float(row.get("TradingShares"))
            volume_lots = round(vol_raw / 1000) if vol_raw else 0
            parsed.append({
                "date": dt_str, "stock_id": sid, "name": name,
                "open": open_p, "high": high_p, "low": low_p,
                "close": close_p, "volume": volume_lots,
            })
        print(f"[PRICE] tpex openapi 取得 {dt_str}：{len(parsed)} 支")
        return dt_str, parsed
    except Exception as e:
        print(f"[PRICE] tpex fetch failed: {type(e).__name__}: {str(e)[:80]}")
        return "", []

# ── rwd fetch（本機回填用，Cloud Run 可能被擋）──────────────────────────

_RWD_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"

def _parse_twse_rwd(text: str, fallback_dt: str = "") -> tuple[str, list]:
    """
    解析 TWSE rwd STOCK_DAY_ALL 回應，同時支援：
    - CSV（2026-10 起 response=json 也回 text/csv）：表頭 `日期,證券代號,證券名稱,成交股數,...`
    - 舊 JSON：{"stat":"OK","date":"20261001","data":[[代號,名稱,股數,金額,開,高,低,收,...]]}
    以欄名定位欄位；只保留出現最多的日期。失敗回 ("", [])。
    """
    import csv, io, json, re
    from collections import Counter
    try:
        text = (text or "").lstrip("﻿").strip()
        if not text:
            return "", []
        rows = []  # (dt_str, sid, name, shares, open, high, low, close)
        if text.startswith("{"):
            data = json.loads(text)
            if data.get("stat") != "OK":
                return "", []
            dt_str = str(data.get("date") or fallback_dt)
            for row in data.get("data", []):
                if len(row) >= 9:
                    rows.append((dt_str, row[0], row[1], row[2], row[5], row[6], row[7], row[8]))
        else:
            lines = list(csv.reader(io.StringIO(text)))
            hdr_i = next((i for i, r in enumerate(lines)
                          if any(c.strip() == "證券代號" for c in r)), None)
            if hdr_i is None:
                print(f"[PRICE] rwd CSV 找不到表頭: {text[:80]!r}")
                return "", []
            hdr = [c.strip().lstrip("﻿") for c in lines[hdr_i]]
            names = ("證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價")
            if any(n not in hdr for n in names):
                print(f"[PRICE] rwd CSV 欄位不足: {hdr}")
                return "", []
            idx = [hdr.index(n) for n in names]
            date_col = hdr.index("日期") if "日期" in hdr else None
            title_dt = ""
            if date_col is None:
                # 舊版格式：日期在表頭前的標題列，如「115年10月01日 ...」
                m = re.search(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日",
                              " ".join(",".join(r) for r in lines[:hdr_i]))
                if m:
                    title_dt = f"{int(m.group(1)) + 1911}{int(m.group(2)):02d}{int(m.group(3)):02d}"
                title_dt = title_dt or fallback_dt
                if not title_dt:
                    print("[PRICE] rwd CSV 找不到日期")
                    return "", []
            need = max(idx + ([date_col] if date_col is not None else []))
            for r in lines[hdr_i + 1:]:
                if len(r) <= need:
                    continue
                dt_str = _roc_to_twse(r[date_col].strip()) if date_col is not None else title_dt
                rows.append((dt_str, *(r[i] for i in idx)))
        valid_dates = [d for d, *_ in rows if d and len(d) == 8 and d.isdigit()]
        if not valid_dates:
            return "", []
        dt_str = Counter(valid_dates).most_common(1)[0][0]
        parsed, skipped = [], 0
        for d, sid, name, shares, o, h, l, c in rows:
            sid = str(sid).strip()
            close_p = _to_float(c)
            if d != dt_str or not sid[:4].isdigit() or close_p is None or close_p <= 0:
                skipped += 1
                continue
            volume_shares = _to_float(shares)
            parsed.append({
                "date": dt_str, "stock_id": sid, "name": str(name).strip(),
                "open": _to_float(o), "high": _to_float(h),
                "low": _to_float(l), "close": close_p,
                "volume": round(volume_shares / 1000) if volume_shares else 0,
            })
        print(f"[PRICE] rwd 解析 {dt_str}：{len(parsed)} 支（跳過 {skipped}）")
        return dt_str, parsed
    except Exception as e:
        print(f"[PRICE] rwd 解析失敗: {type(e).__name__}: {str(e)[:60]} | {str(text)[:80]!r}")
        return "", []

async def fetch_price_day_rwd(client: httpx.AsyncClient, dt: date) -> tuple[str, list]:
    """從 TWSE rwd STOCK_DAY_ALL 取得指定日期（本機回填用）"""
    dt_str = to_twse_date(dt)
    try:
        r = await client.get(_RWD_URL, params={"date": dt_str, "response": "json"},
                             headers=HEADERS, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return dt_str, []
        got_dt, parsed = _parse_twse_rwd(r.text, fallback_dt=dt_str)
        if got_dt != dt_str:  # 休市日 rwd 可能回最近交易日，不可存成指定日期
            return dt_str, []
        return dt_str, parsed
    except Exception as e:
        print(f"[PRICE] rwd fetch {dt_str} failed: {type(e).__name__}: {str(e)[:60]}")
        return dt_str, []

async def fetch_price_latest_rwd(client: httpx.AsyncClient) -> tuple[str, list]:
    """從 TWSE rwd STOCK_DAY_ALL 取得最新一天（收盤後通常比 openapi 早更新）"""
    try:
        r = await client.get(_RWD_URL, params={"response": "json"},
                             headers=HEADERS, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            print(f"[PRICE] rwd latest HTTP {r.status_code}")
            return "", []
        return _parse_twse_rwd(r.text)
    except Exception as e:
        print(f"[PRICE] rwd latest failed: {type(e).__name__}: {str(e)[:60]}")
        return "", []

# ── 儲存 ──────────────────────────────────────────────────────────────────

def get_cached_dates() -> set:
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT DISTINCT date FROM price_daily").fetchall()
    conn.close()
    return {r[0] for r in rows}

def save_price_day(dt_str: str, records: list):
    if not records:
        return
    conn = sqlite3.connect(str(DB_PATH))
    conn.executemany(
        "INSERT OR REPLACE INTO price_daily (date,stock_id,name,open,high,low,close,volume) "
        "VALUES (:date,:stock_id,:name,:open,:high,:low,:close,:volume)",
        records
    )
    conn.commit()
    conn.close()
    try:
        import supabase_store as sb
        sb.pd_upsert(records)
    except Exception as e:
        print(f"[PRICE] Supabase sync {dt_str} failed: {e}")

# ── Supabase 冷啟動恢復 ──────────────────────────────────────────────────

async def restore_from_supabase() -> int:
    import supabase_store as sb
    if not sb._enabled():
        return 0
    total = sb.pd_count()
    if total == 0:
        return 0
    print(f"[PRICE] Supabase 有 {total} 筆，開始並行恢復...")
    init_price_db()
    PAGE = 1000
    pages_count = (total + PAGE - 1) // PAGE
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(10)

    async def fetch_page(offset):
        async with sem:
            return await loop.run_in_executor(None, sb.pd_restore_page, PAGE, offset)

    results = await asyncio.gather(
        *[fetch_page(i * PAGE) for i in range(pages_count)],
        return_exceptions=True,
    )
    all_records = []
    for res in results:
        if isinstance(res, list):
            all_records.extend(res)
    if all_records:
        conn = sqlite3.connect(str(DB_PATH))
        conn.executemany(
            "INSERT OR REPLACE INTO price_daily (date,stock_id,name,open,high,low,close,volume) "
            "VALUES (:date,:stock_id,:name,:open,:high,:low,:close,:volume)",
            all_records
        )
        conn.commit()
        conn.close()
    print(f"[PRICE] 恢復完成：{len(all_records)} 筆")
    return len(all_records)

# ── FinMind 回填（歷史資料，Cloud Run 可用）──────────────────────────────

async def backfill_from_finmind(days: int = 260, concurrency: int = 20) -> dict:
    """
    用 FinMind API 批量抓取所有上市股票歷史資料（Cloud Run 可用，不受 TWSE IP 限制）
    每次最多 concurrency 支同時請求，避免 FinMind 限流。
    注意：不再用全局 cached_dates 跳過日期，改由 SQLite INSERT OR REPLACE 處理重複。
    這樣 Supabase 還原只有 2 支股票時不會讓新股票的近期資料被誤跳。
    """
    import os
    from datetime import timedelta
    token = os.getenv("FINMIND_TOKEN", "")
    if not token:
        return {"error": "未設定 FINMIND_TOKEN 環境變數"}

    init_price_db()

    # 股票清單：永遠從 stocks.csv 取（上市 + 上櫃共 2119 支）
    # 不用 DB 的最新日（OpenAPI 只有上市 ~1700，上櫃 ~900 支會漏）
    try:
        import os as _os2, pandas as _pd2
        _csv = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), "stocks.csv")
        _sdf = _pd2.read_csv(_csv, dtype=str)
        stock_ids = _sdf["stock_id"].dropna().tolist()
        print(f"[PRICE] stocks.csv 讀取 {len(stock_ids)} 支")
    except Exception as _ce:
        print(f"[PRICE] stocks.csv 讀取失敗：{_ce}，改用 DB 清單")
        conn = sqlite3.connect(str(DB_PATH))
        latest_date = conn.execute("SELECT MAX(date) FROM price_daily").fetchone()[0]
        stock_ids = []
        if latest_date:
            rows = conn.execute(
                "SELECT DISTINCT stock_id FROM price_daily WHERE date=?", (latest_date,)
            ).fetchall()
            stock_ids = [r[0] for r in rows]
        conn.close()
        if not stock_ids:
            return {"error": "無法取得股票清單"}

    # 計算起始日期
    start_date = (date.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")  # 多抓一些保險

    def _fmt_date(d: str) -> str:
        """FinMind YYYY-MM-DD → TWSE YYYYMMDD"""
        return d.replace("-", "")

    def _fetch_stock_sync(sid: str) -> list:
        """同步抓取單支股票歷史資料（在 executor 中執行）"""
        import urllib.request, urllib.parse, json as _json
        params = urllib.parse.urlencode({
            "dataset": "TaiwanStockPrice",
            "data_id": sid,
            "start_date": start_date,
            "token": token,
        })
        url = f"https://api.finmindtrade.com/api/v4/data?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read())
            if data.get("status") != 200:
                return []
            records = []
            for row in data.get("data", []):
                dt_str = _fmt_date(row["date"])
                # 不做全局 cached_dates 跳過（避免 Supabase 只有 2 支時近期日期被誤跳）
                # SQLite 用 INSERT OR REPLACE 處理重複
                vol_lots = round(row.get("Trading_Volume", 0) / 1000)
                records.append({
                    "date": dt_str, "stock_id": sid,
                    "name": "",
                    "open": row.get("open"), "high": row.get("max"),
                    "low": row.get("min"), "close": row.get("close"),
                    "volume": vol_lots,
                })
            return records
        except Exception:
            return []

    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_event_loop()
    total_stocks = len(stock_ids)

    # 建立 stock_id → name 對照表（從 price_daily 現有資料）
    conn = sqlite3.connect(str(DB_PATH))
    name_rows = conn.execute(
        "SELECT DISTINCT stock_id, name FROM price_daily WHERE name != '' AND name IS NOT NULL"
    ).fetchall()
    conn.close()
    name_map = {r[0]: r[1] for r in name_rows}

    async def fetch_one(sid: str):
        async with sem:
            records = await loop.run_in_executor(None, _fetch_stock_sync, sid)
            if not records:
                return 0
            # 補股名
            nm = name_map.get(sid, "")
            if nm:
                for r in records:
                    if not r["name"]:
                        r["name"] = nm
            # SQLite 寫入
            conn2 = sqlite3.connect(str(DB_PATH))
            conn2.executemany(
                "INSERT OR REPLACE INTO price_daily "
                "(date,stock_id,name,open,high,low,close,volume) "
                "VALUES (:date,:stock_id,:name,:open,:high,:low,:close,:volume)",
                records
            )
            conn2.commit()
            conn2.close()
            # 每支股票立即同步 Supabase，避免累積 55 萬筆導致 OOM
            try:
                import supabase_store as _sb
                if _sb._enabled():
                    _sb.pd_upsert(records)
            except Exception:
                pass
            return len(records)

    tasks = [fetch_one(sid) for sid in stock_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    new_rows = sum(r for r in results if isinstance(r, int))
    print(f"[PRICE] FinMind 回填完成：{new_rows} 筆新資料，共 {total_stocks} 支股票")

    return {
        "new_rows": new_rows,
        "stocks": total_stocks,
        "cached_days": len(get_cached_dates()),
    }

# ── 更新（Cloud Run：只抓最新日；本機：可抓歷史）────────────────────────

async def update_price_cache(days: int = 260, local_mode: bool = False) -> dict:
    """
    補充缺少的交易日價格資料。
    - local_mode=False（Cloud Run）：用 openapi 抓最新一天
    - local_mode=True（本機）：用 rwd 補全歷史所有缺少的日期
    """
    init_price_db()
    cached = get_cached_dates()

    if not local_mode:
        # Cloud Run 模式：同時抓 TWSE openapi + TWSE rwd + TPEX 最新一天
        # openapi 常延遲到隔天才更新，rwd 收盤後即有資料 → 取日期較新的那份
        async with httpx.AsyncClient() as client:
            (oa_dt, oa_records), (rwd_dt, rwd_records), (tpex_dt, tpex_records) = await asyncio.gather(
                fetch_price_latest_openapi(client),
                fetch_price_latest_rwd(client),
                fetch_price_latest_tpex(client),
            )
        # TWSE 來源選擇：筆數 >= 500 才算有效；日期大者勝；同日取 openapi；落選者不寫入
        twse_dt, twse_records = "", []
        for d, recs in ((oa_dt, oa_records), (rwd_dt, rwd_records)):
            if d and len(recs) >= 500 and d > twse_dt:
                twse_dt, twse_records = d, recs
        print(f"[PRICE] TWSE openapi={oa_dt or '-'}({len(oa_records)}) rwd={rwd_dt or '-'}({len(rwd_records)})"
              f" → 採用 {twse_dt or '無'}；TPEX={tpex_dt or '-'}({len(tpex_records)})")
        if not twse_records and not tpex_records:
            return {"updated": 0, "cached_days": len(cached), "error": "openapi 無資料"}
        # TWSE / TPEX 各自以自己的日期寫入（save_price_day 用 INSERT OR REPLACE，重複執行安全）
        updated = 0
        if twse_records:
            save_price_day(twse_dt, twse_records)
            cached.add(twse_dt)
            updated += 1
            print(f"[PRICE] 儲存 TWSE {twse_dt}: {len(twse_records)} 支")
        if tpex_records:
            # 同日時去除重複 stock_id（TWSE 優先）
            twse_ids = {r["stock_id"] for r in twse_records} if tpex_dt == twse_dt else set()
            tpex_only = [r for r in tpex_records if r["stock_id"] not in twse_ids]
            save_price_day(tpex_dt, tpex_only)
            cached.add(tpex_dt)
            updated += 1
            print(f"[PRICE] 儲存 TPEX {tpex_dt}: {len(tpex_only)} 支")
        return {"updated": updated, "cached_days": len(cached),
                "latest": max(twse_dt, tpex_dt), "twse_latest": twse_dt, "tpex_latest": tpex_dt}
    else:
        # 本機模式：補全所有缺少的歷史日期
        today = date.today()
        needed = last_n_trading_dates(days, today)
        missing = [d for d in needed if to_twse_date(d) not in cached]
        if not missing:
            return {"updated": 0, "cached_days": len(cached), "missing": 0}
        print(f"[PRICE] 本機回填 {len(missing)} 個交易日（由舊到新）...")
        updated = 0
        async with httpx.AsyncClient() as client:
            for dt in reversed(missing):  # 從舊到新
                dt_str, records = await fetch_price_day_rwd(client, dt)
                if records:
                    save_price_day(dt_str, records)
                    updated += 1
                    print(f"[PRICE] {dt_str} -> {len(records)} 支")
                else:
                    print(f"[PRICE] {dt_str} -> 無資料（可能休市或被限流）")
                await asyncio.sleep(1.5)  # 本機回填用較長間隔避免被擋
        return {"updated": updated, "cached_days": len(get_cached_dates()), "missing": len(missing)}

# ── 查詢 API ──────────────────────────────────────────────────────────────

def get_all_prices(min_days: int = 20) -> dict:
    """回傳 {stock_id: pd.DataFrame(date,open,high,low,close,volume,name)}"""
    init_price_db()
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql(
        "SELECT date,stock_id,name,open,high,low,close,volume FROM price_daily ORDER BY stock_id,date",
        conn
    )
    conn.close()
    if df.empty:
        return {}
    result = {}
    for sid, g in df.groupby('stock_id'):
        g = g.sort_values('date').reset_index(drop=True)
        if len(g) >= min_days:
            result[sid] = g
    return result

def get_latest_prices() -> dict:
    """回傳最新一天所有股票的 {stock_id: {name,open,high,low,close,volume,date}}"""
    init_price_db()
    conn = sqlite3.connect(str(DB_PATH))
    latest_date = conn.execute("SELECT MAX(date) FROM price_daily").fetchone()[0]
    if not latest_date:
        conn.close()
        return {}
    rows = conn.execute(
        "SELECT stock_id,name,open,high,low,close,volume FROM price_daily WHERE date=?",
        (latest_date,)
    ).fetchall()
    conn.close()
    result = {}
    for row in rows:
        result[row[0]] = {
            "name": row[1], "open": row[2], "high": row[3],
            "low": row[4], "close": row[5], "volume": row[6], "date": latest_date
        }
    return result

def get_stock_ohlcv(stock_id: str, days: int = 60) -> pd.DataFrame:
    """回傳單支股票最近 days 天的 OHLCV DataFrame（從 price_daily 快取讀取）。"""
    try:
        init_price_db()
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM price_daily "
            "WHERE stock_id=? ORDER BY date DESC LIMIT ?",
            (stock_id, days)
        ).fetchall()
        conn.close()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df = df.sort_values("date").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()

def save_stock_ohlcv(stock_id: str, df: pd.DataFrame):
    """將 Yahoo 抓回的 DataFrame 存入 price_daily 快取（供下次 Yahoo 失敗時使用）。
    只補沒有的日子（INSERT OR IGNORE）：已經有的是官方行情（不還原），Yahoo 的舊價格常是還原價
    （配股／減資，有的連 split 事件都沒列，例 0050 一拆四），不能蓋掉（B53）。"""
    try:
        if df is None or df.empty:
            return
        init_price_db()
        # 盤中（台灣平日 09:00~13:35）今日 K 棒未完成，不落地；否則收盤後掃描會把它當完整日線
        tw_now = datetime.utcnow() + timedelta(hours=8)
        skip_date = (tw_now.strftime("%Y%m%d")
                     if tw_now.weekday() < 5 and (9, 0) <= (tw_now.hour, tw_now.minute) < (13, 35)
                     else "")
        records = []
        for _, row in df.iterrows():
            date_val = str(row.get("date", ""))
            if not date_val:
                continue
            # Yahoo 日期是 YYYY-MM-DD，轉為 YYYYMMDD 格式
            date_str = date_val.replace("-", "") if "-" in str(date_val) else str(date_val)
            if date_str == skip_date:
                continue
            if not float(row.get("volume") or 0):   # 量 0＝沒成交或休市日（颱風假 Yahoo 會塞假的 K 棒），官方也不會有這根
                continue
            records.append({
                "date": date_str, "stock_id": stock_id, "name": "",
                "open": float(row.get("open") or 0) or None,
                "high": float(row.get("high") or 0) or None,
                "low":  float(row.get("low") or 0) or None,
                "close": float(row.get("close") or 0) or None,
                "volume": float(row.get("volume") or 0) or None,
            })
        if records:
            conn = sqlite3.connect(str(DB_PATH))
            conn.executemany(
                "INSERT OR IGNORE INTO price_daily (date,stock_id,name,open,high,low,close,volume) "
                "VALUES (:date,:stock_id,:name,:open,:high,:low,:close,:volume)",
                records
            )
            conn.commit()
            conn.close()
            # 注意：掃描時不在此同步 Supabase（12 thread 同時打會 OOM）
            # Supabase 備份由 backfill_from_finmind 負責
    except Exception as e:
        print(f"[PRICE] save_stock_ohlcv {stock_id}: {e}")

def get_stocks_with_history(min_days: int = 100) -> int:
    """回傳 price_daily 中有 >= min_days 筆資料的股票數（判斷 cache 是否夠熱）"""
    init_price_db()
    conn = sqlite3.connect(str(DB_PATH))
    result = conn.execute(
        "SELECT COUNT(*) FROM (SELECT stock_id FROM price_daily GROUP BY stock_id HAVING COUNT(*) >= ?)",
        (min_days,)
    ).fetchone()[0]
    conn.close()
    return result

def get_stale_stocks(days_threshold: int = 60) -> set:
    """回傳最後成交日距今超過 days_threshold 天的股票 ID 集合（殭屍股：下市、長期停牌）。
    price_daily.date 格式為 YYYYMMDD（舊版誤用 YYYY-MM-DD 比較，字串永遠比門檻大，一支都抓不到）。
    以快取裡最新的市場日期為基準而非今天：快取本身沒更新時不會把全市場誤判成殭屍股；
    快取最新日期落後今天超過 10 天時直接不過濾。"""
    from datetime import date, datetime, timedelta
    init_price_db()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        latest = conn.execute("SELECT MAX(date) FROM price_daily").fetchone()[0]
        if not latest or len(str(latest)) != 8:
            return set()
        latest_d = datetime.strptime(str(latest), "%Y%m%d").date()
        if (date.today() - latest_d).days > 10:
            print(f"[PRICE] get_stale_stocks: 快取最新只到 {latest}，不做殭屍過濾")
            return set()
        threshold = (latest_d - timedelta(days=days_threshold)).strftime("%Y%m%d")
        rows = conn.execute(
            "SELECT stock_id FROM price_daily GROUP BY stock_id HAVING MAX(date) < ?",
            (threshold,)
        ).fetchall()
        return {r[0] for r in rows}
    except Exception as e:
        print(f"[PRICE] get_stale_stocks: {e}")
        return set()
    finally:
        conn.close()


def get_price_cache_status() -> dict:
    init_price_db()
    conn = sqlite3.connect(str(DB_PATH))
    count = conn.execute("SELECT COUNT(DISTINCT date) FROM price_daily").fetchone()[0]
    min_date = conn.execute("SELECT MIN(date) FROM price_daily").fetchone()[0]
    max_date = conn.execute("SELECT MAX(date) FROM price_daily").fetchone()[0]
    stock_count = conn.execute(
        "SELECT COUNT(DISTINCT stock_id) FROM price_daily WHERE date=?", (max_date or '',)
    ).fetchone()[0]
    conn.close()
    return {"days_cached": count, "from": min_date, "to": max_date, "stocks": stock_count}
