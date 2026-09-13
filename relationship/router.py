"""
Relationship Engine V1 — FastAPI Router
"""
import asyncio
import logging
import threading
from datetime import date, timedelta

from fastapi import APIRouter, Query

from .db import get_conn, get_history, get_events, get_date_detail, get_event_history, init_db
from .fetcher import fetch_all
from .event_engine import run_event_engine, EVENT_DEFINITIONS

log = logging.getLogger(__name__)
router = APIRouter()


def _run_refresh(days: int = 400):
    async def _inner():
        await fetch_all(days=days)
    asyncio.run(_inner())
    run_event_engine(days=min(days, 250))


@router.get("/api/relationship/status")
def status():
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt, MIN(observation_date) as earliest, MAX(observation_date) as latest "
        "FROM market_daily"
    ).fetchone()
    events_cnt = conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0]
    conn.close()
    return {"rows": row["cnt"], "earliest": row["earliest"], "latest": row["latest"], "events": events_cnt}


@router.get("/api/relationship/history")
def history(days: int = Query(90, ge=10, le=500)):
    conn = get_conn()
    rows = get_history(conn, days)
    conn.close()
    return {"days": days, "data": rows}


@router.get("/api/relationship/events")
def events(days: int = Query(90, ge=10, le=500), level: int = Query(1, ge=1, le=3)):
    conn = get_conn()
    all_events = get_events(conn, days)
    conn.close()
    filtered = [e for e in all_events if (e.get("event_level") or 1) >= level]
    return {"events": filtered}


@router.get("/api/relationship/date/{date_str}")
def date_detail(date_str: str):
    conn = get_conn()
    detail = get_date_detail(conn, date_str)
    conn.close()
    return detail


@router.get("/api/relationship/research/{event_type}")
def research(event_type: str, days: int = Query(500, ge=90, le=2000)):
    """Historical analysis of a specific event type."""
    conn = get_conn()
    rows = get_event_history(conn, event_type, days)
    conn.close()

    # Compute statistics
    r5 = [r["future_return_5d"] for r in rows if r.get("future_return_5d") is not None]
    r10 = [r["future_return_10d"] for r in rows if r.get("future_return_10d") is not None]
    r20 = [r["future_return_20d"] for r in rows if r.get("future_return_20d") is not None]

    def _stats(returns):
        if not returns:
            return None
        avg = sum(returns) / len(returns)
        win = sum(1 for r in returns if r > 0) / len(returns) * 100
        return {"avg": round(avg, 3), "win_rate": round(win, 1), "n": len(returns)}

    info = EVENT_DEFINITIONS.get(event_type, (1, event_type))
    return {
        "event_type": event_type,
        "description": info[1],
        "level": info[0],
        "total_occurrences": len(rows),
        "stats": {
            "5d": _stats(r5),
            "10d": _stats(r10),
            "20d": _stats(r20),
        },
        "occurrences": rows[:100],  # cap at 100 for response size
    }


@router.get("/api/relationship/event_types")
def event_types():
    return [{"type": k, "level": v[0], "description": v[1]} for k, v in EVENT_DEFINITIONS.items()]


@router.post("/api/relationship/refresh")
def refresh(days: int = Query(400, ge=30, le=1000)):
    threading.Thread(target=_run_refresh, args=(days,), daemon=True).start()
    return {"status": "started", "days": days}
