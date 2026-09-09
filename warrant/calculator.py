"""
計算層 — Black-Scholes / IV 反推 / 回本門檻
完全按規格書 §5 實作
"""
import math
from typing import Optional
from scipy.optimize import brentq
from scipy.stats import norm

# 升降單位（§5.3）— 注意與股票不同
def warrant_tick(price: float) -> float:
    if price < 5:       return 0.01
    if price < 10:      return 0.05
    if price < 50:      return 0.10
    if price < 100:     return 0.50
    if price < 500:     return 1.00
    return 5.00


def bs_price(S: float, K: float, T: float, r: float, q: float,
             sigma: float, kind: str, N: float) -> Optional[float]:
    """§5.1 Black-Scholes 理論價，所有 Greeks 乘以 N"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "CALL":
        return (S * math.exp(-q * T) * norm.cdf(d1) -
                K * math.exp(-r * T) * norm.cdf(d2)) * N
    else:
        return (K * math.exp(-r * T) * norm.cdf(-d2) -
                S * math.exp(-q * T) * norm.cdf(-d1)) * N


def bs_greeks(S: float, K: float, T: float, r: float, q: float,
              sigma: float, kind: str, N: float) -> dict:
    """Delta / Vega / Theta（每日）"""
    if T <= 0 or sigma <= 0:
        return {"delta": None, "vega": None, "theta_daily": None}
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    phi_d1 = norm.pdf(d1)

    if kind == "CALL":
        delta = math.exp(-q * T) * norm.cdf(d1) * N
        # Theta per year (標準 BS)
        theta_yr = (
            -S * math.exp(-q * T) * phi_d1 * sigma / (2 * math.sqrt(T))
            - r * K * math.exp(-r * T) * norm.cdf(d2)
            + q * S * math.exp(-q * T) * norm.cdf(d1)
        ) * N
    else:
        delta = -math.exp(-q * T) * norm.cdf(-d1) * N
        theta_yr = (
            -S * math.exp(-q * T) * phi_d1 * sigma / (2 * math.sqrt(T))
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
            - q * S * math.exp(-q * T) * norm.cdf(-d1)
        ) * N

    vega = S * math.exp(-q * T) * phi_d1 * math.sqrt(T) * N  # per σ=1.00
    theta_daily = theta_yr / 365

    return {"delta": delta, "vega": vega, "theta_daily": theta_daily}


def implied_vol(market_price: float, S: float, K: float, N: float,
                T: float, r: float, q: float, kind: str) -> Optional[float]:
    """§5.2 Brent 法反推 IV，回傳 None 而非 0 或外推"""
    if T <= 0 or market_price is None:
        return None
    intrinsic = max(0, (S - K) if kind == "CALL" else (K - S)) * N
    if market_price <= intrinsic:
        return None

    def f(sigma):
        p = bs_price(S, K, T, r, q, sigma, kind, N)
        return (p or 0) - market_price

    try:
        lo, hi = 0.001, 20.0
        flo, fhi = f(lo), f(hi)
        if flo * fhi > 0:
            return None   # 同號，無解，不外推
        return brentq(f, lo, hi, xtol=1e-8, maxiter=300)
    except Exception:
        return None


FEE = 0.001425
TAX_WARRANT = 0.001
TAX_STOCK = 0.003


def total_hurdle(bid: float, ask: float, S: float,
                 delta: float, vega: float, theta_daily: float,
                 warrant_price: float, fee_discount: float,
                 holding_days: int, iv_stability_pt: float) -> dict:
    """
    §5.4 回本門檻計算
    warrant_price = (bid + ask) / 2 or mid
    iv_stability_pt = 隱波波動（百分點），例如 0.4 代表 ±0.4pp 的波動
    """
    if bid <= 0 or ask <= 0 or warrant_price <= 0:
        return {}

    # 1. 進出成本
    buy_cost = ask * (1 + FEE * fee_discount)
    sell_net = bid * (1 - FEE * fee_discount - TAX_WARRANT)
    instant_loss_pct = 1 - sell_net / buy_cost

    # 2. 時間成本
    theta_decay_daily = abs(theta_daily) / warrant_price if warrant_price > 0 else 0
    theta_cost_pct = theta_decay_daily * holding_days

    # 3. 隱波成本
    iv_drop_1pt_loss_pct = (abs(vega) * 0.01) / warrant_price if warrant_price > 0 else 0
    expected_iv_loss_pct = iv_drop_1pt_loss_pct * iv_stability_pt

    # 換算成「標的需變動幾 %」
    eff_lev = S * abs(delta) / warrant_price   # N 已含在 delta 中
    if eff_lev <= 0:
        return {}

    entry_hurdle  = instant_loss_pct     / eff_lev
    time_hurdle   = theta_cost_pct       / eff_lev
    iv_hurdle     = expected_iv_loss_pct / eff_lev
    total_h       = entry_hurdle + time_hurdle + iv_hurdle

    # §5.5 現股進出成本
    stock_entry_hurdle = FEE * fee_discount * 2 + TAX_STOCK
    is_cheaper = entry_hurdle < stock_entry_hurdle

    return {
        "instant_loss_pct":    round(instant_loss_pct, 6),
        "theta_cost_pct":      round(theta_cost_pct, 6),
        "iv_drop_1pt_loss_pct":round(iv_drop_1pt_loss_pct, 6),
        "expected_iv_loss_pct":round(expected_iv_loss_pct, 6),
        "effective_leverage":  round(eff_lev, 4),
        "entry_hurdle":        round(entry_hurdle, 6),
        "time_hurdle":         round(time_hurdle, 6),
        "iv_hurdle":           round(iv_hurdle, 6),
        "total_hurdle_pct":    round(total_h, 6),
        "stock_entry_hurdle":  round(stock_entry_hurdle, 6),
        "is_cheaper_than_stock": is_cheaper,
    }


def three_lights(entry_h: float, time_h: float, iv_h: float,
                 stock_entry_h: float, is_cheaper: bool,
                 spread_ratio: float, bid_value: float,
                 position_size: int, bid_lots: int) -> dict:
    """§7.2 三燈號"""
    # 💰 進出燈
    if is_cheaper and spread_ratio <= 0.015:
        entry_light = "green"
    elif entry_h > stock_entry_h * 2:
        entry_light = "red"
    else:
        entry_light = "yellow"

    # ⏳ 持有燈
    hold_cost = time_h + iv_h
    if hold_cost <= 0.005:
        holding_light = "green"
    elif hold_cost <= 0.015:
        holding_light = "yellow"
    else:
        holding_light = "red"

    # 🚪 出場燈
    if bid_value >= position_size * 3 and bid_lots >= 50:
        exit_light = "green"
    elif bid_value >= position_size * 1.5:
        exit_light = "yellow"
    else:
        exit_light = "red"

    return {"entry": entry_light, "holding": holding_light, "exit": exit_light}
