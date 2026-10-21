"""B75 轉折點（PLAN-B75 §2）：取代離現價太遠的「劇本失效點」。研究（research/futures/keylevel.py）與網站共用。
目前這一段的方向：進行中的極值是高點 → 上漲段（看下方「轉弱點」）；是低點 → 下跌段（看上方「轉強點」）
- K1 波浪失效點：該級數主要劇本的 invalid
- K2 這一段的起點：最後一個確認的 ZigZag 轉折
- K3 最近的反向小轉折：這一段開始以後確認的 k3 轉折（左右各 k 根；第 i 根到 i+k 收完才算），
  上漲段取現價下方最近的低點、下跌段取現價上方最近的高點，離現價 ≥ 0.5 ATR；找不到退回 K2
純函式：只用第 t 根（含）以前收完的 K 棒"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from . import levels as LV

RULES = ("K1", "K2", "K3")
MIN_ATR = 0.5


def leg(an: dict, t: int) -> tuple:
    """(方向 +1 上漲段／−1 下跌段, 這一段起點 {i,p,t}) ；沒有轉折 → (0, None)"""
    piv = an.get("pivots") or []
    tent = an.get("tentative")
    if not piv:
        return 0, None
    last = piv[-1]
    if tent:
        return (1 if tent["t"] == "H" else -1), last
    # 最後一個確認點就在 t（剛確認）：新的一段才開始，方向跟它相反
    return (-1 if last["t"] == "H" else 1), last


def k3_points(h, l, t: int, start_i: int, k: int = 3, look: int = 60) -> list:
    """第 t 根收完時已確認的 k3 轉折，只取 i ≥ start_i（這一段開始以後）"""
    return [p for p in LV.k3_pivots(h, l, t, look=look, k=k) if p["i"] >= start_i and p["ci"] <= t]


def candidates(an: dict, h, l, c, t: int, atr_v: float, price: Optional[float] = None, k: int = 3, look: int = 60) -> dict:
    """三種候選 {K1, K2, K3: {price, side}}；side＝'below'（跌破＝轉弱）或 'above'（站上＝轉強）"""
    price = float(c[t]) if price is None else float(price)
    d, start = leg(an, t)
    out = {"dir": d}
    prim = an.get("primary")
    if prim and prim.get("invalid") is not None:
        out["K1"] = {"price": float(prim["invalid"]), "side": prim.get("invalid_side") or "below"}
    if start is None or d == 0:
        return out
    side = "below" if d > 0 else "above"
    out["K2"] = {"price": float(start["p"]), "side": side}
    gap = MIN_ATR * atr_v if atr_v and math.isfinite(atr_v) else 0.0
    pts = k3_points(h, l, t, start["i"], k=k, look=look)
    if d > 0:
        cand = [p["p"] for p in pts if p["t"] == "L" and p["p"] <= price - gap]
        best = max(cand) if cand else None
    else:
        cand = [p["p"] for p in pts if p["t"] == "H" and p["p"] >= price + gap]
        best = min(cand) if cand else None
    out["K3"] = {"price": float(best), "side": side, "fallback": False} if best is not None else {**out["K2"], "fallback": True}
    return out


def pick(cands: dict, rule: str, price: float, atr_v: float, wave_invalid: Optional[dict] = None) -> Optional[dict]:
    """把選中的規則轉成網站用的格式；wave_invalid＝K1（顯示成「最後防線」小字）"""
    x = cands.get(rule) or cands.get("K2") or cands.get("K1")
    if not x:
        return None
    p = x["price"]
    out = {"rule": rule if cands.get(rule) else ("K2" if cands.get("K2") else "K1"),
           "price": round(p, 0), "side": x["side"], "kind": "轉弱點" if x["side"] == "below" else "轉強點",
           "dist_pct": round((p / price - 1) * 100, 2) if price else None,
           "dist_atr": round(abs(p - price) / atr_v, 2) if atr_v and math.isfinite(atr_v) and atr_v > 0 else None,
           "fallback": bool(x.get("fallback")), "dir": cands.get("dir", 0),
           # 這一段中間沒有反向小轉折 → 轉折點就是這一段的起點（畫面要說明為什麼比較遠）
           "leg_start": bool(cands.get("K2") and abs(cands["K2"]["price"] - p) < 0.5)}
    k1 = wave_invalid if wave_invalid is not None else cands.get("K1")
    if k1 and abs(k1["price"] - p) > 0.5:
        out["wave_invalid"] = round(k1["price"], 0)
        out["wave_invalid_side"] = k1["side"]
        out["wave_invalid_pct"] = round((k1["price"] / price - 1) * 100, 2) if price else None
    return out


# ── 研究用：碰到之後有沒有「延續」（PLAN §2.3）────────────────────────────────
def follow_through(h, l, c, atr, X: float, side: str, t: int, H: int, brk: float = 0.5, more: float = 1.0):
    """t 之後 H 根內：先找收盤穿過 X 0.5 ATR（確認跌破／突破）；之後回到 X 之前再往同方向走到 X ∓ (0.5+1) ATR → 1，先回到 X → 0。
    沒有確認穿過 → None（不算事件）；穿過後 H 根內兩邊都沒到 → None"""
    n = len(c)
    end = min(n, t + 1 + H)
    A = atr[t]
    if not np.isfinite(A) or A <= 0:
        return None
    b = None
    for u in range(t + 1, end):
        if (side == "below" and c[u] < X - brk * A) or (side == "above" and c[u] > X + brk * A):
            b = u
            break
    if b is None:
        return None
    goal = X - (brk + more) * A if side == "below" else X + (brk + more) * A
    for u in range(b + 1, min(n, b + 1 + H)):
        if side == "below":
            if l[u] <= goal:
                return 1
            if h[u] >= X:
                return 0
        else:
            if h[u] >= goal:
                return 1
            if l[u] <= X:
                return 0
    return None
