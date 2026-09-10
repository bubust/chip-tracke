"""
Regime Engine — API Routes
"""
import logging
from datetime import date, timedelta
from fastapi import APIRouter

from .db import db, init_db
from .fetcher import fetch_all, fetch_twse_margin, fetch_twse_foreign_spot
from .factor import calculate_factors

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/regime/status")
def regime_status():
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM market_daily").fetchone()
        latest = conn.execute(
            "SELECT date FROM factors ORDER BY date DESC LIMIT 1"
        ).fetchone()
    return {
        "data_rows": row["c"],
        "latest_factors": latest["date"] if latest else None,
    }


@router.get("/api/regime/today")
def regime_today():
    today = date.today().strftime("%Y-%m-%d")
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM factors WHERE date=?", (today,)
        ).fetchone()
    if row:
        return dict(row)
    # 計算今日因子
    return calculate_factors(today)


@router.get("/api/regime/history")
def regime_history(days: int = 60):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM factors ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


@router.get("/api/regime/series/{series}")
def regime_series(series: str, days: int = 120):
    with db() as conn:
        rows = conn.execute("""
            SELECT date, value FROM market_daily
            WHERE series=? AND value IS NOT NULL
            ORDER BY date DESC LIMIT ?
        """, (series, days)).fetchall()
    return [{"date": r["date"], "value": r["value"]} for r in reversed(rows)]


@router.post("/api/regime/refresh")
def regime_refresh():
    """手動觸發資料更新 + 因子計算"""
    import threading
    def _run():
        try:
            fetch_all(days=90)
            fetch_twse_margin()
            fetch_twse_foreign_spot()
            calculate_factors()
            log.info("[regime] 更新完成")
        except Exception as e:
            log.error(f"[regime] 更新失敗: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": "已開始背景更新"}
