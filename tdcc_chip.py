"""
tdcc_chip.py — 集保所千張大戶持股分級週資料
資料來源：TDCC 官方 OpenAPI（https://openapi.tdcc.com.tw/v1/opendata/1-5）
- 無 IP 限制，免費，不需 token，Render（美國 IP）可正常使用
- 一次下載全市場所有股票（~9.7MB，約 68,000 筆）
千張大戶 = 持股分級 15~17（持股 >= 1,000,000 股 ≈ >= 1,000 張）
"""
import asyncio
import sqlite3
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "chip_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

TDCC_OPENAPI = "https://openapi.tdcc.com.tw/v1/opendata/1-5"


# ── SQLite ────────────────────────────────────────────────────────────────────

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


def _has_date(date_str: str, min_count: int = 10) -> bool:
    try:
        c = _conn()
        n = c.execute(
            "SELECT COUNT(*) FROM tdcc_holding WHERE date=?", (date_str,)
        ).fetchone()[0]
        c.close()
        return n >= min_count
    except Exception:
        return False


def _save(date_str: str, data: dict):
    if not data:
        return
    c = _conn()
    c.executemany(
        "INSERT OR REPLACE INTO tdcc_holding (stock_id, date, kpct) VALUES (?,?,?)",
        [(sid, date_str, pct) for sid, pct in data.items()]
    )
    c.commit()
    c.close()


def get_tdcc_data() -> dict:
    """
    回傳 {stock_id: {current_pct, prev_pct, change, date, consec_up}}
    從 SQLite 讀最近三週；資料不足時回傳 {}。
    """
    try:
        c = _conn()
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT date FROM tdcc_holding ORDER BY date DESC LIMIT 3"
        ).fetchall()]
        if not dates:
            c.close()
            return {}
        cur_date = dates[0]
        prev_date = dates[1] if len(dates) >= 2 else cur_date
        cur  = {r["stock_id"]: r["kpct"] for r in c.execute(
            "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (cur_date,)
        ).fetchall()}
        prev = {r["stock_id"]: r["kpct"] for r in c.execute(
            "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (prev_date,)
        ).fetchall()}
        prev2 = {}
        if len(dates) >= 3:
            prev2_date = dates[2]
            prev2 = {r["stock_id"]: r["kpct"] for r in c.execute(
                "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (prev2_date,)
            ).fetchall()}
        c.close()

        result = {}
        for sid, cpct in cur.items():
            ppct  = prev.get(sid, cpct)
            pp2ct = prev2.get(sid, ppct)
            consec = 0
            if cpct > ppct:
                consec = 1
                if ppct > pp2ct:
                    consec = 2
            result[sid] = {
                "current_pct": cpct,
                "prev_pct":    ppct,
                "change":      round(cpct - ppct, 2),
                "date":        cur_date,
                "consec_up":   consec,
            }
        return result
    except Exception as e:
        print(f"[TDCC] get_tdcc_data error: {e}")
        return {}


def get_stock_tdcc_history(stock_id: str, weeks: int = 12) -> list[dict]:
    """回傳單支股票最近 N 週的千張大戶資料（最新在前）。"""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT date, kpct FROM tdcc_holding WHERE stock_id=? ORDER BY date DESC LIMIT ?",
            (stock_id, weeks)
        ).fetchall()
        c.close()
        result = []
        for i, r in enumerate(rows):
            prev_kpct = rows[i + 1]["kpct"] if i + 1 < len(rows) else r["kpct"]
            result.append({
                "date":   r["date"],
                "kpct":   r["kpct"],
                "change": round(r["kpct"] - prev_kpct, 2),
            })
        return result
    except Exception as e:
        print(f"[TDCC] get_stock_tdcc_history error: {e}")
        return []


# ── TDCC 官方 OpenAPI ─────────────────────────────────────────────────────────

def _parse_openapi_rows(rows: list[dict]) -> tuple[str, dict[str, float]]:
    """
    解析 TDCC OpenAPI 回傳資料，計算每支股票的千張大戶持股比例。
    - 千張大戶 = 持股分級 15~17
    - 注意：第一個 key 的 JSON 原始值帶有 BOM（\ufeff），httpx 解析後 key 名稱含中文即可正常匹配
    - 股票代號有尾部空格，需 .strip()
    回傳 (date_str, {stock_id: kpct})
    """
    if not rows:
        return "", {}

    # 動態定位欄位 key（避免硬寫 BOM 問題）
    first = rows[0]
    keys = list(first.keys())
    sid_key  = next(k for k in keys if "代號" in k)
    tier_key = next(k for k in keys if "分級" in k)
    pct_key  = next(k for k in keys if "%" in k)
    date_key = next(k for k in keys if "日期" in k)

    date_str = rows[0][date_key].strip()

    holdings: dict[str, float] = {}
    for row in rows:
        try:
            tier = int(row[tier_key])
        except (ValueError, KeyError):
            continue
        if tier >= 15:
            sid = row[sid_key].strip()
            try:
                holdings[sid] = holdings.get(sid, 0.0) + float(row[pct_key])
            except (ValueError, KeyError):
                pass

    result = {sid: round(pct, 2) for sid, pct in holdings.items() if pct > 0}
    return date_str, result


async def refresh_for_stocks(stock_ids: list[str] = None) -> dict:
    """
    從 TDCC 官方 OpenAPI 下載全市場資料，存入 SQLite。
    - 無 IP 限制，Render（美國 IP）可正常使用
    - stock_ids 參數保留相容性，但實際下載全市場所有股票
    - 若該週已有快取（>= 10 筆）則跳過
    """
    timeout = httpx.Timeout(60.0, connect=15.0)

    try:
        print("[TDCC] 從官方 OpenAPI 下載全市場資料（~9.7MB）...")
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(TDCC_OPENAPI)
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        print(f"[TDCC] 下載失敗：{e}")
        return {"error": str(e)}

    date_str, data = _parse_openapi_rows(rows)
    if not date_str or not data:
        return {"error": "資料解析失敗"}

    if _has_date(date_str, min_count=10):
        print(f"[TDCC] {date_str} 已有快取，跳過")
        return {date_str: "cached"}

    _save(date_str, data)
    print(f"[TDCC] {date_str} 完成：{len(data)} 支股票")
    return {date_str: len(data)}


async def refresh_tdcc() -> dict:
    """API 相容性保留（/api/tdcc/refresh 端點）"""
    return await refresh_for_stocks()
