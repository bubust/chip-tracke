"""
tdcc_chip.py — 集保所千張大戶持股分級週資料
資料來源：FinMind API (TaiwanStockHolding)，全球 IP 可用，免爬蟲。
千張大戶 = 持股分級 15~17（持股 >= 1,000,000 股 ≈ >= 1,000 張）

FinMind 每週五更新，免費方案每日 600 次請求。
MA 預篩後約 100~400 支，每週只需更新一次（有快取則跳過）。
"""
import asyncio
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "chip_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

FINMIND_URL   = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"
    ".eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0"
    ".LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
)
THOUSAND_LOT_TIERS = {15, 16, 17}


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
        print(f"[FinMind] get_tdcc_data error: {e}")
        return {}


# ── FinMind API ───────────────────────────────────────────────────────────────

def _parse_rows(rows: list[dict]) -> dict[str, float]:
    """
    將 FinMind 回傳的持股分級 rows 解析成 {date_yyyymmdd: kpct}。
    rows 欄位：date(YYYY-MM-DD), HoldingSharesCount(1~17), percent(float)
    """
    from collections import defaultdict
    per_date: dict[str, float] = defaultdict(float)
    for row in rows:
        try:
            tier = int(row.get("HoldingSharesCount", 0))
        except (ValueError, TypeError):
            continue
        if tier in THOUSAND_LOT_TIERS:
            try:
                per_date[row["date"]] += float(row.get("percent", 0))
            except (ValueError, TypeError):
                pass
    # 轉成 {YYYYMMDD: round_pct}
    return {d.replace("-", ""): round(v, 2) for d, v in per_date.items()}


async def _fetch_one_finmind(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    stock_id: str,
    start_date: str,
) -> dict[str, float]:
    """
    查詢單支股票，回傳 {date_yyyymmdd: kpct}。
    失敗或無資料回傳 {}。
    """
    params = {
        "dataset":    "TaiwanStockHolding",
        "stock_id":   stock_id,
        "start_date": start_date,
        "token":      FINMIND_TOKEN,
    }
    async with sem:
        try:
            r = await client.get(FINMIND_URL, params=params)
            if r.status_code == 200:
                j = r.json()
                if j.get("status") == 200:
                    return _parse_rows(j.get("data", []))
                # rate limit / error
                msg = j.get("msg", "")
                if "limit" in msg.lower() or j.get("status") == 402:
                    print(f"[FinMind] 達到請求上限：{msg}")
            return {}
        except Exception as e:
            print(f"[FinMind] {stock_id} 失敗：{e}")
            return {}


async def _get_available_dates(start_date: str) -> list[str]:
    """
    查詢 2330 取得 FinMind 上最近可用的週次日期清單（最多 2 筆，YYYYMMDD 格式）。
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(FINMIND_URL, params={
                "dataset":    "TaiwanStockHolding",
                "stock_id":   "2330",
                "start_date": start_date,
                "token":      FINMIND_TOKEN,
            })
            rows = r.json().get("data", [])
        dates = sorted({row["date"] for row in rows}, reverse=True)[:2]
        return [d.replace("-", "") for d in dates]
    except Exception as e:
        print(f"[FinMind] 取可用日期失敗：{e}")
        return []


async def fetch_batch(stock_ids: list[str], date_str: str) -> dict[str, float]:
    """
    批次查詢多支股票，回傳 {stock_id: kpct} for 指定日期。
    """
    if not stock_ids:
        return {}

    # start_date 往前推 21 天確保涵蓋最近兩個週次
    start = (date.today() - timedelta(days=21)).strftime("%Y-%m-%d")
    sem = asyncio.Semaphore(5)   # FinMind 免費方案請謹慎控制並發
    timeout = httpx.Timeout(30.0, connect=10.0)

    print(f"[FinMind] 查詢 {len(stock_ids)} 支股票（日期 {date_str}）...")
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _fetch_one_finmind(client, sem, sid, start)
            for sid in stock_ids
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, float] = {}
    ok = 0
    for sid, per_date in zip(stock_ids, results_list):
        if isinstance(per_date, Exception) or not isinstance(per_date, dict):
            continue
        if date_str in per_date:
            results[sid] = per_date[date_str]
            ok += 1

    print(f"[FinMind] 完成：{ok}/{len(stock_ids)} 支有資料，日期 {date_str}")
    return results


async def refresh_for_stocks(stock_ids: list[str]) -> dict:
    """
    為指定股票清單取得最近兩週 FinMind 資料並寫入快取。
    - 若日期已有快取（>= min_count 筆）則跳過
    - 回傳 {date_str: count | "cached"}
    """
    if not stock_ids:
        return {}

    skip_threshold = max(10, len(stock_ids) // 2)
    start = (date.today() - timedelta(days=21)).strftime("%Y-%m-%d")

    available_dates = await _get_available_dates(start)
    if not available_dates:
        # fallback：計算最近兩個週五
        fri = date.today() - timedelta(days=(date.today().weekday() - 4) % 7)
        available_dates = [
            fri.strftime("%Y%m%d"),
            (fri - timedelta(days=7)).strftime("%Y%m%d"),
        ]
        print(f"[FinMind] 改用計算值：{available_dates}")

    print(f"[FinMind] 本次使用日期：{available_dates}")
    report = {}

    for ds in available_dates:
        if _has_date(ds, min_count=skip_threshold):
            print(f"[FinMind] {ds} 已有快取（>={skip_threshold} 筆），跳過")
            report[ds] = "cached"
            continue

        # FinMind：每支股票需一次請求，一次取多週資料
        # 所以一次 fetch_all 取所有日期，再分日儲存
        batch_by_date = await _fetch_all_dates(stock_ids, start, available_dates)
        for d2, data in batch_by_date.items():
            if data:
                _save(d2, data)
                report[d2] = len(data)
            else:
                report[d2] = 0
        break  # 已一次取完所有日期，不再重複迴圈

    return report


async def _fetch_all_dates(
    stock_ids: list[str],
    start_date: str,
    target_dates: list[str],
) -> dict[str, dict[str, float]]:
    """
    一次取多支股票多個日期的資料，回傳 {date_str: {stock_id: kpct}}。
    """
    if not stock_ids:
        return {}

    sem = asyncio.Semaphore(5)
    timeout = httpx.Timeout(30.0, connect=10.0)
    print(f"[FinMind] 批次查詢 {len(stock_ids)} 支，日期 {target_dates} ...")

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _fetch_one_finmind(client, sem, sid, start_date)
            for sid in stock_ids
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

    # 重整為 {date: {stock_id: pct}}
    by_date: dict[str, dict[str, float]] = {d: {} for d in target_dates}
    ok_total = 0
    for sid, per_date in zip(stock_ids, results_list):
        if isinstance(per_date, Exception) or not isinstance(per_date, dict):
            continue
        for ds in target_dates:
            if ds in per_date:
                by_date[ds][sid] = per_date[ds]
                ok_total += 1

    for ds in target_dates:
        print(f"[FinMind] {ds}：{len(by_date[ds])} 支有資料")
    return by_date


def get_stock_tdcc_history(stock_id: str, weeks: int = 12) -> list[dict]:
    """
    回傳單支股票最近 N 週的千張大戶資料（最新在前）。
    [{date: "YYYYMMDD", kpct: float, change: float}, ...]
    """
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
        print(f"[FinMind] get_stock_tdcc_history error: {e}")
        return []


async def refresh_tdcc() -> dict:
    """API 相容性保留（/api/tdcc/refresh 端點）"""
    return {
        "message": "TDCC 資料已改用 FinMind API，執行全市場掃描即會自動抓取",
        "skipped": True,
    }
