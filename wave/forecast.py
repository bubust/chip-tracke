"""B74 過去相似狀態（PLAN-B74 §4.7）：研究 R6 與網站共用。
第 t 天只用「t − 期間」以前、之後報酬已經知道的日子當樣本；條件依事先排好的順序，不夠 40 筆就從最後一個拿掉；
全部拿掉＝全部歷史（標 fallback）。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

MIN_N = 40


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n <= 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, c - w), 4), round(min(1.0, c + w), 4))


def analog(feat: pd.DataFrame, t: int, conds: list, horizon: int = 20, min_n: int = MIN_N,
           start: int = 0) -> dict:
    """conds：[欄名, ...]（離散值）。回傳 {n, p_up, ci, median, q20, q80, used, dropped, fallback}"""
    col = f"fwd{horizon}"
    last = t - horizon                       # 這天以前的 fwd 才已知
    if last < start:
        return {"n": 0, "fallback": True, "used": [], "dropped": list(conds)}
    base = feat.iloc[start:last + 1]
    y = base[col].values.astype(float)
    ok = ~np.isnan(y)

    def _val(cname):
        v = feat[cname].iat[t] if cname in feat else np.nan
        try:
            return None if v is None or np.isnan(float(v)) else float(v)
        except (TypeError, ValueError):
            return v

    unavailable = [cn for cn in conds if _val(cn) is None]          # 今天沒有這個條件的資料 → 只跳過它
    used = [cn for cn in conds if cn not in unavailable]
    dropped = []
    while True:
        m = ok.copy()
        for cname in used:
            m &= (base[cname].values == _val(cname))
        if m.sum() >= min_n or not used:
            break
        dropped.insert(0, used.pop())
    yy = y[m]
    n = int(len(yy))
    if n == 0:
        return {"n": 0, "fallback": True, "used": used, "dropped": dropped, "unavailable": unavailable}
    k = int((yy > 0).sum())
    return {"n": n, "p_up": round(k / n, 4), "ci": wilson(k, n), "median": round(float(np.median(yy)), 5),
            "q20": round(float(np.quantile(yy, 0.2)), 5), "q80": round(float(np.quantile(yy, 0.8)), 5),
            "used": used, "dropped": dropped, "unavailable": unavailable, "fallback": not used}
