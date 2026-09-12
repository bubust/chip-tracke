"""
sector/router.py — FastAPI routes for 產業輪動引擎
"""
import logging
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from .db import db
from .universe import fetch_and_build_mapping, is_initialized, get_all_sectors

log = logging.getLogger(__name__)
router = APIRouter()

_engine_running = False
_engine_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sectors  — 所有產業最新狀態列表
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sectors")
def api_get_sectors(sort_by: str = Query("rank5d", description="rank5d|rank20d|rank60d|rank_change|event")):
    """
    回傳所有產業的最新狀態，按 relative_rank_5d 排序（或依 sort_by 切換）。
    """
    with db() as conn:
        # 找最新日期
        row = conn.execute(
            "SELECT MAX(observation_date) AS d FROM sector_daily"
        ).fetchone()
        if not row or not row["d"]:
            return {"date": None, "sectors": []}
        latest_date = row["d"]

        rows = conn.execute(
            """
            SELECT sd.*, sm.sector_name
            FROM sector_daily sd
            LEFT JOIN sector_master sm ON sd.sector_id = sm.sector_id
            WHERE sd.observation_date = ?
            """,
            (latest_date,),
        ).fetchall()

    sectors = [dict(r) for r in rows]

    # 排序
    if sort_by == "rank5d":
        sectors.sort(key=lambda x: (x.get("relative_rank_5d") or 9999))
    elif sort_by == "rank20d":
        sectors.sort(key=lambda x: (x.get("relative_rank_20d") or 9999))
    elif sort_by == "rank60d":
        sectors.sort(key=lambda x: (x.get("relative_rank_60d") or 9999))
    elif sort_by == "rank_change":
        # 排名改善幅度最大在前（rank_change_5d 越大越好）
        sectors.sort(key=lambda x: -(x.get("rank_change_5d") or 0))
    elif sort_by == "event":
        # 有結構事件的排前面
        def event_key(x):
            ev = x.get("structure_event")
            priority = {"BREAKOUT": 0, "FALSE_BREAKDOWN": 1, "RECLAIM": 2, "BREAKDOWN": 3, "FALSE_BREAKOUT": 4}
            return priority.get(ev, 9)
        sectors.sort(key=event_key)

    return {"date": latest_date, "total": len(sectors), "sectors": sectors}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sector/{sector_id}  — 單一產業詳細 + 歷史
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sector/{sector_id}")
def api_get_sector(sector_id: str, days: int = Query(60, ge=1, le=365)):
    """
    回傳單一產業的最新狀態 + 最近 days 天歷史。
    """
    with db() as conn:
        # 最新一筆
        latest = conn.execute(
            """
            SELECT sd.*, sm.sector_name
            FROM sector_daily sd
            LEFT JOIN sector_master sm ON sd.sector_id = sm.sector_id
            WHERE sd.sector_id = ?
            ORDER BY sd.observation_date DESC
            LIMIT 1
            """,
            (sector_id,),
        ).fetchone()

        if not latest:
            raise HTTPException(status_code=404, detail=f"找不到產業：{sector_id}")

        # 歷史資料
        history_rows = conn.execute(
            """
            SELECT observation_date, index_level, return_ew_1d,
                   return_ew_5d, return_ew_20d, return_ew_60d,
                   ma20, ma60, ma120, trend_state,
                   relative_rank_5d, relative_rank_20d,
                   breadth_up_ratio, above_ma20_ratio
            FROM sector_daily
            WHERE sector_id = ?
            ORDER BY observation_date DESC
            LIMIT ?
            """,
            (sector_id, days),
        ).fetchall()

        # 近期結構事件
        events = conn.execute(
            """
            SELECT * FROM sector_events
            WHERE sector_id = ?
            ORDER BY observation_date DESC
            LIMIT 10
            """,
            (sector_id,),
        ).fetchall()

        # 該產業股票清單
        stocks = conn.execute(
            """
            SELECT stock_id FROM stock_sector_map
            WHERE sector_id = ?
            ORDER BY stock_id
            """,
            (sector_id,),
        ).fetchall()

    return {
        "latest": dict(latest),
        "history": [dict(r) for r in reversed(history_rows)],
        "events": [dict(r) for r in events],
        "stocks": [r["stock_id"] for r in stocks],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/events  — 最近結構事件
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/events")
def api_get_events(limit: int = Query(50, ge=1, le=200)):
    """回傳最近結構事件列表"""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT se.*, sm.sector_name
            FROM sector_events se
            LEFT JOIN sector_master sm ON se.sector_id = sm.sector_id
            ORDER BY se.observation_date DESC, se.event_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"events": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/status  — 引擎狀態
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/status")
def api_get_status():
    """回傳引擎狀態：幾個產業、最後更新日、是否初始化"""
    try:
        with db() as conn:
            sector_count = conn.execute(
                "SELECT COUNT(*) FROM sector_master"
            ).fetchone()[0]

            stock_count = conn.execute(
                "SELECT COUNT(DISTINCT stock_id) FROM stock_sector_map"
            ).fetchone()[0]

            latest_date_row = conn.execute(
                "SELECT MAX(observation_date) AS d FROM sector_daily"
            ).fetchone()
            latest_date = latest_date_row["d"] if latest_date_row else None

            last_run_row = conn.execute(
                "SELECT value FROM sector_meta WHERE key='last_run'"
            ).fetchone()
            last_run = last_run_row["value"] if last_run_row else None

            event_count = conn.execute(
                "SELECT COUNT(*) FROM sector_events"
            ).fetchone()[0]

        return {
            "initialized": sector_count > 0,
            "sector_count": sector_count,
            "stock_count": stock_count,
            "latest_date": latest_date,
            "last_run": last_run,
            "event_count": event_count,
            "engine_running": _engine_running,
        }
    except Exception as e:
        return {
            "initialized": False,
            "sector_count": 0,
            "stock_count": 0,
            "latest_date": None,
            "last_run": None,
            "event_count": 0,
            "engine_running": _engine_running,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/refresh  — 觸發重新計算
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/refresh")
def api_refresh(background_tasks: BackgroundTasks, days_back: int = Query(120, ge=1, le=365)):
    """觸發產業引擎重新計算（背景執行）"""
    global _engine_running
    with _engine_lock:
        if _engine_running:
            return {"ok": False, "message": "引擎計算中，請稍候"}
        _engine_running = True

    def _run():
        global _engine_running
        try:
            from .engine import run_sector_engine
            run_sector_engine(days_back=days_back)
        except Exception as e:
            log.error(f"[sector] 引擎錯誤: {e}", exc_info=True)
        finally:
            _engine_running = False

    background_tasks.add_task(_run)
    return {"ok": True, "message": f"已開始計算（days_back={days_back}）"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/init  — 觸發 sector mapping 初始化
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/init")
def api_init(background_tasks: BackgroundTasks):
    """觸發 FinMind 抓取 + sector mapping 建立（背景執行）"""

    def _init():
        try:
            counts = fetch_and_build_mapping()
            log.info(f"[sector] 初始化完成：{len(counts)} 個產業")
        except Exception as e:
            log.error(f"[sector] 初始化失敗: {e}", exc_info=True)

    background_tasks.add_task(_init)
    return {"ok": True, "message": "已開始從 FinMind 建立產業對照表"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sectors/history  — 多產業歷史指數（供 chart 用）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sectors/history")
def api_sectors_history(
    sector_ids: str = Query("", description="逗號分隔的 sector_id"),
    days: int = Query(60, ge=1, le=365),
):
    """
    回傳多個產業的歷史指數（供前端畫多線圖）。
    """
    if not sector_ids.strip():
        return {"series": {}}

    ids = [s.strip() for s in sector_ids.split(",") if s.strip()]
    result = {}
    with db() as conn:
        for sid in ids:
            rows = conn.execute(
                """
                SELECT observation_date, index_level, return_ew_1d,
                       trend_state, relative_rank_5d
                FROM sector_daily
                WHERE sector_id = ?
                ORDER BY observation_date DESC
                LIMIT ?
                """,
                (sid, days),
            ).fetchall()
            result[sid] = [dict(r) for r in reversed(rows)]

    return {"series": result}
