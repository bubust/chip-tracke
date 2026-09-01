"""
price_cache.py - 全市場日線價格快取
使用 TWSE STOCK_DAY_ALL endpoint（每日一個 API call），存 SQLite
"""
import sqlite3
import asyncio
import httpx
from datetime import date
import pandas as pd
from chip_tracker_v2 import DB_PATH, is_trading_day, to_twse_date, last_n_trading_dates

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.twse.com.tw/",
}

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

async def fetch_price_day(client: httpx.AsyncClient, dt: date):
    """從 TWSE STOCK_DAY_ALL 取得指定日期所有上市股票日線"""
    dt_str = to_twse_date(dt)
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
    try:
        r = await client.get(url, params={"date": dt_str, "response": "json"},
                             headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return dt_str, []
        data = r.json()
        if data.get("stat") != "OK":
            return dt_str, []
        rows = data.get("data", [])
        # Fields: 0=代號 1=名稱 2=成交股數 3=成交筆數 4=成交金額 5=開盤 6=最高 7=最低 8=收盤 9=漲跌符號 10=漲跌價差
        parsed = []
        for row in rows:
            if len(row) < 9:
                continue
            sid = str(row[0]).strip()
            if not sid or not sid[:4].isdigit():
                continue
            name = str(row[1]).strip()
            volume_shares = _to_float(row[2])
            open_p  = _to_float(row[5])
            high_p  = _to_float(row[6])
            low_p   = _to_float(row[7])
            close_p = _to_float(row[8])
            if close_p is None or close_p <= 0:
                continue
            volume_lots = round(volume_shares / 1000) if volume_shares else 0
            parsed.append({
                "date": dt_str, "stock_id": sid, "name": name,
                "open": open_p, "high": high_p, "low": low_p,
                "close": close_p, "volume": volume_lots,
            })
        return dt_str, parsed
    except Exception as e:
        print(f"[PRICE] fetch {to_twse_date(dt)} failed: {type(e).__name__}: {str(e)[:60]}")
        return to_twse_date(dt), []

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
    # 同步到 Supabase（持久化）
    try:
        import supabase_store as sb
        sb.pd_upsert(records)
    except Exception as e:
        print(f"[PRICE] Supabase sync {dt_str} failed: {e}")


async def restore_from_supabase() -> int:
    """從 Supabase 並行讀取 price_daily 到本機 SQLite（冷啟動恢復用）"""
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

async def update_price_cache(days: int = 260) -> dict:
    """補充缺少的交易日價格資料"""
    init_price_db()
    today = date.today()
    needed = last_n_trading_dates(days, today)
    cached = get_cached_dates()
    missing = [d for d in needed if to_twse_date(d) not in cached]
    if not missing:
        return {"updated": 0, "cached_days": len(cached), "missing": 0}
    print(f"[PRICE] 補充 {len(missing)} 個交易日...")
    updated = 0
    async with httpx.AsyncClient() as client:
        for dt in missing:
            dt_str, records = await fetch_price_day(client, dt)
            if records:
                save_price_day(dt_str, records)
                updated += 1
                print(f"[PRICE] {dt_str} -> {len(records)} 支")
            await asyncio.sleep(0.4)
    return {"updated": updated, "cached_days": len(get_cached_dates()), "missing": len(missing)}

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
