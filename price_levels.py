"""
price_levels.py — 依使用者的看盤邏輯算關鍵價位（觀察清單、K 線、平地一聲雷策略共用）

使用者規則（2026-10-03 截圖手寫＋確認）：
- 壓力區：現價上方的前高（波段高點）由近到遠＝第一壓力、第二壓力…（「0 是底，1、2、3、4 是上面的壓力」）
- 平地一聲雷：上方盤整很久（90 天、區間 ≤15%）後帶量（≥ 20 日均量 2.5 倍）突破盤整上緣；
  漲一段後回檔，回檔幅度 ≤ 第一段漲幅的 0.618，
  目標價 ＝ 第一段高點 − 突破點（盤整上緣）＋ 回檔低點（例：30 − 10 + 25 = 45，上方沒有前高時用）
- 上漲模式（平地一聲雷突破後、均線多頭排列）：收盤跌破前一天低點出場
- 停損一般看：爆量 K 棒低點、波段低點、前低；附近有均線（如 60 日線）一起看
- 跌破爆量低點出場，之後站回就是假跌破
- 區間整理：5 日 > 10 日 > 20 日、底部一直墊高、但還沒過區間高 → 加入自選觀察
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

THUNDER_DEFAULTS = {"base_days": 90, "base_range": 0.15, "vol_mult": 2.5, "max_retrace": 0.618,
                    "breakout_within": 60}


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def pivots(values, k: int, kind: str) -> list:
    """波段高/低點：前後各 k 根都沒有更高（更低）的點。回傳 index 清單（最後 k 根不判斷）"""
    v = np.asarray(values, dtype=float)
    out = []
    # 平頭（同價）很常見：取同價的第一根（左邊嚴格、右邊可相等）
    for i in range(k, len(v) - k):
        left, right = v[i - k:i], v[i + 1:i + k + 1]
        if kind == "high" and v[i] > left.max() and v[i] >= right.max():
            out.append(i)
        elif kind == "low" and v[i] < left.min() and v[i] <= right.min():
            out.append(i)
    return out


def detect_thunder(df: pd.DataFrame, params: dict = None) -> Optional[dict]:
    """平地一聲雷：找最近一次「盤整 base_days 天、收盤區間 ≤ base_range，之後收盤帶量突破盤整上緣」，
    且突破發生在最近 breakout_within 根內、現價仍在盤整上緣之上。沒有就回 None。"""
    p = {**THUNDER_DEFAULTS, **(params or {})}
    n = len(df)
    nb = int(p["base_days"])
    if n < nb + 2:
        return None
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    v = df["volume"].values.astype(float)
    last = n - 1
    found = None
    for b in range(last, max(nb, 20, last - int(p["breakout_within"])) - 1, -1):
        base = c[b - nb:b]
        lo, hi = base.min(), base.max()
        if lo <= 0 or (hi - lo) / lo > p["base_range"]:
            continue
        avg20 = v[b - 20:b].mean()
        if c[b] > hi and avg20 > 0 and v[b] >= avg20 * p["vol_mult"]:
            found = (b, hi, lo, v[b] / avg20)
            break
    if not found:
        return None
    b, base_top, base_low, vol_ratio = found
    if c[last] <= base_top:
        return None                      # 跌回盤整區：突破失敗，不算
    # 第一段：突破後第一個波段高點（後面有回檔）；回檔低點＝它之後、價格再創高之前的最低點
    first_hi = next((i for i in pivots(h, 3, "high") if i > b), None)
    if first_hi is None:
        hi_idx = b + int(h[b:].argmax())
        high, pull_low, reclaimed = float(h[hi_idx]), None, False
    else:
        hi_idx = first_hi
        high = float(h[hi_idx])
        after = np.where(h[hi_idx + 1:] > high)[0]
        end = hi_idx + 1 + int(after[0]) if len(after) else last + 1
        pull_low = float(l[hi_idx + 1:end].min()) if end > hi_idx + 1 else None
        reclaimed = bool(len(after))     # 回檔後已越過第一段高點
    leg = high - base_top
    retrace = (high - pull_low) / leg if (pull_low is not None and leg > 0) else None
    target = None
    if retrace is not None and retrace <= p["max_retrace"] and pull_low > base_top * 0.97:
        target = high - base_top + pull_low
    # 階段
    ma5 = pd.Series(c).rolling(5).mean().values
    ma10 = pd.Series(c).rolling(10).mean().values
    ma20 = pd.Series(c).rolling(20).mean().values
    uptrend = bool(c[last] > ma5[last] > ma10[last] > ma20[last]) if not np.isnan(ma20[last]) else False
    if pull_low is None:
        stage = "攻擊中（突破後還沒回檔）"
    elif retrace is not None and retrace > p["max_retrace"]:
        stage = f"回檔過深（回檔 {retrace:.0%} > {p['max_retrace']:.1%}）"
    elif reclaimed:
        stage = f"回檔 {retrace:.0%} 不破、已越過第一段高點，往目標價前進"
    else:
        stage = f"回檔整理中（回檔 {retrace:.0%}，不破回檔低點才買）"
    return {
        "base_top": _r(base_top), "base_low": _r(base_low), "base_days": nb,
        "breakout_idx": int(b), "breakout_date": str(df["date"].iloc[b]),
        "breakout_vol_ratio": _r(vol_ratio, 1),
        "high": _r(high), "high_date": str(df["date"].iloc[hi_idx]),
        "pullback_low": _r(pull_low), "retrace": _r(retrace, 3),
        "target": _r(target), "stage": stage, "uptrend": uptrend,
        "exit_prev_low": _r(l[last]) if uptrend else None,   # 上漲模式：明天收盤跌破今天低點出場
    }


def _zones(highs_idx, h, price, tol=0.02):
    """把現價上方的波段高點合併成壓力區（相差 2% 內算同一區），由近到遠"""
    above = sorted(float(h[i]) for i in highs_idx if h[i] > price * 1.005)
    zones = []
    for x in above:
        if zones and x <= zones[-1]["high"] * (1 + tol):
            zones[-1]["high"] = max(zones[-1]["high"], x)
            zones[-1]["touches"] += 1
        else:
            zones.append({"low": x, "high": x, "touches": 1})
    return [{"low": _r(z["low"]), "high": _r(z["high"]), "touches": z["touches"]} for z in zones]


def compute_levels(df: pd.DataFrame, thunder_params: dict = None) -> dict:
    """回傳 {price, mode, pressure1, pressure2, target, target_method, stops, thunder, ma_near, notes}"""
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    n = len(df)
    if n < 30:
        return {"error": "K 線資料不足 30 根"}
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    v = df["volume"].values.astype(float)
    last = n - 1
    price = float(c[last])
    notes = []
    look = max(0, n - 250)                 # 約一年內的前高前低

    # 壓力區（現價上方的前高）
    ph = [i for i in pivots(h, 5, "high") if i >= look]
    zones = _zones(ph, h, price)
    p1 = zones[0] if zones else None
    p2 = zones[1] if len(zones) > 1 else None

    # 平地一聲雷
    th = detect_thunder(df, thunder_params)

    # 區間整理（5>10>20、底部墊高、還沒過區間高）
    ma = {k: pd.Series(c).rolling(k).mean().values for k in (5, 10, 20, 60)}
    pl3 = [i for i in pivots(l, 3, "low") if i >= n - 60]
    box_high = float(h[max(0, n - 20):].max())
    rising = len(pl3) >= 2 and all(l[pl3[j]] < l[pl3[j + 1]] for j in range(len(pl3) - 1))
    aligned = not np.isnan(ma[20][last]) and ma[5][last] > ma[10][last] > ma[20][last]
    consolidating = aligned and rising and price < box_high * 0.995

    if th and th["uptrend"]:
        mode = "平地一聲雷・上漲模式"
    elif th:
        mode = f"平地一聲雷・{th['stage']}"
    elif consolidating:
        mode = "區間整理（底部墊高，待突破區間高）"
        if not p1 or box_high < p1["low"]:
            p2, p1 = p1, {"low": _r(box_high), "high": _r(box_high), "touches": 1}
        notes.append(f"還沒過區間高 {box_high:.2f}：可先加入自選觀察，帶量突破再進")
    else:
        mode = "一般"

    # 目標價
    target, method = None, ""
    if th and th["target"]:
        target, method = th["target"], f"等幅：高點 {th['high']} − 突破點 {th['base_top']} ＋ 回檔低點 {th['pullback_low']}"
    elif p2:
        target, method = p2["low"], "第二壓力區"
    elif p1:
        target, method = p1["low"], "第一壓力區（上方只有一個前高）"
    else:
        # 上方沒有前高：用最近一段的等幅（高點 − 起漲低點 ＋ 回檔低點）
        hi_idx = max(range(look, n), key=lambda i: h[i])
        if hi_idx < last:
            start = float(l[max(0, hi_idx - 60):hi_idx + 1].min())
            pull = float(l[hi_idx + 1:].min())
            leg = h[hi_idx] - start
            if leg > 0 and (h[hi_idx] - pull) / leg <= 0.618:
                target = _r(h[hi_idx] - start + pull)
                method = f"無前高等幅：高點 {h[hi_idx]:.2f} − 起漲 {start:.2f} ＋ 回檔低點 {pull:.2f}"
        if target is None:
            method = "上方無前高、也還沒有回檔可量測"

    # 停損：爆量低點、波段低點、前低
    stops = {}
    avg20 = pd.Series(v).rolling(20).mean().shift(1).values
    for i in range(last, max(20, n - 60) - 1, -1):
        if avg20[i] > 0 and v[i] >= avg20[i] * 2 and l[i] < price:
            stops["volume_low"] = {"price": _r(l[i]), "date": str(df["date"].iloc[i]), "idx": int(i),
                                   "label": f"爆量 K 棒低點（{v[i] / avg20[i]:.1f} 倍量）"}
            break
    lows = [i for i in pivots(l, 3, "low") if l[i] < price and i >= look]
    if lows:
        i1 = lows[-1]
        stops["swing_low"] = {"price": _r(l[i1]), "date": str(df["date"].iloc[i1]), "label": "波段低點"}
        older = [i for i in lows if i < i1 and l[i] < l[i1]]
        if older:
            i2 = older[-1]
            stops["prev_low"] = {"price": _r(l[i2]), "date": str(df["date"].iloc[i2]), "label": "前低"}
    if th and th["exit_prev_low"]:
        stops["uptrend_exit"] = {"price": th["exit_prev_low"], "date": str(df["date"].iloc[last]),
                                 "label": "上漲模式：收盤跌破這天低點出場"}

    # 附近均線（±3% 內）
    ma_near = []
    for k, name in ((20, "20 日線"), (60, "60 日線")):
        m = ma[k][last]
        if not np.isnan(m) and abs(price / m - 1) <= 0.03:
            ma_near.append({"name": name, "price": _r(m)})
    if ma_near:
        notes.append("附近有 " + "、".join(f"{x['name']} {x['price']}" for x in ma_near) + "，停損一起看")

    # 假跌破：昨天收盤跌破爆量低點、今天站回
    vl = stops.get("volume_low")
    if vl and vl["idx"] < last - 1 and c[last - 1] < vl["price"] <= c[last]:
        notes.append(f"昨天跌破爆量低點 {vl['price']}、今天站回 → 假跌破")

    return {
        "price": _r(price), "date": str(df["date"].iloc[last]), "mode": mode,
        "pressure1": p1, "pressure2": p2, "zones": zones[:4],
        "target": _r(target), "target_method": method,
        "upside_pct": _r((target / price - 1) * 100, 1) if target else None,
        "stops": stops, "thunder": th, "ma_near": ma_near, "notes": notes,
    }
