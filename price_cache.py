"""
price_cache.py - 全市場日線價格快取
- Cloud Run: 使用 openapi.twse.com.tw（不受 IP 封鎖，只有最新一天）
- 本機回填: 使用 rwd STOCK_DAY_ALL（可抓指定日期歷史資料）
- 資料存 SQLite + 同步 Supabase（跨重啟持久化）
"""
import sqlite3
import asyncio
import httpx
from datetime import date, datetime
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

# ── rwd fetch（本機回填用，Cloud Run 可能被擋）──────────────────────────

async def fetch_price_day_rwd(client: httpx.AsyncClient, dt: date) -> tuple[str, list]:
    """從 TWSE rwd STOCK_DAY_ALL 取得指定日期（本機回填用）"""
    dt_str = to_twse_date(dt)
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
    try:
        r = await client.get(url, params={"date": dt_str, "response": "json"},
                             headers=HEADERS, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return dt_str, []
        data = r.json()
        if data.get("stat") != "OK":
            return dt_str, []
        rows = data.get("data", [])
        parsed = []
        for row in rows:
            if len(row) < 9:
                continue
            sid = str(row[0]).strip()
            if not sid or not sid[:4].isdigit():
                continue
            close_p = _to_float(row[8])
            if close_p is None or close_p <= 0:
                continue
            volume_shares = _to_float(row[2])
            parsed.append({
                "date": dt_str, "stock_id": sid, "name": str(row[1]).strip(),
                "open": _to_float(row[5]), "high": _to_float(row[6]),
                "low": _to_float(row[7]), "close": close_p,
                "volume": round(volume_shares / 1000) if volume_shares else 0,
            })
        return dt_str, parsed
    except Exception as e:
        print(f"[PRICE] rwd fetch {dt_str} failed: {type(e).__name__}: {str(e)[:60]}")
        return dt_str, []

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

async def backfill_from_finmind(days: int = 260, concurrency: int = 8) -> dict:
    """
    用 FinMind API 批量抓取所有上市股票歷史資料（Cloud Run 可用，不受 TWSE IP 限制）
    每次最多 concurrency 支同時請求，避免 FinMind 限流。
    """
    import os
    from datetime import timedelta
    token = os.getenv("FINMIND_TOKEN", "")
    if not token:
        return {"error": "未設定 FINMIND_TOKEN 環境變數"}

    init_price_db()
    cached_dates = get_cached_dates()

    # 取得股票代號清單（從已有的最新一天資料；若無則先抓 TWSE openapi）
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
        # 先用 OpenAPI 抓今日資料取得股票清單
        async with httpx.AsyncClient() as client:
            dt_str, records = await fetch_price_latest_openapi(client)
        if records:
            save_price_day(dt_str, records)
            stock_ids = [r["stock_id"] for r in records]
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
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read())
            if data.get("status") != 200:
                return []
            records = []
            for row in data.get("data", []):
                dt_str = _fmt_date(row["date"])
                if dt_str in cached_dates:
                    continue
                vol_lots = round(row.get("Trading_Volume", 0) / 1000)
                records.append({
                    "date": dt_str, "stock_id": sid,
                    "name": "",  # FinMind 不含股名，由 OpenAPI 資料補
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
    all_new_records: list = []  # 收集本次新增的所有記錄，一起同步 Supabase

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
            all_new_records.extend(records)
            return len(records)

    tasks = [fetch_one(sid) for sid in stock_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    new_rows = sum(r for r in results if isinstance(r, int))
    print(f"[PRICE] FinMind 回填完成：{new_rows} 筆新資料，共 {total_stocks} 支股票")

    # 只上傳本次新增的資料到 Supabase（不重傳舊資料）
    try:
        import supabase_store as sb
        if sb._enabled() and all_new_records:
            print(f"[PRICE] 同步 {len(all_new_records)} 筆新資料到 Supabase...")
            sb.pd_upsert(all_new_records)
            print(f"[PRICE] Supabase 同步完成")
    except Exception as e:
        print(f"[PRICE] Supabase 同步失敗: {e}")

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
        # Cloud Run 模式：只抓最新一天
        async with httpx.AsyncClient() as client:
            dt_str, records = await fetch_price_latest_openapi(client)
        if not dt_str:
            return {"updated": 0, "cached_days": len(cached), "error": "openapi 無資料"}
        if dt_str in cached:
            return {"updated": 0, "cached_days": len(cached), "message": f"{dt_str} 已有資料"}
        if records:
            save_price_day(dt_str, records)
            cached.add(dt_str)
            print(f"[PRICE] 儲存 {dt_str}: {len(records)} 支")
            return {"updated": 1, "cached_days": len(cached), "latest": dt_str}
        return {"updated": 0, "cached_days": len(cached), "error": "openapi 回傳空資料"}
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
