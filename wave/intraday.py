"""B75／B76 分 K 分析（PLAN-B75 §4、PLAN-B76 §2）：bars5 → 30／60 分 K → 各自的數浪、支撐壓力、轉折點
- 60 分 K：θ＝max(0.5%, m × 60 分 K ATR% 近 60 根中位數)，m 由 stats.json intraday 覆蓋（B75 校準 m＝2）
- 30 分 K（B76）：自己的 θ＝max(0.4%, m30 × 30 分 K ATR% 近 60 根中位數)，m30 由 stats.json intraday30 覆蓋（B76 校準 m30＝2）
- 只有收完的 K 棒參與轉折確認；盤中最後一根（partial）只當現價"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from . import engine as E, futdata as FD, keylevel as KL, levels as LV

KEEP_DAYS = 40            # 分 K 用近 40 天（夠 ZigZag／ATR 中位數）
SHOW = {60: 260, 30: 360}  # 回給前端的根數
# 每個分 K 週期的設定：級數、價位窗口、k3 回看根數、顯示名稱
TF = {60: {"deg": "intra", "cfg": E.INTRA, "win": LV.ULTRA_WIN, "k3_look": LV.ULTRA_K3_LOOK, "tfn": "60 分"},
      30: {"deg": "intra30", "cfg": E.INTRA30, "win": 0.02, "k3_look": 120, "tfn": "30 分"}}


def set_params(st: dict):
    for key, cfg in (("intraday", E.INTRA), ("intraday30", E.INTRA30)):
        x = (st or {}).get(key) or {}
        if x.get("m"):
            cfg["m"] = float(x["m"])
        if x.get("floor"):
            cfg["floor"] = float(x["floor"])


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


def theta(h, l, c, cfg: Optional[dict] = None) -> np.ndarray:
    cfg = cfg or E.INTRA
    ap = E.atr_pct_median(h, l, c)
    f, m = cfg["floor"], cfg["m"]
    return np.maximum(f, m * np.where(np.isnan(ap), f / m, ap))


def _arr(bs):
    return tuple(np.array([b[k] for b in bs], dtype=float) for k in ("open", "high", "low", "close"))


def analyze_tf(tf: int, bs: list, price: Optional[float], daily: dict, trend: int = 0) -> dict:
    """單一分 K 週期：自己的 θ 數浪＋支撐壓力＋轉折點候選（只用收完的 K 棒）"""
    p = TF[tf]
    done = [b for b in bs if not b.get("partial")]
    if len(done) < 40:
        return {"ok": False, "note": f"{p['tfn']} K 資料還不夠（剛開始累積，或還在回補）"}
    o, h, l, c = _arr(done)
    th = theta(h, l, c, p["cfg"])
    piv = E.zigzag(h, l, th)
    t = len(c) - 1
    an = E.analyze(o, h, l, c, p["deg"], t=t, trend=trend, piv=piv)
    times = [b["time"] for b in done]
    lab = lambda i: FD.tw_dt(times[i]).strftime("%m/%d %H:%M")
    atr_v = float(E.atr(h, l, c)[-1])
    px = float(price) if price else float(c[-1])
    lv = LV.build_ultra(h, l, c, t, an, atr_v, px, label=lab, daily=daily, win=p["win"], k3_look=p["k3_look"], tfn=p["tfn"])
    cands = KL.candidates(an, h, l, c, t, atr_v, price=px, k=3, look=p["k3_look"])
    return {"ok": True, "an": an, "times": times, "atr": atr_v, "theta": float(th[-1]), "levels": lv, "cands": cands,
            "hlc": (h, l, c), "piv": piv}           # B79 多層浪名的「浪名演變」要用（只在伺服器端，不進快照）


def analyze(sym: str, b60: list, b30: list, price: Optional[float], daily: dict, trend: int = 0) -> dict:
    """60 分 K（out 本身，跟 B75 相容）＋30 分 K（out['m30']，B76 各自的 θ）"""
    out = analyze_tf(60, b60, price, daily, trend)
    out["m30"] = analyze_tf(30, b30, price, daily, trend)
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


def wave_out(a: dict) -> dict:
    """analyze_tf 結果 → 快照 waves 的格式（時間＝epoch）"""
    an, times = a["an"], a["times"]
    f = an.get("fib")
    return {"label": an["label"], "pivots": pts(an["pivots"][-20:], times),
            "tentative": pts([an["tentative"]], times)[0] if an.get("tentative") else None,
            "primary": with_times(an.get("primary"), times), "alternate": with_times(an.get("alternate"), times),
            "fib": None if not f else {**f, "from": {**f["from"], "time": int(times[f["from"]["i"]])},
                                       "to": {**f["to"], "time": int(times[f["to"]["i"]])}},
            "time_based": True, "maybe_pivot": None}
