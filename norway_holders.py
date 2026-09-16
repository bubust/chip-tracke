"""
norway_holders.py — norway.twsthr.info 千張大戶細分週資料爬蟲
資料來源：https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}
- Server-side rendered，GET 直接可拿到完整 HTML
- D1 明細表：日期、集保總張數、大股東持有張數/比例/人數、各區間人數、收盤價
快取在 chip_data/cache.db → norway_holders 表
"""
import asyncio
import re
import sqlite3
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "chip_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

NORWAY_URL = "https://norway.twsthr.info/StockHolders.aspx"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://norway.twsthr.info/",
}


# ── SQLite ─────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS norway_holders (
            stock_id      TEXT,
            date          TEXT,
            total_shares  INTEGER,
            shareholders  INTEGER,
            avg_per_person REAL,
            gt400_shares  INTEGER,
            gt400_pct     REAL,
            gt400_count   INTEGER,
            cnt400_600    INTEGER,
            cnt600_800    INTEGER,
            cnt800_1000   INTEGER,
            gt1000_count  INTEGER,
            gt1000_pct    REAL,
            close_price   REAL,
            PRIMARY KEY (stock_id, date)
        )
    """)
    c.commit()
    return c


# ── HTML Parser ────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"[,\s&nbsp;]", "", s).strip()


def _parse_details_table(html: str) -> list[dict]:
    """解析 D1 明細表，回傳清單 [{date, total_shares, ...}, ...]"""
    # 找 id='Details' 的 table
    m = re.search(r"id=['\"]Details['\"].*?</table>", html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    table_html = m.group(0)

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
    results = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        # 去 HTML tag，清空白
        vals = [re.sub(r"<[^>]+>", "", c) for c in cells]
        vals = [_clean(v) for v in vals]
        # 過濾空行 / header 行（header 含中文且沒有日期格式）
        if len(vals) < 14:
            continue
        # D1 欄位結構（去掉首尾 &nbsp; 欄後共 14 個有效欄）：
        # 0:blank 1:colorDiv 2:date(YYYYMMDD) 3:total_shares 4:shareholders
        # 5:avg_per_person 6:gt400_shares 7:gt400_pct 8:gt400_count
        # 9:cnt400_600 10:cnt600_800 11:cnt800_1000 12:gt1000_count
        # 13:gt1000_pct 14:close_price 15:blank
        date_str = vals[2]
        if not re.match(r"^\d{8}$", date_str):
            continue
        try:
            results.append({
                "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
                "total_shares":   int(vals[3].replace(",", "") or 0),
                "shareholders":   int(vals[4].replace(",", "") or 0),
                "avg_per_person": float(vals[5] or 0),
                "gt400_shares":   int(vals[6].replace(",", "") or 0),
                "gt400_pct":      float(vals[7] or 0),
                "gt400_count":    int(vals[8].replace(",", "") or 0),
                "cnt400_600":     int(vals[9].replace(",", "") or 0),
                "cnt600_800":     int(vals[10].replace(",", "") or 0),
                "cnt800_1000":    int(vals[11].replace(",", "") or 0),
                "gt1000_count":   int(vals[12].replace(",", "") or 0),
                "gt1000_pct":     float(vals[13] or 0),
                "close_price":    float(vals[14].replace(",", "") or 0),
            })
        except (ValueError, IndexError):
            continue
    return results


# ── Fetch & Cache ──────────────────────────────────────────────────────────────

async def fetch_and_cache(stock_id: str) -> list[dict]:
    """從 norway 抓資料並寫入 DB，回傳最新 20 週"""
    async with httpx.AsyncClient(headers=_HEADERS, timeout=15, follow_redirects=True) as client:
        try:
            r = await client.get(NORWAY_URL, params={"stock": stock_id})
            r.raise_for_status()
            html = r.text
        except Exception as e:
            log.warning(f"[norway] fetch {stock_id} failed: {e}")
            return []

    rows = _parse_details_table(html)
    if not rows:
        log.warning(f"[norway] {stock_id}: parse returned 0 rows")
        return []

    c = _conn()
    try:
        c.executemany("""
            INSERT OR REPLACE INTO norway_holders
            (stock_id, date, total_shares, shareholders, avg_per_person,
             gt400_shares, gt400_pct, gt400_count, cnt400_600, cnt600_800,
             cnt800_1000, gt1000_count, gt1000_pct, close_price)
            VALUES (:stock_id,:date,:total_shares,:shareholders,:avg_per_person,
             :gt400_shares,:gt400_pct,:gt400_count,:cnt400_600,:cnt600_800,
             :cnt800_1000,:gt1000_count,:gt1000_pct,:close_price)
        """, [{**row, "stock_id": stock_id} for row in rows])
        c.commit()
        log.info(f"[norway] {stock_id}: saved {len(rows)} rows")
    finally:
        c.close()

    return rows[:20]


def get_cached(stock_id: str, weeks: int = 20) -> list[dict]:
    """從 DB 讀取快取，回傳 [{date, gt1000_count, gt1000_pct, gt400_pct, close_price, ...}]"""
    try:
        c = _conn()
        rows = c.execute("""
            SELECT date, total_shares, shareholders, avg_per_person,
                   gt400_shares, gt400_pct, gt400_count,
                   cnt400_600, cnt600_800, cnt800_1000,
                   gt1000_count, gt1000_pct, close_price
            FROM norway_holders
            WHERE stock_id=?
            ORDER BY date DESC LIMIT ?
        """, (stock_id, weeks)).fetchall()
        c.close()
        return [dict(r) for r in reversed(rows)]
    except Exception as e:
        log.warning(f"[norway] get_cached {stock_id}: {e}")
        return []


def needs_refresh(stock_id: str) -> bool:
    """若快取中最新一筆超過 7 天，需要重新抓取"""
    try:
        c = _conn()
        row = c.execute(
            "SELECT MAX(date) FROM norway_holders WHERE stock_id=?", (stock_id,)
        ).fetchone()
        c.close()
        if not row or not row[0]:
            return True
        last = date.fromisoformat(row[0])
        return (date.today() - last).days >= 7
    except Exception:
        return True


async def get_history(stock_id: str) -> list[dict]:
    """主入口：有快取且不過期則直接回傳，否則重新抓取"""
    if needs_refresh(stock_id):
        rows = await fetch_and_cache(stock_id)
        if rows:
            return rows
    cached = get_cached(stock_id)
    if cached:
        return cached
    # 快取沒有 → 再試一次（避免 DB miss）
    return await fetch_and_cache(stock_id)
