"""
Regime Engine — 因子計算引擎 (V1.0)
"""
import math
import logging
from datetime import date, timedelta
from typing import Optional

from .db import db, upsert_series

log = logging.getLogger(__name__)

def _get_series(conn, series: str, limit: int = 252) -> list[tuple[str, float]]:
    rows = conn.execute("""
        SELECT date, value FROM market_daily
        WHERE series=? AND value IS NOT NULL
        ORDER BY date DESC LIMIT ?
    """, (series, limit)).fetchall()
    return [(r["date"], r["value"]) for r in reversed(rows)]

def _rolling_pct(values: list[float], window: int = 252) -> list[float]:
    """Rolling percentile rank (0–100)"""
    result = [float("nan")] * len(values)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        sub = values[start:i + 1]
        if len(sub) < 20:
            continue
        v = values[i]
        rank = sum(1 for x in sub if x <= v) / len(sub) * 100
        result[i] = round(rank, 2)
    return result

def _risk_adj_momentum(prices: list[float], period: int) -> Optional[float]:
    """Return / Rolling_Volatility (annualized)"""
    if len(prices) < period + 20:
        return None
    ret = (prices[-1] - prices[-period]) / prices[-period]
    daily_rets = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(max(1, len(prices)-period), len(prices))]
    if not daily_rets:
        return None
    mean = sum(daily_rets) / len(daily_rets)
    variance = sum((x - mean)**2 for x in daily_rets) / len(daily_rets)
    vol = math.sqrt(variance * 252) if variance > 0 else 0.0001
    return ret / vol if vol > 0 else None

def _zscore_to_score(z: Optional[float], clamp: float = 3.0) -> float:
    """Convert z-score to -100~+100 scale"""
    if z is None:
        return 0.0
    clamped = max(-clamp, min(clamp, z))
    return round(clamped / clamp * 100, 2)

def _pct_to_direction(pct: Optional[float]) -> float:
    """Convert rolling percentile (0-100) to direction score (-100 to +100)"""
    if pct is None:
        return 0.0
    return round((pct - 50) * 2, 2)


def calculate_factors(target_date: Optional[str] = None) -> dict:
    """
    計算指定日期的 Regime 因子。
    回傳 dict with keys: trend, breadth, positioning, macro, direction, risk_score, exhaustion, regime_label
    """
    today = target_date or date.today().strftime("%Y-%m-%d")

    with db() as conn:
        taiex = _get_series(conn, "TAIEX", 300)
        otc   = _get_series(conn, "OTC",   300)
        sp500 = _get_series(conn, "SP500", 300)
        sox   = _get_series(conn, "SOX",   300)
        vix   = _get_series(conn, "VIX",   300)
        us10y = _get_series(conn, "US10Y", 300)
        usdtwd = _get_series(conn, "USDTWD", 300)
        margin = _get_series(conn, "MARGIN_BALANCE", 300)
        foreign_net = _get_series(conn, "FOREIGN_NET_LOT", 300)

    # ── T1/T2: TAIEX Risk-adjusted Momentum ──────────────────────────────
    taiex_px = [v for _, v in taiex]
    t1 = _risk_adj_momentum(taiex_px, 20)   # 20D
    t2 = _risk_adj_momentum(taiex_px, 60)   # 60D

    # ── T3: OTC Relative Strength (OTC mom - TAIEX mom) ──────────────────
    otc_px = [v for _, v in otc]
    otc_20d = _risk_adj_momentum(otc_px, 20)
    t3 = (otc_20d - t1) if (otc_20d and t1) else None

    # ── Trend Factor (weighted avg of T1, T2, T3) ────────────────────────
    trend_inputs = [(t1, 0.4), (t2, 0.4), (t3, 0.2)]
    trend_vals = [(v, w) for v, w in trend_inputs if v is not None]
    if trend_vals:
        total_w = sum(w for _, w in trend_vals)
        trend_raw = sum(v * w for v, w in trend_vals) / total_w
        # Convert to percentile then direction
        trend_score = _zscore_to_score(trend_raw * 3)  # scale: ram ~0.3 → good
    else:
        trend_score = 0.0

    # ── Breadth (placeholder — from scanner.py breadth scan) ─────────────
    # TODO Sprint 2: integrate with scanner breadth output
    breadth_score = 0.0

    # ── Positioning: Foreign Spot ─────────────────────────────────────────
    if foreign_net and len(foreign_net) >= 5:
        fn_vals = [v for _, v in foreign_net[-20:]]
        fn_5d = sum(fn_vals[-5:])
        fn_20d = sum(fn_vals[-20:] if len(fn_vals) >= 20 else fn_vals)
        fn_score = _zscore_to_score((fn_5d / max(abs(fn_20d), 1)) * 2)
    else:
        fn_score = 0.0

    positioning_score = fn_score

    # ── Macro Factor ──────────────────────────────────────────────────────
    sp500_px = [v for _, v in sp500]
    sox_px   = [v for _, v in sox]
    sp_mom   = _risk_adj_momentum(sp500_px, 20)
    sox_mom  = _risk_adj_momentum(sox_px, 20)
    macro_raw = ((sp_mom or 0) * 0.5 + (sox_mom or 0) * 0.5)
    macro_score = _zscore_to_score(macro_raw * 3)

    # ── VIX Risk (inverted) ───────────────────────────────────────────────
    if vix:
        vix_vals = [v for _, v in vix[-60:]]
        cur_vix = vix_vals[-1]
        avg_vix = sum(vix_vals) / len(vix_vals)
        vix_risk = min(100, max(0, (cur_vix - 15) / 30 * 100))
    else:
        vix_risk = 0.0

    # ── Margin Risk ───────────────────────────────────────────────────────
    if margin and len(margin) >= 20:
        m_vals = [v for _, v in margin[-60:]]
        m_20d_chg = (m_vals[-1] - m_vals[-20]) / max(m_vals[-20], 1) * 100
        margin_risk = min(100, max(0, 50 + m_20d_chg * 5))
    else:
        margin_risk = 50.0

    # ── USD/TWD divergence (macro risk indicator) ─────────────────────────
    usdtwd_px = [v for _, v in usdtwd]
    usdtwd_mom = _risk_adj_momentum(usdtwd_px, 20)
    # TWD strengthening (TWD=X falling) → positive for Taiwan → reduce risk
    fx_risk = _zscore_to_score((usdtwd_mom or 0) * 3)  # positive = USD strengthening = risk

    # ── Composite Scores ──────────────────────────────────────────────────
    direction = round(
        trend_score * 0.40 +
        breadth_score * 0.25 +
        positioning_score * 0.20 +
        macro_score * 0.15,
        1
    )

    risk_score = round(
        vix_risk * 0.40 +
        margin_risk * 0.30 +
        max(0, fx_risk) * 0.30,
        1
    )

    exhaustion = 0.0  # TODO Sprint 2

    # ── Regime Label ──────────────────────────────────────────────────────
    if direction > 50 and risk_score < 50:
        label = "🟢 健康多頭"
    elif direction > 50 and risk_score > 70:
        label = "🔴 多頭過熱"
    elif direction < -50 and risk_score > 80 and exhaustion > 75:
        label = "🟡 恐慌竭盡"
    elif direction < -50:
        label = "🔴 空頭"
    elif risk_score > 85:
        label = "🚨 極端風險"
    else:
        label = "🟡 震盪中性"

    result = {
        "date": today,
        "trend": round(trend_score, 1),
        "breadth": round(breadth_score, 1),
        "positioning": round(positioning_score, 1),
        "macro_factor": round(macro_score, 1),
        "direction": round(direction, 1),
        "leverage_risk": round(margin_risk, 1),
        "concentration": 0.0,   # TODO
        "divergence": 0.0,      # TODO
        "risk_score": round(risk_score, 1),
        "exhaustion": round(exhaustion, 1),
        "regime_label": label,
    }

    # Store factors in DB
    with db() as conn:
        conn.execute("""
            INSERT INTO factors(date, trend, breadth, positioning, macro_factor,
                direction, leverage_risk, concentration, divergence,
                risk_score, exhaustion, regime_label, updated_at)
            VALUES(:date,:trend,:breadth,:positioning,:macro_factor,
                :direction,:leverage_risk,:concentration,:divergence,
                :risk_score,:exhaustion,:regime_label,datetime('now'))
            ON CONFLICT(date) DO UPDATE SET
                trend=excluded.trend, breadth=excluded.breadth,
                positioning=excluded.positioning, macro_factor=excluded.macro_factor,
                direction=excluded.direction, leverage_risk=excluded.leverage_risk,
                risk_score=excluded.risk_score, exhaustion=excluded.exhaustion,
                regime_label=excluded.regime_label, updated_at=excluded.updated_at
        """, result)

    return result
