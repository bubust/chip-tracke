"""
Regime Engine — 因子計算引擎 (V1.1)
Sprint 4: backfill_factors(), target_date support, positioning/concentration fallbacks
"""
import math
import logging
from datetime import date, timedelta
from typing import Optional

from .db import db, upsert_series

log = logging.getLogger(__name__)

def _get_series(conn, series: str, limit: int = 252, up_to_date: str = None) -> list[tuple[str, float]]:
    """取 series 資料。若指定 up_to_date，只取該日期以前的資料。"""
    if up_to_date:
        rows = conn.execute("""
            SELECT date, value FROM market_daily
            WHERE series=? AND value IS NOT NULL AND date <= ?
            ORDER BY date DESC LIMIT ?
        """, (series, up_to_date, limit)).fetchall()
    else:
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
    target_date: 若指定，只使用 <= target_date 的市場資料（供歷史回填用）
    回傳 dict with keys: trend, breadth, positioning, macro, direction, risk_score, exhaustion, regime_label
    """
    today = target_date or date.today().strftime("%Y-%m-%d")

    with db() as conn:
        taiex  = _get_series(conn, "TAIEX",   300, up_to_date=today)
        otc    = _get_series(conn, "OTC",     300, up_to_date=today)
        sp500  = _get_series(conn, "SP500",   300, up_to_date=today)
        sox    = _get_series(conn, "SOX",     300, up_to_date=today)
        vix    = _get_series(conn, "VIX",     300, up_to_date=today)
        us10y  = _get_series(conn, "US10Y",   300, up_to_date=today)
        usdtwd = _get_series(conn, "USDTWD",  300, up_to_date=today)
        margin = _get_series(conn, "MARGIN_BALANCE",    300, up_to_date=today)
        foreign_net     = _get_series(conn, "FOREIGN_NET_LOT",    300, up_to_date=today)
        # Sprint 2
        breadth_50ma    = _get_series(conn, "BREADTH_50MA",       300, up_to_date=today)
        ad_line         = _get_series(conn, "AD_LINE",            300, up_to_date=today)
        median_ret      = _get_series(conn, "MEDIAN_RET",         300, up_to_date=today)
        foreign_futures = _get_series(conn, "FOREIGN_FUTURES_NET", 300, up_to_date=today)

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

    # ── Breadth (Sprint 2: % stocks above 50MA + AD趨勢) ─────────────────
    if breadth_50ma and len(breadth_50ma) >= 5:
        b_vals = [v for _, v in breadth_50ma[-20:]]
        cur_b = b_vals[-1]  # 0~100，例如 60 = 60% 股票站上50MA
        # 轉換為 -100~+100 方向分數：50% 為中性
        b_dir = _pct_to_direction(cur_b)
        # A/D 趨勢加權（A/D 5日均vs20日均，方向一致加分）
        ad_boost = 0.0
        if ad_line and len(ad_line) >= 20:
            ad_vals = [v for _, v in ad_line[-20:]]
            ad_5d = sum(ad_vals[-5:]) / 5
            ad_20d = sum(ad_vals) / 20
            if ad_5d > 0 and ad_20d > 0:
                ad_boost = min(20, ad_5d / max(abs(ad_20d), 1) * 10)
            elif ad_5d < 0 and ad_20d < 0:
                ad_boost = max(-20, ad_5d / max(abs(ad_20d), 1) * 10)
        breadth_score = round(max(-100, min(100, b_dir + ad_boost)), 1)
    else:
        breadth_score = 0.0

    # ── Positioning: Foreign Spot + Futures ──────────────────────────────
    fn_score = 0.0
    if foreign_net and len(foreign_net) >= 2:
        fn_vals = [v for _, v in foreign_net]
        if len(fn_vals) >= 10:
            # 正常路徑：z-score
            fn_5d  = sum(fn_vals[-5:])
            fn_20d = sum(fn_vals[-20:] if len(fn_vals) >= 20 else fn_vals)
            fn_score = _zscore_to_score((fn_5d / max(abs(fn_20d), 1)) * 2)
        else:
            # 資料不足：用最近幾日的方向（正=買超，負=賣超）
            recent_sum = sum(fn_vals[-5:] if len(fn_vals) >= 5 else fn_vals)
            fn_score = 50.0 if recent_sum > 0 else -50.0
            log.debug(f"[factor] FOREIGN_NET_LOT 資料不足({len(fn_vals)}筆)，使用方向 fallback: {fn_score}")

    # 外資期貨淨部位方向（正=多頭傾向，負=空頭傾向）
    ff_score = 0.0
    if foreign_futures and len(foreign_futures) >= 2:
        ff_vals = [v for _, v in foreign_futures]
        if len(ff_vals) >= 3:
            ff_5d = sum(ff_vals[-5:]) / len(ff_vals[-5:])
            ff_score = _zscore_to_score(ff_5d / max(abs(sum(ff_vals) / len(ff_vals)), 1) * 2)
        else:
            # 資料不足：用方向
            ff_score = 50.0 if ff_vals[-1] > 0 else -50.0
            log.debug(f"[factor] FOREIGN_FUTURES_NET 資料不足({len(ff_vals)}筆)，使用方向 fallback: {ff_score}")

    # 加權合成 (現貨 60%，期貨 40%)
    if foreign_net or foreign_futures:
        positioning_score = round(fn_score * 0.6 + ff_score * 0.4, 1)
    else:
        positioning_score = 0.0

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

    # ── Exhaustion (Sprint 2: 極端漲跌後的竭盡訊號) ─────────────────────
    # 使用中位數漲跌幅 + 市場廣度 + VIX 峰值識別極端狀態
    exhaustion = 0.0
    if median_ret and len(median_ret) >= 20 and breadth_50ma and len(breadth_50ma) >= 20:
        med_vals = [v for _, v in median_ret[-20:]]
        b_vals_ex = [v for _, v in breadth_50ma[-20:]]
        # 最近5日中位數漲幅均值（正=過熱傾向，負=恐慌傾向）
        med_5d_avg = sum(med_vals[-5:]) / 5
        # 廣度極端：>85% 或 <15% 代表可能竭盡
        cur_breadth = b_vals_ex[-1]
        breadth_extreme = max(0, cur_breadth - 75) / 25 * 50 if cur_breadth > 75 else max(0, 25 - cur_breadth) / 25 * 50
        # VIX 極端（已在 vix_risk 計算過，這裡取高 VIX 竭盡）
        vix_extreme = min(50, max(0, vix_risk - 50)) if vix_risk > 50 else 0
        # 綜合竭盡：廣度極端 + VIX 極端，最高100
        exhaustion = round(min(100, breadth_extreme * 0.6 + vix_extreme * 0.4), 1)
    elif breadth_50ma and len(breadth_50ma) >= 5:
        # median_ret 不足時，僅用廣度 + VIX
        b_vals_ex = [v for _, v in breadth_50ma[-10:]]
        cur_breadth = b_vals_ex[-1]
        breadth_extreme = max(0, cur_breadth - 75) / 25 * 50 if cur_breadth > 75 else max(0, 25 - cur_breadth) / 25 * 50
        vix_extreme = min(50, max(0, vix_risk - 50)) if vix_risk > 50 else 0
        exhaustion = round(min(100, breadth_extreme * 0.6 + vix_extreme * 0.4), 1)

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

    # ── Concentration (集中度：指數 vs 全市場中位數，Sprint 2) ───────────
    # 若中位數漲跌幅遠小於指數動能，代表集中度高（少數股撐盤）
    concentration = None  # None = 無資料，前端顯示 —
    if median_ret and len(median_ret) >= 5 and t1 is not None:
        med_recent = [v for _, v in median_ret[-10:]]
        med_avg = sum(med_recent) / len(med_recent)
        if abs(med_avg) > 0:
            divergence_ratio = abs(t1 * 100 - med_avg) / max(abs(med_avg), 0.1)
            concentration = round(min(100, divergence_ratio * 20), 1)
        else:
            concentration = 0.0
    elif breadth_50ma and len(breadth_50ma) >= 5 and t1 is not None:
        # MEDIAN_RET 無資料：用廣度變化代理集中度
        b_recent = [v for _, v in breadth_50ma[-10:]]
        b_avg = sum(b_recent) / len(b_recent)
        # 廣度遠低於 50% 且指數向上 → 集中度高
        if t1 > 0 and b_avg < 45:
            concentration = round(min(100, (45 - b_avg) * 3), 1)
        elif t1 < 0 and b_avg > 55:
            concentration = round(min(100, (b_avg - 55) * 3), 1)
        else:
            concentration = 0.0

    # ── Divergence (背離：廣度與指數方向不一致) ──────────────────────────
    divergence = 0.0
    if breadth_50ma and len(breadth_50ma) >= 10 and taiex and len(taiex) >= 10:
        b_trend = (breadth_50ma[-1][1] - breadth_50ma[-10][1]) if len(breadth_50ma) >= 10 else 0
        t_trend = (taiex[-1][1] - taiex[-10][1]) / max(taiex[-10][1], 1) * 100 if len(taiex) >= 10 else 0
        # 背離：指數漲但廣度跌（或反之）
        if (t_trend > 0 and b_trend < -5) or (t_trend < 0 and b_trend > 5):
            divergence = round(min(100, abs(t_trend) * 5 + abs(b_trend)), 1)

    result = {
        "date": today,
        "trend": round(trend_score, 1),
        "breadth": round(breadth_score, 1),
        "positioning": round(positioning_score, 1),
        "macro_factor": round(macro_score, 1),
        "direction": round(direction, 1),
        "leverage_risk": round(margin_risk, 1),
        "concentration": concentration,  # may be None
        "divergence": divergence,
        "risk_score": round(risk_score, 1),
        "exhaustion": round(exhaustion, 1),
        "regime_label": label,
    }

    # Store factors in DB（concentration 為 None 時儲存 NULL）
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
                concentration=excluded.concentration, divergence=excluded.divergence,
                risk_score=excluded.risk_score, exhaustion=excluded.exhaustion,
                regime_label=excluded.regime_label, updated_at=excluded.updated_at
        """, result)

    return result


def backfill_factors(days: int = 120):
    """
    為所有有 market_daily 資料但尚未計算 factors 的歷史日期補算因子。
    最多回溯 days 天。
    """
    try:
        with db() as conn:
            # 取最近 days 天內有資料的日期（以 TAIEX 為基準，有 TAIEX 才算可計算）
            dates_with_data = [
                row[0] for row in conn.execute(
                    "SELECT DISTINCT date FROM market_daily WHERE series='TAIEX' ORDER BY date DESC LIMIT ?",
                    (days,)
                ).fetchall()
            ]

            # 已有 factors 的日期
            dates_with_factors = set(
                row[0] for row in conn.execute(
                    "SELECT DISTINCT date FROM factors"
                ).fetchall()
            )

        missing_dates = [d for d in dates_with_data if d not in dates_with_factors]
        missing_dates.sort()  # 由舊到新計算

        if not missing_dates:
            log.info("[factor] backfill_factors: 無需回填")
            return 0

        log.info(f"[factor] backfill_factors: 待補 {len(missing_dates)} 天")
        count = 0
        for target_date in missing_dates:
            try:
                calculate_factors(target_date=target_date)
                count += 1
                log.debug(f"[factor] backfill {target_date} OK")
            except Exception as e:
                log.warning(f"[factor] backfill {target_date} 失敗: {e}")

        log.info(f"[factor] backfill_factors 完成: 補算 {count} 天")
        return count

    except Exception as e:
        log.error(f"[factor] backfill_factors 錯誤: {e}")
        return 0
