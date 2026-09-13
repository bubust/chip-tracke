"""
Event Engine — generates market relationship events from daily data.
Events are based on price, OI, futures, and positioning data.
"""
import json
import logging
from .db import get_conn, upsert_event

log = logging.getLogger(__name__)

EVENT_DEFINITIONS = {
    # Level 1: basic structure
    "PRICE_FUTURES_ALIGNED":         (1, "價格與期貨同步"),
    "PRICE_FUTURES_DIVERGENCE_BULL": (2, "期貨相對強（多頭背離）"),
    "PRICE_FUTURES_DIVERGENCE_BEAR": (2, "期貨相對弱（空頭背離）"),
    "PRICE_OI_UP_BUILD":             (1, "上漲增倉"),
    "PRICE_OI_UP_COVERING":          (1, "上漲減倉（可能空單回補）"),
    "PRICE_OI_DOWN_BUILD":           (1, "下跌增倉"),
    "PRICE_OI_DOWN_LIQUIDATION":     (1, "下跌減倉（可能多單退出）"),
    # Level 2: notable
    "PRICE_POSITIONING_DIVERGENCE":  (2, "價格與法人籌碼背離"),
    "FOREIGN_FUTURES_IMPROVING":     (2, "外資期貨部位連續改善"),
    "FOREIGN_FUTURES_DETERIORATING": (2, "外資期貨部位連續惡化"),
    "LARGE_TRADER_BUILDING":         (2, "大額交易人增加部位"),
    "LARGE_TRADER_REDUCING":         (2, "大額交易人減少部位"),
    # Level 3: high importance
    "BULLISH_CONFIRMATION":          (3, "多頭籌碼確認"),
    "BEARISH_CONFIRMATION":          (3, "空頭籌碼確認"),
    "BEARISH_PRESSURE_WEAKENING":    (3, "空方壓力減弱"),
    "POTENTIAL_BEARISH_EXHAUSTION":  (3, "可能空頭耗竭"),
    "POTENTIAL_BULLISH_EXHAUSTION":  (3, "可能多頭過熱"),
}


def _safe(rows: list, col: str, idx: int, default=None):
    try:
        return rows[idx].get(col, default)
    except Exception:
        return default


def run_event_engine(days: int = 120):
    """Compute events for recent days based on market_daily + positioning_daily data."""
    conn = get_conn()

    # Load market_daily
    mrows = conn.execute(
        "SELECT * FROM market_daily ORDER BY observation_date ASC LIMIT ?",
        (days + 10,)
    ).fetchall()
    mrows = [dict(r) for r in mrows]

    # Load positioning_daily (from positioning.db, different DB)
    pos_map: dict = {}
    try:
        from positioning.db import get_conn as pos_conn
        pc = pos_conn()
        prows = pc.execute(
            "SELECT observation_date, foreign_futures_net_oi, "
            "delta_foreign_futures_1d, delta_foreign_futures_5d, "
            "top5_net_oi, delta_top5_1d, delta_top5_5d, "
            "foreign_cash_net, foreign_cash_5d, "
            "retail_mtx_ratio, retail_pct250, "
            "positioning_state, positioning_exhaustion "
            "FROM positioning_daily ORDER BY observation_date ASC"
        ).fetchall()
        pc.close()
        pos_map = {r["observation_date"]: dict(r) for r in prows}
    except Exception as e:
        log.warning(f"[event_engine] positioning data unavailable: {e}")

    events_generated = 0

    for i, row in enumerate(mrows[-days:]):
        dt = row["observation_date"]
        taiex_ret = row.get("taiex_return_1d")
        tx_rel = row.get("tx_relative_return")
        oi_chg = row.get("oi_change_1d")
        pos = pos_map.get(dt, {})

        trigger = {}

        # ── OI state ──
        if taiex_ret is not None and oi_chg is not None:
            if taiex_ret > 0 and oi_chg > 0:
                oi_state = "PRICE_UP_OI_UP"
            elif taiex_ret > 0 and oi_chg < 0:
                oi_state = "PRICE_UP_OI_DOWN"
            elif taiex_ret < 0 and oi_chg > 0:
                oi_state = "PRICE_DOWN_OI_UP"
            else:
                oi_state = "PRICE_DOWN_OI_DOWN"
            conn.execute(
                "UPDATE market_daily SET oi_state=? WHERE observation_date=?",
                (oi_state, dt)
            )
            # OI events
            if oi_state in EVENT_DEFINITIONS:
                lvl, desc = EVENT_DEFINITIONS[oi_state]
                trigger = {"taiex_ret": taiex_ret, "oi_chg": oi_chg}
                upsert_event(conn, dt, oi_state, lvl, desc, trigger)
                events_generated += 1

        # ── Price vs Futures alignment ──
        if taiex_ret is not None and tx_rel is not None:
            if taiex_ret > 0 and tx_rel > 0.1:
                upsert_event(conn, dt, "PRICE_FUTURES_DIVERGENCE_BULL", 2,
                    "期貨相對強（多頭背離）",
                    {"taiex_ret": taiex_ret, "tx_rel": tx_rel})
                events_generated += 1
            elif taiex_ret < 0 and tx_rel < -0.1:
                upsert_event(conn, dt, "PRICE_FUTURES_DIVERGENCE_BEAR", 2,
                    "期貨相對弱（空頭背離）",
                    {"taiex_ret": taiex_ret, "tx_rel": tx_rel})
                events_generated += 1
            elif abs(tx_rel) <= 0.1:
                upsert_event(conn, dt, "PRICE_FUTURES_ALIGNED", 1,
                    "價格與期貨方向一致",
                    {"taiex_ret": taiex_ret, "tx_rel": tx_rel})
                events_generated += 1

        # ── Positioning-based events (if data available) ──
        if pos:
            ff_net = pos.get("foreign_futures_net_oi")
            ff_d1 = pos.get("delta_foreign_futures_1d")
            ff_d5 = pos.get("delta_foreign_futures_5d")
            t5_net = pos.get("top5_net_oi")
            t5_d1 = pos.get("delta_top5_1d")
            cash_5d = pos.get("foreign_cash_5d")
            state = pos.get("positioning_state", "")
            exhaustion = pos.get("positioning_exhaustion", "")

            # Foreign futures trend
            if ff_d5 is not None and ff_d5 > 2000:
                upsert_event(conn, dt, "FOREIGN_FUTURES_IMPROVING", 2,
                    f"外資期貨部位5日改善 {ff_d5:+.0f}口",
                    {"ff_net": ff_net, "ff_d5": ff_d5})
                events_generated += 1
            elif ff_d5 is not None and ff_d5 < -2000:
                upsert_event(conn, dt, "FOREIGN_FUTURES_DETERIORATING", 2,
                    f"外資期貨部位5日惡化 {ff_d5:+.0f}口",
                    {"ff_net": ff_net, "ff_d5": ff_d5})
                events_generated += 1

            # Price vs Positioning divergence
            if taiex_ret is not None:
                if taiex_ret > 0.3 and cash_5d is not None and cash_5d < -50 and ff_d5 is not None and ff_d5 < -1000:
                    upsert_event(conn, dt, "PRICE_POSITIONING_DIVERGENCE", 2,
                        "價格上漲但法人籌碼惡化",
                        {"taiex_ret": taiex_ret, "cash_5d": cash_5d, "ff_d5": ff_d5})
                    events_generated += 1
                elif taiex_ret < -0.3 and cash_5d is not None and cash_5d > 50 and ff_d5 is not None and ff_d5 > 1000:
                    upsert_event(conn, dt, "PRICE_POSITIONING_DIVERGENCE", 2,
                        "價格下跌但法人籌碼改善",
                        {"taiex_ret": taiex_ret, "cash_5d": cash_5d, "ff_d5": ff_d5})
                    events_generated += 1

            # High-level state events
            if state == "BULLISH_CONFIRMATION":
                upsert_event(conn, dt, "BULLISH_CONFIRMATION", 3,
                    "多頭籌碼全面確認",
                    {"state": state, "ff_net": ff_net, "t5_net": t5_net})
                events_generated += 1
            elif state == "BEARISH_CONFIRMATION":
                upsert_event(conn, dt, "BEARISH_CONFIRMATION", 3,
                    "空頭籌碼全面確認",
                    {"state": state, "ff_net": ff_net, "t5_net": t5_net})
                events_generated += 1
            elif state == "BEARISH_EXHAUSTION":
                upsert_event(conn, dt, "POTENTIAL_BEARISH_EXHAUSTION", 3,
                    "空頭可能進入耗竭",
                    {"state": state, "exhaustion": exhaustion})
                events_generated += 1

    # Update forward returns for past events
    _update_forward_returns(conn, mrows)

    conn.commit()
    conn.close()
    log.info(f"[event_engine] generated {events_generated} events")
    return events_generated


def _update_forward_returns(conn, mrows: list[dict]):
    """Update future_return_5d/10d/20d for events where we now have the data."""
    close_map = {r["observation_date"]: r.get("taiex_close") for r in mrows}
    dates_sorted = sorted(close_map.keys())

    events = conn.execute(
        "SELECT id, observation_date FROM market_events "
        "WHERE future_return_5d IS NULL"
    ).fetchall()

    for ev in events:
        dt = ev["observation_date"]
        base = close_map.get(dt)
        if base is None:
            continue

        def _fwd(n):
            idx = dates_sorted.index(dt) if dt in dates_sorted else -1
            if idx < 0 or idx + n >= len(dates_sorted):
                return None
            fwd_dt = dates_sorted[idx + n]
            fwd_close = close_map.get(fwd_dt)
            if fwd_close and base:
                return round((fwd_close - base) / base * 100, 4)
            return None

        r5 = _fwd(5)
        r10 = _fwd(10)
        r20 = _fwd(20)

        if r5 is not None or r10 is not None:
            conn.execute(
                "UPDATE market_events SET future_return_5d=?, future_return_10d=?, future_return_20d=? WHERE id=?",
                (r5, r10, r20, ev["id"])
            )
