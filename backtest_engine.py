"""
backtest_engine.py - 單股 / 批量回測共用的純函式（PLAN-BACKTEST §3）

- simulate(df, signal_mask, direction, exit_cfg, cost_cfg) -> (trades, open_trade)
- compute_stats(trades) -> dict
- adjust_ohlcv(df)：用 Yahoo adjclose 換算還原 OHLC（保留 raw_* 原始價供漲跌停判斷）
- wilder_atr(high, low, close, n)：ATR(14) Wilder 平滑

規則摘要：
- 進場：訊號日隔天開盤（預設），或訊號日收盤；持倉中忽略新訊號（不疊單）
- 出場：當日 high/low 檢查觸價；跳空越過停損/停利 → 開盤價成交；同日同時碰到停損與停利 → 算停損
- 收盤型出場（均線、跌破N日低點）：收盤成立，隔天開盤出場
- 漲跌停一價到底：進場遇鎖死略過訊號；出場遇鎖死順延到下一個可成交日開盤
- 成本：每筆淨報酬 = 毛報酬 − 來回成本（預設 0.585%）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

from scanner import _tick_size, _limit_up_price

DEFAULT_COST_ROUNDTRIP = 0.00585   # 手續費 0.1425%×2 + 證交稅 0.3%


@dataclass
class ExitConfig:
    stop: str = "atr"            # atr | pct | none   初始停損
    stop_atr: float = 2.0
    stop_pct: float = 0.0        # %（如 5 = 5%）
    trail: str = "atr"           # atr | pct | none   移動停損（只往有利方向移）
    trail_atr: float = 2.5
    trail_pct: float = 0.0
    max_hold: int = 60           # 最多持有天數（交易日），0 = 不限
    exit_ma: int = 0             # 收盤跌破 MA 出場（隔日開盤），0 = 不用
    trail_low_days: int = 0      # 收盤跌破前 N 日低點出場（隔日開盤），0 = 不用
    time_stop_days: int = 0      # N 天內沒賺到 time_stop_pct% 就出場（當日收盤），0 = 不用
    time_stop_pct: float = 0.0
    take_profit: float = 0.0     # 停利 %，0 = 不用
    entry: str = "next_open"     # next_open | close

    def key(self) -> dict:
        return asdict(self)


@dataclass
class CostConfig:
    roundtrip: float = DEFAULT_COST_ROUNDTRIP


# ── 指標 ──────────────────────────────────────────────────────────────────────

def wilder_atr(high, low, close, n: int = 14) -> np.ndarray:
    """ATR(n)，Wilder 平滑（True Range 的 RMA，α=1/n）。
    TR[0] = H−L；ATR[n−1] = 前 n 個 TR 平均；之後 ATR[i] = (ATR[i−1]×(n−1) + TR[i]) / n。"""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    size = len(c)
    out = np.full(size, np.nan)
    if size < n:
        return out
    prev_c = np.concatenate(([np.nan], c[:-1]))
    tr = np.maximum.reduce([h - l,
                            np.where(np.isnan(prev_c), 0.0, np.abs(h - prev_c)),
                            np.where(np.isnan(prev_c), 0.0, np.abs(l - prev_c))])
    out[n - 1] = tr[:n].mean()
    for i in range(n, size):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _limit_down_price(prev_close: float) -> float:
    raw = prev_close * 0.90
    tick = _tick_size(raw)
    return round(math.ceil(round(raw / tick, 6)) * tick, 6)


def adjust_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含還原 OHLC 的 df（open/high/low/close 已還原），原始價存在 raw_*、factor 欄。
    沒有 adjclose 欄（或 NaN）時 factor = 1。"""
    out = df.reset_index(drop=True).copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].astype(float)
        out["raw_" + col] = out[col]
    if "adjclose" in out.columns:
        f = (out["adjclose"].astype(float) / out["close"]).replace([np.inf, -np.inf], np.nan)
        f = f.fillna(1.0)
    else:
        f = pd.Series(1.0, index=out.index)
    out["factor"] = f
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] * f
    # 有些 bar open/high/low 為 0 或 NaN（Yahoo 偶發）→ 以 close 補
    for col in ("open", "high", "low"):
        bad = out[col].isna() | (out[col] <= 0)
        out.loc[bad, col] = out.loc[bad, "close"]
        bad_raw = out["raw_" + col].isna() | (out["raw_" + col] <= 0)
        out.loc[bad_raw, "raw_" + col] = out.loc[bad_raw, "raw_close"]
    return out


def _locked_flags(df: pd.DataFrame):
    """回傳 (locked_up, locked_down) bool 陣列：一價到底（open=high=low）且在漲/跌停價。用原始價判斷。"""
    o = df["raw_open"].values if "raw_open" in df else df["open"].values
    h = df["raw_high"].values if "raw_high" in df else df["high"].values
    l = df["raw_low"].values if "raw_low" in df else df["low"].values
    c = df["raw_close"].values if "raw_close" in df else df["close"].values
    n = len(c)
    up = np.zeros(n, dtype=bool)
    dn = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not (abs(h[i] - l[i]) < 1e-9 and abs(o[i] - h[i]) < 1e-9):
            continue
        prev = c[i - 1]
        if not prev or prev <= 0:
            continue
        tick = _tick_size(o[i])
        if o[i] >= _limit_up_price(prev) - tick / 2:
            up[i] = True
        elif o[i] <= _limit_down_price(prev) + tick / 2:
            dn[i] = True
    return up, dn


# ── 模擬 ──────────────────────────────────────────────────────────────────────

def simulate(df: pd.DataFrame, signal_mask, direction: str = "long",
             exit_cfg: Optional[ExitConfig] = None,
             cost_cfg: Optional[CostConfig] = None):
    """
    df：已還原的 OHLCV（adjust_ohlcv 的輸出；也接受無 raw_* 欄的一般 df）
    signal_mask：長度 = len(df) 的 bool 序列，True = 該日收盤訊號成立
    回傳 (closed_trades: list[dict], open_trade: dict | None, info: dict)
    """
    ec = exit_cfg or ExitConfig()
    cc = cost_cfg or CostConfig()
    short = (direction == "short")
    df = df.reset_index(drop=True)
    n = len(df)
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    dates = [str(x) for x in df["date"].values]
    factor = df["factor"].values.astype(float) if "factor" in df else np.ones(n)
    locked_up, locked_down = _locked_flags(df)
    mask = list(signal_mask) + [False] * max(0, n - len(signal_mask))

    need_atr = ec.stop == "atr" or ec.trail == "atr"
    atr = wilder_atr(h, l, c, 14) if need_atr else None
    ma = pd.Series(c).rolling(ec.exit_ma, min_periods=ec.exit_ma).mean().values if ec.exit_ma > 0 else None

    sign = -1.0 if short else 1.0
    trades = []
    open_trade = None
    first_eligible = None      # 指標暖機後第一個可進場的 bar（給買進持有對照用）
    pending_signal = None      # 最後一根 K 線訊號成立、明天才進場
    blocked_entries = 0
    i = 0
    busy_until = -1            # 持倉至此 bar（含）不得再有新訊號

    def _raw(price, idx):
        f = factor[idx] if factor[idx] else 1.0
        return round(float(price / f), 2)

    def _warm(idx):
        if need_atr and (atr is None or np.isnan(atr[idx])):
            return False
        if ma is not None and np.isnan(ma[idx]):
            return False
        return True

    while i < n:
        if not _warm(i):
            i += 1
            continue
        if first_eligible is None:
            first_eligible = i
        if not mask[i] or i <= busy_until:
            i += 1
            continue

        # ── 進場 ──
        if ec.entry == "close":
            e = i
            if (locked_up[i] if not short else locked_down[i]):
                blocked_entries += 1
                i += 1
                continue
            entry_px = c[i]
            start_j = i + 1
        else:
            e = i + 1
            if e >= n:
                pending_signal = dates[i]
                break
            if (locked_up[e] if not short else locked_down[e]):
                blocked_entries += 1
                i += 1
                continue
            entry_px = o[e]
            start_j = e        # 進場當天盤中也可能打到停損
        if entry_px <= 0:
            i += 1
            continue

        a0 = atr[i] if atr is not None else None
        init_stop = None
        if ec.stop == "atr":
            init_stop = entry_px - sign * ec.stop_atr * a0
        elif ec.stop == "pct" and ec.stop_pct > 0:
            init_stop = entry_px * (1 - sign * ec.stop_pct / 100.0)
        tp = entry_px * (1 + sign * ec.take_profit / 100.0) if ec.take_profit > 0 else None

        trail_stop = None
        extreme = entry_px          # 持有期間最高價（多）/最低價（空）
        exit_idx = None
        exit_px = None
        reason = ""
        pending_exit = None         # 收盤型出場或鎖死順延：下一個可成交日開盤出場

        for j in range(start_j, n):
            cant_trade = locked_down[j] if not short else locked_up[j]
            # 0) 順延中的出場
            if pending_exit is not None:
                if cant_trade:
                    continue
                exit_idx, exit_px, reason = j, o[j], pending_exit
                break

            # 1) 停損（初始 + 移動，取較嚴者）
            active, active_reason = init_stop, "停損"
            if trail_stop is not None and (active is None or sign * (trail_stop - active) > 0):
                active, active_reason = trail_stop, "移動停損"
            hit_stop = False
            if active is not None:
                if sign * (o[j] - active) <= 0 and not (j == e and ec.entry != "close"):
                    hit_stop, px = True, o[j]           # 跳空越過停損 → 開盤價
                elif sign * ((l[j] if not short else h[j]) - active) <= 0:
                    hit_stop, px = True, active
            if hit_stop:
                if cant_trade:
                    pending_exit = active_reason
                    continue
                exit_idx, exit_px, reason = j, px, active_reason
                break

            # 2) 停利
            if tp is not None:
                if sign * (o[j] - tp) >= 0 and not (j == e and ec.entry != "close"):
                    exit_idx, exit_px, reason = j, o[j], "停利"
                    break
                if sign * ((h[j] if not short else l[j]) - tp) >= 0:
                    exit_idx, exit_px, reason = j, tp, "停利"
                    break

            held = j - i
            # 3) 時間停損 / 天數到期（當日收盤）
            if ec.time_stop_days > 0 and held >= ec.time_stop_days:
                gain = sign * (c[j] / entry_px - 1)
                if gain < ec.time_stop_pct / 100.0:
                    if cant_trade:
                        pending_exit = "時間停損"
                        continue
                    exit_idx, exit_px, reason = j, c[j], "時間停損"
                    break
            if ec.max_hold > 0 and held >= ec.max_hold:
                if cant_trade:
                    pending_exit = "天數到期"
                    continue
                exit_idx, exit_px, reason = j, c[j], "天數到期"
                break

            # 4) 收盤型出場 → 隔日開盤
            if ma is not None and not np.isnan(ma[j]) and sign * (c[j] - ma[j]) < 0:
                pending_exit = f"{'破' if not short else '站上'}MA{ec.exit_ma}"
            elif ec.trail_low_days > 0:
                lb = max(e, j - ec.trail_low_days)
                if lb < j:
                    ref = l[lb:j].min() if not short else h[lb:j].max()
                    if sign * (c[j] - ref) < 0:
                        pending_exit = "跌破低點" if not short else "突破高點"

            # 5) 收盤後更新移動停損（只往有利方向移）
            extreme = max(extreme, h[j]) if not short else min(extreme, l[j])
            cand = None
            if ec.trail == "atr" and atr is not None and not np.isnan(atr[j]):
                cand = extreme - sign * ec.trail_atr * atr[j]
            elif ec.trail == "pct" and ec.trail_pct > 0:
                cand = extreme * (1 - sign * ec.trail_pct / 100.0)
            if cand is not None and (trail_stop is None or sign * (cand - trail_stop) > 0):
                trail_stop = cand

        def _rec(xi, xp, why, status):
            gross = sign * (xp / entry_px - 1)
            return {
                "signal_date":  dates[i],
                "entry_date":   dates[e],
                "entry_price":  _raw(entry_px, e),
                "exit_date":    dates[xi],
                "exit_price":   _raw(xp, xi),
                "gross_return": round(float(gross), 5),
                "return":       round(float(gross - cc.roundtrip), 5),
                "hold_days":    int(xi - i),
                "exit_reason":  why,
                "stop_price":   _raw(init_stop, e) if init_stop is not None else None,
                "tp_price":     _raw(tp, e) if tp is not None else None,
                "status":       status,
            }

        if exit_idx is None:
            open_trade = _rec(n - 1, c[n - 1], f"{pending_exit}（明日開盤出場）" if pending_exit else "持有中", "open")
            busy_until = n
            break
        trades.append(_rec(exit_idx, exit_px, reason, "closed"))
        # 出場當天之後才可再進場：隔日開盤模式 → 出場當天收盤的訊號可用；收盤進場 → 要等隔天
        busy_until = exit_idx - 1 if ec.entry != "close" else exit_idx
        i = max(i + 1, busy_until + 1)

    bh = None
    if first_eligible is not None and first_eligible < n - 1 and c[first_eligible] > 0:
        bh = float(c[n - 1] / c[first_eligible] - 1)
    info = {
        "first_date":      dates[first_eligible] if first_eligible is not None else None,
        "last_date":       dates[-1] if n else None,
        "buy_hold_return": round(bh, 5) if bh is not None else None,
        "pending_signal":  pending_signal,
        "blocked_entries": blocked_entries,
        "bars":            n,
    }
    return trades, open_trade, info


# ── 統計 ──────────────────────────────────────────────────────────────────────

def compute_stats(trades: list) -> dict:
    """只吃已平倉交易（未平倉另外顯示，不計入勝率/期望值）。"""
    closed = [t for t in trades if t.get("status", "closed") == "closed"]
    if not closed:
        return {"count": 0}
    # 依出場日排序，權益曲線 / 連虧才有意義
    closed = sorted(closed, key=lambda t: (t["exit_date"], t["entry_date"]))
    rets = [float(t["return"]) for t in closed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    loss_sum = -sum(losses)
    max_consec = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        max_consec = max(max_consec, cur)
    eq, peak, mdd = 1.0, 1.0, 0.0
    curve = []
    for t, r in zip(closed, rets):
        eq *= (1 + r)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        curve.append([t["exit_date"], round(eq, 4)])
    reasons: dict = {}
    for t in closed:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    srt = sorted(rets)
    return {
        "count":            len(closed),
        "win_rate":         round(len(wins) / len(rets), 4),
        "expectancy":       round(sum(rets) / len(rets), 5),
        "avg_return":       round(sum(rets) / len(rets), 5),   # 舊欄位名，同 expectancy
        "median_return":    round(srt[len(srt) // 2], 5),
        "avg_win":          round(avg_win, 5),
        "avg_loss":         round(avg_loss, 5),
        "payoff_ratio":     round(avg_win / -avg_loss, 3) if avg_loss < 0 else None,
        "profit_factor":    round(sum(wins) / loss_sum, 3) if loss_sum > 0 else None,
        "max_win":          round(max(rets), 5),
        "max_loss":         round(min(rets), 5),
        "max_consec_losses": max_consec,
        "max_drawdown":     round(mdd, 5),
        "total_return":     round(eq - 1, 5),
        "avg_hold_days":    round(sum(t["hold_days"] for t in closed) / len(closed), 1),
        "exit_reasons":     reasons,
        "equity_curve":     curve,
        "low_sample":       len(closed) < 10,
    }


def summary_sentence(stats: dict, info: dict, cost: float = DEFAULT_COST_ROUNDTRIP) -> str:
    """一句話結論，例如「過去 5 年 38 筆交易，每筆平均 +2.1%（已扣成本），勝過同期買進持有」"""
    n = stats.get("count", 0)
    span = _years_between(info.get("first_date"), info.get("last_date"))
    span_txt = f"過去 {span} 年" if span else "回測期間"
    if not n:
        return f"{span_txt}沒有任何完成的交易"
    exp = stats["expectancy"] * 100
    s = f"{span_txt} {n} 筆交易，每筆平均 {exp:+.2f}%（已扣成本）"
    bh = info.get("buy_hold_return")
    if bh is not None:
        tr = stats.get("total_return", 0)
        s += "，" + ("勝過" if tr > bh else "不如") + f"同期買進持有（策略累計 {tr*100:+.1f}% vs 持有 {bh*100:+.1f}%）"
    if stats.get("low_sample"):
        s += "；樣本太少，參考性低"
    return s


def _years_between(d1, d2):
    try:
        a = pd.Timestamp(str(d1))
        b = pd.Timestamp(str(d2))
        y = (b - a).days / 365.25
        return round(y, 1) if y >= 0.1 else None
    except Exception:
        return None
