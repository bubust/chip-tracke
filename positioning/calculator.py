"""
Positioning Engine V1 — Calculator
Computes derived indicators, states, transitions, divergences, and exhaustion.
"""

import logging
from datetime import date, datetime
from statistics import mean, stdev

from .db import get_conn, upsert_positioning, get_series, get_history

log = logging.getLogger(__name__)


# ── Rolling statistics ────────────────────────────────────────────────────────

def _rolling_percentile(values: list[float], current: float) -> float | None:
    """Rank of current value in the history (0-100)."""
    if not values or len(values) < 5:
        return None
    below = sum(1 for v in values if v <= current)
    return round(below / len(values) * 100, 1)


def _delta(series: list[tuple], lag: int) -> float | None:
    """series is [(date_str, value), ...] ordered oldest→newest."""
    if len(series) < lag + 1:
        return None
    curr = series[-1][1]
    prev = series[-(lag + 1)][1]
    if curr is None or prev is None:
        return None
    return round(curr - prev, 2)


def _sum_last(series: list[tuple], n: int) -> float | None:
    vals = [v for _, v in series[-n:] if v is not None]
    return round(sum(vals), 2) if vals else None


# ── Level classifier ──────────────────────────────────────────────────────────

def _level(value: float | None, pct: float | None) -> str:
    """Classify a value into BEARISH / NEUTRAL / BULLISH based on percentile."""
    if value is None:
        return "UNKNOWN"
    if pct is None:
        return "POSITIVE" if value >= 0 else "NEGATIVE"
    if pct >= 75:
        return "BULLISH"
    elif pct <= 25:
        return "BEARISH"
    return "NEUTRAL"


def _direction(delta1d: float | None, delta5d: float | None) -> str:
    if delta1d is None and delta5d is None:
        return "STABLE"
    d = delta5d if delta5d is not None else delta1d
    if abs(d) < 0.5:
        return "STABLE"
    if d > 0:
        return "IMPROVING" if d < 5000 else "RAPIDLY_IMPROVING"
    return "WEAKENING" if d > -5000 else "RAPIDLY_WEAKENING"


def _transition(delta1d: float | None, delta3d: float | None,
                delta5d: float | None, delta10d: float | None) -> str:
    """Determine positioning transition state."""
    deltas = [d for d in [delta1d, delta3d, delta5d, delta10d] if d is not None]
    if not deltas:
        return "STABLE"
    avg = mean(deltas)
    if len(deltas) >= 2:
        recent = mean(deltas[:2])  # shorter term
    else:
        recent = deltas[0]

    if avg > 2000 and recent > 1000:
        return "RAPIDLY_IMPROVING"
    if avg > 500:
        return "IMPROVING"
    if avg < -2000 and recent < -1000:
        return "RAPIDLY_WEAKENING"
    if avg < -500:
        return "WEAKENING"
    # Check for reversal: direction flipped recently
    if len(deltas) >= 3:
        if deltas[0] > 0 and deltas[-1] < 0:
            return "REVERSING_BULLISH"
        if deltas[0] < 0 and deltas[-1] > 0:
            return "REVERSING_BEARISH"
    return "STABLE"


# ── State determination ───────────────────────────────────────────────────────

def _positioning_state(
    foreign_futures_net: float | None,
    foreign_futures_delta5d: float | None,
    top5_net: int | None,
    top5_delta5d: int | None,
    foreign_cash_5d: float | None,
    retail_ratio: float | None,
    retail_pct: float | None,
    pcr_pct: float | None,
    total_oi_delta1d: float | None,
    price_delta5d: float | None,
) -> str:
    """
    Determine the primary positioning state.
    Returns one of: BULLISH_CONFIRMATION, BULLISH_DIVERGENCE,
    BEARISH_CONFIRMATION, BEARISH_EXHAUSTION, SHORT_COVERING,
    LONG_LIQUIDATION, POSITIONING_NEUTRAL
    """
    price_up = price_delta5d is not None and price_delta5d > 0
    price_down = price_delta5d is not None and price_delta5d < 0

    ff_net = foreign_futures_net or 0
    ff_improving = foreign_futures_delta5d is not None and foreign_futures_delta5d > 0
    ff_deteriorating = foreign_futures_delta5d is not None and foreign_futures_delta5d < 0

    t5_net = top5_net or 0
    t5_improving = top5_delta5d is not None and top5_delta5d > 0
    t5_deteriorating = top5_delta5d is not None and top5_delta5d < 0

    cash_improving = foreign_cash_5d is not None and foreign_cash_5d > 0

    retail_extreme_long = retail_pct is not None and retail_pct > 80
    retail_extreme_short = retail_pct is not None and retail_pct < 20

    pcr_extreme_high = pcr_pct is not None and pcr_pct > 80
    pcr_extreme_low = pcr_pct is not None and pcr_pct < 20

    oi_falling = total_oi_delta1d is not None and total_oi_delta1d < -1000

    # SHORT_COVERING: price up, futures rapidly improving, OI falling
    if price_up and ff_improving and (ff_net < 0) and oi_falling:
        return "SHORT_COVERING"

    # LONG_LIQUIDATION: price down, futures deteriorating, OI falling
    if price_down and ff_deteriorating and (ff_net > 0) and oi_falling:
        return "LONG_LIQUIDATION"

    # BEARISH_EXHAUSTION: price down + retail extreme short + PCR extreme
    if price_down and retail_extreme_short and pcr_extreme_high and ff_improving:
        return "BEARISH_EXHAUSTION"

    # BULLISH_CONFIRMATION
    if price_up and cash_improving and ff_improving and t5_improving and not retail_extreme_long:
        return "BULLISH_CONFIRMATION"

    # BEARISH_CONFIRMATION
    if price_down and not cash_improving and ff_deteriorating and t5_deteriorating and not retail_extreme_short:
        return "BEARISH_CONFIRMATION"

    # BULLISH_DIVERGENCE: price up but futures/top5 not supporting
    if price_up and (ff_deteriorating or t5_deteriorating):
        return "BULLISH_DIVERGENCE"

    return "POSITIONING_NEUTRAL"


# ── Divergence engine ─────────────────────────────────────────────────────────

def _divergences(
    price_delta5d: float | None,
    foreign_cash_5d: float | None,
    ff_delta5d: float | None,
    top5_delta5d: float | None,
    top10_delta5d: float | None,
    foreign_opt_net: float | None,
    retail_ratio: float | None,
    oi_delta5d: float | None,
) -> list[str]:
    divs = []
    if price_delta5d is None:
        return ["PRICE_DATA_MISSING"]

    price_up = price_delta5d > 0

    def _mismatch(name, delta, bullish_when_positive=True):
        if delta is None:
            return
        following = (delta > 0) == price_up if bullish_when_positive else (delta > 0) != price_up
        if not following:
            divs.append(f"PRICE_VS_{name}")

    _mismatch("FOREIGN_CASH", foreign_cash_5d)
    _mismatch("FUTURES", ff_delta5d)
    _mismatch("TOP5", top5_delta5d)
    _mismatch("TOP10", top10_delta5d)

    # OI divergence: price up + OI up = healthy; price up + OI down = warning
    if oi_delta5d is not None:
        if price_up and oi_delta5d < -2000:
            divs.append("PRICE_OI_DIVERGENCE")
        elif not price_up and oi_delta5d > 2000:
            divs.append("PRICE_OI_DIVERGENCE")

    return divs if divs else ["NONE"]


# ── Exhaustion engine ─────────────────────────────────────────────────────────

def _exhaustion(
    retail_pct: float | None,
    pcr_pct: float | None,
    ff_pct: float | None,
    top5_pct: float | None,
    oi_pct: float | None,
    price_delta5d: float | None,
) -> str:
    price_up = price_delta5d is not None and price_delta5d > 0
    price_down = price_delta5d is not None and price_delta5d < 0

    extreme_scores = 0
    total_avail = 0

    checks = [
        (retail_pct, 80, 20, price_up),   # extreme long in up market
        (pcr_pct, 20, 80, not price_up),  # PCR extreme (low in up = complacent)
        (ff_pct, 85, 15, price_up),
        (top5_pct, 85, 15, price_up),
        (oi_pct, 85, 15, None),           # OI extreme regardless of direction
    ]

    for pct, high_thresh, low_thresh, up_context in checks:
        if pct is None:
            continue
        total_avail += 1
        if up_context is True and pct > high_thresh:
            extreme_scores += 1
        elif up_context is False and pct < low_thresh:
            extreme_scores += 1
        elif up_context is None and (pct > high_thresh or pct < low_thresh):
            extreme_scores += 1

    if total_avail == 0:
        return "UNKNOWN"
    ratio = extreme_scores / total_avail

    if ratio >= 0.6:
        if price_up:
            return "OVERHEATED"
        elif price_down:
            return "CAPITULATION_CANDIDATE"
    return "NORMAL"


# ── OI State ─────────────────────────────────────────────────────────────────

def _oi_state(price_delta5d: float | None, oi_delta5d: float | None) -> str:
    if price_delta5d is None or oi_delta5d is None:
        return "UNKNOWN"
    if price_delta5d > 0 and oi_delta5d > 0:
        return "PRICE_UP_OI_UP"
    if price_delta5d > 0 and oi_delta5d < 0:
        return "PRICE_UP_OI_DOWN"
    if price_delta5d < 0 and oi_delta5d > 0:
        return "PRICE_DOWN_OI_UP"
    return "PRICE_DOWN_OI_DOWN"


# ── Summary text ─────────────────────────────────────────────────────────────

def _summary(row: dict) -> str:
    parts = []

    cash = row.get("foreign_cash_5d")
    if cash is not None:
        parts.append(f"外資現貨{'買超' if cash > 0 else '賣超'} {abs(cash):.1f}億（5日）")

    ff_net = row.get("foreign_futures_net_oi")
    ff_trans = row.get("positioning_transition", "")
    if ff_net is not None:
        direction = "淨多" if ff_net > 0 else "淨空"
        parts.append(f"外資期貨{direction} {abs(ff_net):.0f}口（{ff_trans}）")

    t5 = row.get("top5_net_oi")
    if t5 is not None:
        parts.append(f"前五大{'淨多' if t5 > 0 else '淨空'} {abs(t5):,}口")

    pcr = row.get("pcr_oi_all")
    if pcr is not None:
        parts.append(f"PCR-OI {pcr:.1f}")

    retail = row.get("retail_mtx_ratio")
    if retail is not None:
        parts.append(f"散戶小台{'偏多' if retail > 0 else '偏空'} ({retail:.1f}%)")

    state = row.get("positioning_state", "")
    divs = row.get("positioning_divergence", "NONE")
    exhaustion = row.get("positioning_exhaustion", "NORMAL")

    summary_parts = ["、".join(parts)] if parts else []
    summary_parts.append(f"整體定位：{state}")
    if divs and divs != "NONE":
        summary_parts.append(f"背離：{divs}")
    if exhaustion not in ("NORMAL", "UNKNOWN"):
        summary_parts.append(f"極端狀態：{exhaustion}")

    return "。".join(summary_parts)


# ── Main compute function ─────────────────────────────────────────────────────

def compute_positioning(raw: dict, target_date: str | None = None) -> dict:
    """
    Given raw fetched data, compute all derived indicators and states.
    Saves result to positioning_daily.
    """
    conn = get_conn()
    td_str = target_date or raw.get("observation_date") or date.today().strftime("%Y-%m-%d")

    # Pull historical series for delta/percentile calculations
    def _series(col, limit=300):
        return get_series(conn, col, up_to_date=td_str, limit=limit)

    ff_series = _series("foreign_futures_net_oi")
    t5_series = _series("top5_net_oi")
    t10_series = _series("top10_net_oi")
    cash_series = _series("foreign_cash_net")
    retail_series = _series("retail_mtx_ratio")
    pcr_series = _series("pcr_oi_all")
    oi_series = _series("tx_equivalent_total_oi")
    taiex_series = _series("taiex_close")

    # TAIEX 歷史不足 6 筆時：從 regime.db 補充（regime 每天從 Yahoo Finance 抓）
    if len(taiex_series) < 6:
        try:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path
            _regime_db = _Path(__file__).parent.parent / "chip_data" / "regime.db"
            if _regime_db.exists():
                _rc = _sqlite3.connect(str(_regime_db))
                _rows = _rc.execute(
                    "SELECT date, value FROM market_daily "
                    "WHERE series='TAIEX' AND value IS NOT NULL "
                    "ORDER BY date DESC LIMIT 300"
                ).fetchall()
                _rc.close()
                _regime_taiex = [(r[0], r[1]) for r in reversed(_rows)]
                if len(_regime_taiex) >= 6:
                    # 把 regime TAIEX 寫入 positioning_daily，補全歷史
                    _pc = get_conn()
                    for _dt, _val in _regime_taiex:
                        try:
                            _pc.execute(
                                "INSERT OR IGNORE INTO positioning_daily "
                                "(observation_date, taiex_close) VALUES (?, ?)",
                                (_dt, _val)
                            )
                            _pc.execute(
                                "UPDATE positioning_daily SET taiex_close=? "
                                "WHERE observation_date=? AND taiex_close IS NULL",
                                (_val, _dt)
                            )
                        except Exception:
                            pass
                    _pc.commit()
                    _pc.close()
                    taiex_series = _series("taiex_close")
                    if len(taiex_series) < 6:
                        taiex_series = _regime_taiex  # 直接用 regime 資料
        except Exception as _e:
            log.warning(f"[calculator] regime TAIEX fallback: {_e}")

    def _vals(s):
        return [v for _, v in s if v is not None]

    # ── Deltas ──
    # We need to append today's value to the series temporarily
    def _append_current(series, current_val):
        if current_val is None:
            return series
        return series + [(td_str, current_val)]

    ff_full = _append_current(ff_series, raw.get("foreign_futures_net_oi"))
    t5_full = _append_current(t5_series, raw.get("top5_net_oi"))
    t10_full = _append_current(t10_series, raw.get("top10_net_oi"))
    cash_full = _append_current(cash_series, raw.get("foreign_cash_net"))
    retail_full = _append_current(retail_series, raw.get("retail_mtx_ratio"))
    pcr_full = _append_current(pcr_series, raw.get("pcr_oi_all"))
    oi_full = _append_current(oi_series, raw.get("tx_equivalent_total_oi"))
    taiex_full = _append_current(taiex_series, raw.get("taiex_close"))

    ff_delta1d = _delta(ff_full, 1)
    ff_delta5d = _delta(ff_full, 5)
    t5_delta1d = _delta(t5_full, 1)
    t5_delta5d = _delta(t5_full, 5)
    t10_delta1d = _delta(t10_full, 1)
    t10_delta5d = _delta(t10_full, 5)
    cash_delta1d = _delta(cash_full, 1)
    cash_delta5d = _delta(cash_full, 5)
    retail_delta1d = _delta(retail_full, 1)
    oi_delta1d = _delta(oi_full, 1)
    oi_delta5d = _delta(oi_full, 5)
    price_delta5d = _delta(taiex_full, 5)

    # ── Cumulative cash ──
    foreign_cash_3d = _sum_last(cash_full, 3)
    foreign_cash_5d = _sum_last(cash_full, 5)
    foreign_cash_10d = _sum_last(cash_full, 10)
    foreign_cash_20d = _sum_last(cash_full, 20)

    # ── Percentiles (250D) ──
    ff_hist = _vals(ff_series)
    ff_cur = raw.get("foreign_futures_net_oi")
    ff_pct = _rolling_percentile(ff_hist[-250:], ff_cur) if ff_cur is not None else None

    t5_hist = _vals(t5_series)
    t5_cur = raw.get("top5_net_oi")
    t5_pct = _rolling_percentile(t5_hist[-250:], t5_cur) if t5_cur is not None else None

    t10_hist = _vals(t10_series)
    t10_cur = raw.get("top10_net_oi")
    t10_pct = _rolling_percentile(t10_hist[-250:], t10_cur) if t10_cur is not None else None

    pcr_hist = _vals(pcr_series)
    pcr_cur = raw.get("pcr_oi_all")
    pcr_pct = _rolling_percentile(pcr_hist[-250:], pcr_cur) if pcr_cur is not None else None

    retail_hist = _vals(retail_series)
    retail_cur = raw.get("retail_mtx_ratio")
    retail_pct = _rolling_percentile(retail_hist[-250:], retail_cur) if retail_cur is not None else None

    oi_hist = _vals(oi_series)
    oi_cur = raw.get("tx_equivalent_total_oi")
    oi_pct = _rolling_percentile(oi_hist[-250:], oi_cur) if oi_cur is not None else None

    # ── Transition ──
    ff_delta3d = _delta(ff_full, 3)
    ff_delta10d = _delta(ff_full, 10)
    transition = _transition(ff_delta1d, ff_delta3d, ff_delta5d, ff_delta10d)

    # ── State ──
    state = _positioning_state(
        foreign_futures_net=ff_cur,
        foreign_futures_delta5d=ff_delta5d,
        top5_net=t5_cur,
        top5_delta5d=t5_delta5d,
        foreign_cash_5d=foreign_cash_5d,
        retail_ratio=retail_cur,
        retail_pct=retail_pct,
        pcr_pct=pcr_pct,
        total_oi_delta1d=oi_delta1d,
        price_delta5d=price_delta5d,
    )

    # ── Divergence ──
    divs = _divergences(
        price_delta5d=price_delta5d,
        foreign_cash_5d=foreign_cash_5d,
        ff_delta5d=ff_delta5d,
        top5_delta5d=t5_delta5d,
        top10_delta5d=t10_delta5d,
        foreign_opt_net=raw.get("foreign_option_net_value"),
        retail_ratio=retail_cur,
        oi_delta5d=oi_delta5d,
    )
    divergence_str = "|".join(divs)

    # ── Exhaustion ──
    exhaustion = _exhaustion(
        retail_pct=retail_pct,
        pcr_pct=pcr_pct,
        ff_pct=ff_pct,
        top5_pct=t5_pct,
        oi_pct=oi_pct,
        price_delta5d=price_delta5d,
    )

    # ── Build final row ──
    result = {
        **raw,
        "observation_date": td_str,
        # Deltas
        "delta_foreign_cash_1d": cash_delta1d,
        "delta_foreign_cash_5d": cash_delta5d,
        "delta_foreign_futures_1d": ff_delta1d,
        "delta_foreign_futures_5d": ff_delta5d,
        "delta_top5_1d": int(t5_delta1d) if t5_delta1d is not None else None,
        "delta_top5_5d": int(t5_delta5d) if t5_delta5d is not None else None,
        "delta_top10_1d": int(t10_delta1d) if t10_delta1d is not None else None,
        "delta_top10_5d": int(t10_delta5d) if t10_delta5d is not None else None,
        "delta_retail_1d": retail_delta1d,
        "delta_oi_1d": oi_delta1d,
        "delta_oi_5d": oi_delta5d,
        # Cumulative cash
        "foreign_cash_3d": foreign_cash_3d,
        "foreign_cash_5d": foreign_cash_5d,
        "foreign_cash_10d": foreign_cash_10d,
        "foreign_cash_20d": foreign_cash_20d,
        # Percentiles
        "foreign_futures_pct250": ff_pct,
        "top5_pct250": t5_pct,
        "top10_pct250": t10_pct,
        "pcr_pct250": pcr_pct,
        "retail_pct250": retail_pct,
        "oi_pct250": oi_pct,
        # States
        "positioning_state": state,
        "positioning_transition": transition,
        "positioning_divergence": divergence_str,
        "positioning_exhaustion": exhaustion,
    }

    result["positioning_summary"] = _summary(result)
    upsert_positioning(conn, result)
    conn.close()
    return result


def backfill_positioning(days: int = 120):
    """Backfill missing positioning calculations (not fetching, just re-computing from raw data)."""
    conn = get_conn()
    # Find dates that have raw data but no positioning_daily entry
    raw_dates = conn.execute(
        "SELECT DISTINCT observation_date FROM raw_taifex_inst_futures "
        "ORDER BY observation_date DESC LIMIT ?",
        (days,),
    ).fetchall()
    existing = set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT observation_date FROM positioning_daily "
            f"WHERE observation_date >= date('now', '-{days} days')"
        ).fetchall()
    )
    conn.close()

    missing = [r[0] for r in raw_dates if r[0] not in existing]
    log.info(f"Backfill: {len(missing)} missing dates")
    return missing
