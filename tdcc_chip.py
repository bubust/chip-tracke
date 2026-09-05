"""
tdcc_chip.py — 集保所千張大戶持股分級週資料
每週六更新，透過 TDCC Open Data API 抓取全市場資料。
千張大戶 = 持股分級 15~17（持股 ≥ 1,000,000 股 ≈ ≥ 1,000 張）
"""
import asyncio
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "chip_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

TDCC_URL = "https://openapi.tdcc.com.tw/v1/openData/1"
THOUSAND_LOT_TIERS = {15, 16, 17}
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS tdcc_holding (
            stock_id TEXT,
            date     TEXT,
            kpct     REAL,
            PRIMARY KEY (stock_id, date)
        )
    """)
    c.commit()
    return c


def _last_saturday(d: date = None) -> date:
    """回傳最近的週六（含今天若為週六）"""
    d = d or date.today()
    return d - timedelta(days=(d.weekday() - 5) % 7)


def _has_date(date_str: str, min_count: int = 50) -> bool:
    try:
        c = _conn()
        n = c.execute(
            "SELECT COUNT(*) FROM tdcc_holding WHERE date=?", (date_str,)
        ).fetchone()[0]
        c.close()
        return n >= min_count
    except Exception:
        return False


def get_tdcc_data() -> dict:
    """
    回傳 {stock_id: {current_pct, prev_pct, change, date}}
    從 SQLite 讀最近兩週；資料不足時回傳 {}。
    """
    try:
        c = _conn()
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT date FROM tdcc_holding ORDER BY date DESC LIMIT 2"
        ).fetchall()]
        if len(dates) < 2:
            c.close()
            return {}
        cur_date, prev_date = dates[0], dates[1]
        cur  = {r["stock_id"]: r["kpct"] for r in c.execute(
            "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (cur_date,)
        ).fetchall()}
        prev = {r["stock_id"]: r["kpct"] for r in c.execute(
            "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (prev_date,)
        ).fetchall()}
        c.close()
        result = {}
        for sid, cpct in cur.items():
            ppct = prev.get(sid, cpct)
            result[sid] = {
                "current_pct": cpct,
                "prev_pct":    ppct,
                "change":      round(cpct - ppct, 2),
                "date":        cur_date,
            }
        return result
    except Exception as e:
        print(f"[TDCC] get_tdcc_data error: {e}")
        return {}


def _parse_rows(rows: list, target_date: str) -> dict:
    """解析 TDCC API 回傳的 rows，累加千張大戶比例，回傳 {stock_id: pct}"""
    stock_tiers: dict = {}
    for row in rows:
        if isinstance(row, dict):
            row_date = str(row.get("資料日期", "")).strip()
            if row_date and row_date != target_date:
                continue
            sid      = str(row.get("證券代號", "")).strip()
            tier_raw = row.get("持股分級", 0)
            pct_raw  = row.get("占集保庫存數比例", "0")
        elif isinstance(row, list) and len(row) >= 6:
            row_date = str(row[0]).strip()
            if row_date and row_date != target_date:
                continue
            sid      = str(row[1]).strip()
            tier_raw = row[3]
            pct_raw  = row[6] if len(row) > 6 else row[5]
        else:
            continue

        if not sid:
            continue
        try:
            tier = int(str(tier_raw).strip())
            pct  = float(str(pct_raw).replace("%", "").strip())
        except Exception:
            continue

        if tier in THOUSAND_LOT_TIERS:
            stock_tiers[sid] = stock_tiers.get(sid, 0.0) + pct

    return {sid: round(v, 2) for sid, v in stock_tiers.items()}


async def _fetch_week(sat: date) -> dict:
    """抓取指定週六全市場千張大戶持股比例，回傳 {stock_id: pct}"""
    date_str = sat.strftime("%Y%m%d")
    headers = {"User-Agent": _UA}

    async with httpx.AsyncClient(timeout=120.0, verify=False, follow_redirects=True) as client:
        # 先嘗試帶 date filter，再嘗試不帶 filter
        param_sets = [
            {"$filter": f"資料日期 eq '{date_str}'", "$format": "json", "$top": 200000},
            {"$format": "json", "$top": 200000},
        ]
        for params in param_sets:
            try:
                r = await client.get(TDCC_URL, params=params, headers=headers)
                if r.status_code != 200:
                    continue
                body = r.json()
                if isinstance(body, dict):
                    rows = body.get("value", body.get("data", []))
                elif isinstance(body, list):
                    rows = body
                else:
                    continue

                result = _parse_rows(rows, date_str)
                if result:
                    print(f"[TDCC] {date_str}: 取得 {len(result)} 支千張大戶資料")
                    return result
            except Exception as e:
                print(f"[TDCC] fetch attempt error ({date_str}): {e}")
                continue

    print(f"[TDCC] {date_str}: 無法取得資料")
    return {}


def _save(date_str: str, data: dict):
    c = _conn()
    c.executemany(
        "INSERT OR REPLACE INTO tdcc_holding (stock_id, date, kpct) VALUES (?,?,?)",
        [(sid, date_str, pct) for sid, pct in data.items()]
    )
    c.commit()
    c.close()


async def refresh_tdcc() -> dict:
    """
    更新最近兩週 TDCC 資料（已有資料跳過），回傳 {date_str: count}。
    在 Render 啟動後或手動呼叫 /api/tdcc/refresh 時執行。
    """
    today   = date.today()
    sat     = _last_saturday(today)
    prev    = sat - timedelta(days=7)
    report  = {}
    for s in [sat, prev]:
        ds = s.strftime("%Y%m%d")
        if _has_date(ds):
            print(f"[TDCC] {ds} 已有資料，跳過")
            report[ds] = "cached"
            continue
        data = await _fetch_week(s)
        if data:
            _save(ds, data)
            report[ds] = len(data)
        else:
            report[ds] = 0
    return report
