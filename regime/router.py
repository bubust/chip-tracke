"""
Regime Engine — API Routes
Sprint 4: backfill endpoint, overheating/panic in today response
"""
import logging
from datetime import date, timedelta
from fastapi import APIRouter

from .db import db, init_db
from .fetcher import (
    fetch_all, fetch_twse_margin, fetch_twse_foreign_spot,
    fetch_breadth_ad, fetch_twse_market_breadth, fetch_taifex_foreign_futures,
    fetch_mi5mins,
)
from .factor import calculate_factors, backfill_factors

log = logging.getLogger(__name__)
router = APIRouter()


def _get_overheating_today() -> dict:
    """取今日（或最近一筆）過熱/恐慌指數"""
    today = date.today().strftime("%Y-%m-%d")
    try:
        with db() as conn:
            oh_row = conn.execute(
                "SELECT value FROM market_daily WHERE series='OVERHEATING_INDEX' AND date=? LIMIT 1",
                (today,)
            ).fetchone()
            pa_row = conn.execute(
                "SELECT value FROM market_daily WHERE series='PANIC_INDEX' AND date=? LIMIT 1",
                (today,)
            ).fetchone()
            # 若今日無資料，取最近一筆
            if oh_row is None:
                oh_row = conn.execute(
                    "SELECT value FROM market_daily WHERE series='OVERHEATING_INDEX' ORDER BY date DESC LIMIT 1"
                ).fetchone()
            if pa_row is None:
                pa_row = conn.execute(
                    "SELECT value FROM market_daily WHERE series='PANIC_INDEX' ORDER BY date DESC LIMIT 1"
                ).fetchone()
        return {
            "overheating": oh_row["value"] if oh_row else None,
            "panic":       pa_row["value"] if pa_row else None,
        }
    except Exception as e:
        log.warning(f"[regime] 取過熱指數失敗: {e}")
        return {"overheating": None, "panic": None}


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
        result = dict(row)
    else:
        # 計算今日因子
        result = calculate_factors(today)

    # 附加過熱/恐慌指數
    oh = _get_overheating_today()
    result["overheating"] = oh["overheating"]
    result["panic"]       = oh["panic"]
    return result


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


@router.get("/api/regime/overheating")
def regime_overheating():
    """取最新的過熱/恐慌指數"""
    return _get_overheating_today()


@router.post("/api/regime/refresh")
def regime_refresh():
    """手動觸發資料更新 + 因子計算 + 歷史回填"""
    import threading
    def _run():
        try:
            fetch_all(days=90)
            fetch_twse_margin()
            fetch_twse_foreign_spot()
            fetch_twse_market_breadth(lookback=90)  # Sprint 3: 直接從 TWSE 抓漲跌家數
            fetch_breadth_ad(lookback=90)           # price_daily 有資料時覆蓋為精確值
            fetch_taifex_foreign_futures()
            fetch_mi5mins()                         # Sprint 4: 過熱/恐慌指數
            calculate_factors()
            # Sprint 4: 更新完後補算歷史因子
            backfill_factors(days=120)
            log.info("[regime] 更新完成（含歷史回填）")
        except Exception as e:
            log.error(f"[regime] 更新失敗: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": "已開始背景更新（含歷史回填）"}


@router.post("/api/regime/backfill")
def regime_backfill(days: int = 120):
    """手動觸發歷史因子回填"""
    import threading
    def _run():
        try:
            count = backfill_factors(days=days)
            log.info(f"[regime] 歷史回填完成: {count} 天")
        except Exception as e:
            log.error(f"[regime] 歷史回填失敗: {e}")
    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": f"已開始歷史回填（最多 {days} 天）"}
