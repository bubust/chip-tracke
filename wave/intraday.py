"""B75 超短線（PLAN-B75 §4）：bars5 → 30／60 分 K → 60 分 K 數浪、超短線支撐壓力、轉折點
- θ＝max(下限, m × 60 分 K ATR% 近 60 根中位數)（m 由 stats.json intraday 覆蓋）；30 分 K 用「上一根已收完的 60 分 K」的 θ（同一套轉折、因果）
- 只有收完的 K 棒參與轉折確認；盤中最後一根（partial）只當現價"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from . import engine as E, futdata as FD, keylevel as KL, levels as LV

KEEP_DAYS = 40            # 分 K 用近 40 天（夠 ZigZag／ATR 中位數）
SHOW = {60: 260, 30: 360}  # 回給前端的根數


def set_params(st: dict):
    x = (st or {}).get("intraday") or {}
    if x.get("m"):
        E.INTRA["m"] = float(x["m"])
    if x.get("floor"):
        E.INTRA["floor"] = float(x["floor"])


def bars(sym: str, tf: int, live_rows: Optional[list] = None, now_ts: Optional[float] = None) -> list:
    """資料庫 5 分 K（近 40 天）＋鉅亨即時（同一根以即時為準）→ tf 分 K；最後一根沒收完標 partial"""
    now_ts = time.time() if now_ts is None else now_ts
    rows = {r[0]: r for r in FD.load_bars5(sym, int(now_ts - KEEP_DAYS * 86400))}
    for r in live_rows or []:
        rows[r[0]] = r
    out = FD.agg_bars([rows[k] for k in sorted(rows)], sym, tf)
    if out:
        last = out[-1]
        s = FD.session_of(sym, last["time"])
        end = min(last["time"] + tf * 60, s[2]) if s else last["time"] + tf * 60
        if now_ts < end:
            last["partial"] = True
    return out


def theta(h, l, c) -> np.ndarray:
    ap = E.atr_pct_median(h, l, c)
    f, m = E.INTRA["floor"], E.INTRA["m"]
    return np.maximum(f, m * np.where(np.isnan(ap), f / m, ap))


def _arr(bs):
    return tuple(np.array([b[k] for b in bs], dtype=float) for k in ("open", "high", "low", "close"))


def analyze(sym: str, b60: list, b30: list, price: Optional[float], daily: dict, trend: int = 0) -> dict:
    """60 分 K：數浪＋超短線價位＋轉折點；30 分 K：同一組 θ 的轉折（圖用）"""
    out = {"ok": False}
    done60 = [b for b in b60 if not b.get("partial")]
    if len(done60) < 40:
        out["note"] = "60 分 K 資料還不夠（剛開始累積，或還在回補）"
        return out
    o, h, l, c = _arr(done60)
    th = theta(h, l, c)
    piv = E.zigzag(h, l, th)
    t = len(c) - 1
    an = E.analyze(o, h, l, c, "intra", t=t, trend=trend, piv=piv)
    times = [b["time"] for b in done60]
    lab = lambda i: FD.tw_dt(times[i]).strftime("%m/%d %H:%M")
    atr60 = float(E.atr(h, l, c)[-1])
    px = float(price) if price else float(c[-1])
    lv = LV.build_ultra(h, l, c, t, an, atr60, px, label=lab, daily=daily)
    cands = KL.candidates(an, h, l, c, t, atr60, price=px, k=3, look=LV.ULTRA_K3_LOOK)
    out.update(ok=True, an=an, times=times, atr=atr60, theta=float(th[-1]), levels=lv, cands=cands)
    # 30 分 K：用上一根收完的 60 分 K θ
    done30 = [b for b in b30 if not b.get("partial")]
    if len(done30) >= 40:
        o3, h3, l3, c3 = _arr(done30)
        t60 = np.array(times)
        th30 = np.empty(len(done30))
        for i, b in enumerate(done30):
            k = int(np.searchsorted(t60, b["time"], side="right")) - 2
            th30[i] = th[k] if k >= 0 else th[0]
        piv30 = E.zigzag(h3, l3, th30)
        conf, tent = E.state_at(piv30, h3, l3, len(c3) - 1)
        out["tf30"] = {"times": [b["time"] for b in done30], "pivots": conf, "tentative": tent}
    return out


def pts(lst: list, times: list) -> list:
    return [{"time": int(times[p["i"]]), "p": round(float(p["p"]), 2), "t": p["t"],
             "confirmed": None if p.get("ci") is None else int(times[p["ci"]])} for p in lst if p]


def with_times(cnt: Optional[dict], times: list) -> Optional[dict]:
    if not cnt:
        return None
    x = dict(cnt)
    x["labels"] = [{**y, "time": int(times[y["i"]])} for y in x.get("labels", [])]
    return x
