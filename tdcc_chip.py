"""
tdcc_chip.py — 集保所千張大戶持股分級週資料
資料來源：TDCC 官方 OpenAPI（https://openapi.tdcc.com.tw/v1/opendata/1-5）
- 無 IP 限制，免費，不需 token，Render（美國 IP）可正常使用
- 一次下載全市場所有股票（~9.7MB，約 68,000 筆）
千張大戶 = 持股分級 15（持股 > 1,000,000 股＝1,000 張以上）÷ 分級 17（合計）

2026-10-04 實測 OpenAPI 1-5 的分級：1~15 是持股級距、16 是「差異數調整」、17 是「合計」
（例：2330 分級 1~15 加總 − 分級 16 = 分級 17 = 25,932,370,067 股；千張大戶 = 21,984,287,365 ÷ 合計 = 84.77%，
 跟官方「占集保庫存數比例%」欄一致）。
舊版把 15、16、17 都當大戶、分母又把 17（合計）再加一次 → 舊值 =（大戶＋合計）÷（2×合計），
例 2330 會算成 92.39%；本機 tdcc_local 舊版把 15~17 的 % 欄相加 → 多 100%。
_fix_old_kpct() 會把資料庫裡的舊值一次換算回正確值（只跑一次）。
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
    c.execute("CREATE TABLE IF NOT EXISTS tdcc_meta (key TEXT PRIMARY KEY, value TEXT)")
    c.commit()
    _fix_old_kpct(c)
    return c


_fixed = False


def fix_value(old: float) -> float:
    """舊公式的值換回正確的千張大戶 %：
    - 本機匯入（15~17 的 % 相加，多了合計 100%）→ 舊值 > 100：減 100
    - OpenAPI 舊公式（大戶＋合計）÷（2×合計）→ 舊值必在 50~100：× 2 − 100"""
    if old is None:
        return old
    if old > 100:
        return round(old - 100, 2)
    if old >= 50:
        return round(old * 2 - 100, 2)
    return old


def _fix_old_kpct(c):
    """資料庫裡修正前存的舊值，一次換算回正確值（tdcc_meta 記錄已做過）"""
    global _fixed
    if _fixed:
        return
    try:
        if not c.execute("SELECT 1 FROM tdcc_meta WHERE key='kpct_fix_v1'").fetchone():
            rows = c.execute("SELECT stock_id, date, kpct FROM tdcc_holding").fetchall()
            c.executemany("UPDATE tdcc_holding SET kpct=? WHERE stock_id=? AND date=?",
                          [(fix_value(r[2]), r[0], r[1]) for r in rows if r[2] is not None])
            c.execute("INSERT OR REPLACE INTO tdcc_meta(key, value) VALUES ('kpct_fix_v1', ?)", (str(len(rows)),))
            c.commit()
            print(f"[TDCC] 千張大戶舊值已換算修正：{len(rows)} 筆")
        _fixed = True
    except Exception as e:
        print(f"[TDCC] 舊值修正失敗：{e}")


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
    - 千張大戶 = 持股分級 15（> 1,000,000 股）的股數 ÷ 分級 17（合計）的股數 × 100
    - 分級 16 是「差異數調整」、17 是「合計」，都不是大戶；沒有 17 時分母用 1~15 加總 − 16
    - 股票代號有尾部空格，需 .strip()
    回傳 (date_str, {stock_id: kpct})
    """
    if not rows:
        return "", {}

    # 動態定位欄位 key（避免硬寫 BOM 問題）
    first = rows[0]
    keys = list(first.keys())
    sid_key   = next(k for k in keys if "代號" in k)
    tier_key  = next(k for k in keys if "分級" in k)
    share_key = next(k for k in keys if "股數" in k)
    date_key  = next(k for k in keys if "日期" in k)

    date_str = rows[0][date_key].strip()

    tiers: dict[str, dict[int, int]] = {}
    for row in rows:
        sid = row[sid_key].strip()
        try:
            shares = int(str(row[share_key]).replace(",", ""))
            tier   = int(row[tier_key])
        except (ValueError, KeyError):
            continue
        tiers.setdefault(sid, {})[tier] = shares

    result = {}
    for sid, t in tiers.items():
        total = t.get(17) or (sum(v for k, v in t.items() if 1 <= k <= 15) - t.get(16, 0))
        if total > 0 and 15 in t:
            result[sid] = round(t[15] / total * 100, 2)
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

    _save(date_str, data)          # 同一週重抓也覆蓋（確保是正確公式算的值）
    print(f"[TDCC] {date_str} 完成：{len(data)} 支股票")
    return {date_str: len(data)}


async def refresh_tdcc() -> dict:
    """API 相容性保留（/api/tdcc/refresh 端點）"""
    return await refresh_for_stocks()
