"""
Positioning Engine V1 — FastAPI Router
"""

import asyncio
import logging
import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter

from .db import get_conn, get_history, get_latest, get_series, init_db
from .fetcher import fetch_all
from .calculator import compute_positioning

log = logging.getLogger(__name__)
router = APIRouter()

_TELEGRAM_BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_refresh(target_date: date | None = None):
    async def _inner():
        try:
            raw = await fetch_all(target_date)
            result = compute_positioning(raw, target_date=raw.get("observation_date"))
            log.info(f"Positioning refresh done: {result.get('observation_date')}")
        except Exception as e:
            log.exception(f"Positioning refresh error: {e}")
    asyncio.run(_inner())


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/api/positioning/status")
def status():
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt, MAX(observation_date) as latest FROM positioning_daily"
    ).fetchone()
    conn.close()
    return {"count": row[0], "latest": row[1]}


@router.get("/api/positioning/today")
def today():
    conn = get_conn()
    row = get_latest(conn)
    conn.close()
    return row or {}


@router.get("/api/positioning/history")
def history(days: int = 60):
    conn = get_conn()
    rows = get_history(conn, days)
    conn.close()
    return rows


@router.get("/api/positioning/series/{column}")
def series(column: str, days: int = 250):
    allowed = {
        "foreign_futures_net_oi", "top5_net_oi", "top10_net_oi",
        "foreign_cash_net", "retail_mtx_ratio", "pcr_oi_all",
        "tx_equivalent_total_oi", "taiex_close",
        "foreign_futures_pct250", "top5_pct250", "pcr_pct250",
    }
    if column not in allowed:
        return {"error": "column not allowed"}
    conn = get_conn()
    s = get_series(conn, column, limit=days)
    conn.close()
    return [{"date": d, "value": v} for d, v in s]


@router.post("/api/positioning/refresh")
def refresh(target_date: str | None = None):
    td = None
    if target_date:
        try:
            td = date.fromisoformat(target_date)
        except Exception:
            pass
    threading.Thread(target=_run_refresh, args=(td,), daemon=True).start()
    return {"status": "started", "target_date": str(td or "today")}


@router.post("/api/positioning/backfill")
def backfill(days: int = 30):
    def _bg():
        # Re-fetch and compute for last N trading days
        td = date.today()
        count = 0
        for i in range(days * 2):  # iterate extra to skip weekends
            d = td - timedelta(days=i)
            if d.weekday() >= 5:
                continue
            if count >= days:
                break
            try:
                asyncio.run(_do_one(d))
                count += 1
            except Exception as e:
                log.warning(f"Backfill {d}: {e}")

    async def _do_one(d: date):
        raw = await fetch_all(d)
        compute_positioning(raw, target_date=raw.get("observation_date"))

    threading.Thread(target=_bg, daemon=True).start()
    return {"status": "started", "days": days}


@router.post("/api/positioning/telegram")
def send_telegram():
    conn = get_conn()
    row = get_latest(conn)
    conn.close()
    if not row:
        return {"status": "no data"}
    _send_telegram_report(row)
    return {"status": "sent"}


def _send_telegram_report(row: dict):
    if not _TELEGRAM_BOT or not _TELEGRAM_CHAT:
        log.warning("Telegram not configured, skipping report")
        return

    dt = row.get("observation_date", "N/A")
    state = row.get("positioning_state", "N/A")
    transition = row.get("positioning_transition", "N/A")
    divergence = row.get("positioning_divergence", "NONE")
    exhaustion = row.get("positioning_exhaustion", "NORMAL")
    summary = row.get("positioning_summary", "")

    def _fmt_val(v, unit="", decimals=0):
        if v is None:
            return "N/A"
        return f"{v:+.{decimals}f}{unit}" if decimals else f"{int(v):+,}{unit}"

    msg = f"""📊 *市場籌碼定位 {dt}*

🏛 *現貨法人*
外資：{_fmt_val(row.get('foreign_cash_net'), '億', 1)}（5日累計：{_fmt_val(row.get('foreign_cash_5d'), '億', 1)}）
投信：{_fmt_val(row.get('trust_cash_net'), '億', 1)}
自營：{_fmt_val(row.get('dealer_cash_net'), '億', 1)}

📈 *期貨籌碼*
外資期貨淨OI：{_fmt_val(row.get('foreign_futures_net_oi'), '口')}（Δ5D：{_fmt_val(row.get('delta_foreign_futures_5d'), '口')}）
前五大淨OI：{_fmt_val(row.get('top5_net_oi'), '口')}（Δ1D：{_fmt_val(row.get('delta_top5_1d'), '口')}）
前十大淨OI：{_fmt_val(row.get('top10_net_oi'), '口')}

⚖️ *選擇權*
PCR-OI：{_fmt_val(row.get('pcr_oi_all'), '', 1)}（{row.get('pcr_pct250', 'N/A')}th pct）
外資選擇權淨值：{_fmt_val(row.get('foreign_option_net_value'), '千元')}

🌾 *散戶*
小台散戶比（推估）：{_fmt_val(row.get('retail_mtx_ratio'), '%', 1)}（{row.get('retail_pct250', 'N/A')}th pct）

📋 *定位判斷*
狀態：{state}
趨勢：{transition}
背離：{divergence}
極端：{exhaustion}

💬 {summary}"""

    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{_TELEGRAM_BOT}/sendMessage",
            json={"chat_id": _TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")
