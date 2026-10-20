"""B74 研究（PLAN-B74 §5）：R1 費波那契、R2 支撐壓力類型、R3 波浪狀態、R4 籌碼、R5 國際、R6 相似狀態校準。
資料：research/wave/data（fetch.py 下載）。輸出 research/wave/results/*.json、REPORT.md，以及網站讀的 wave/stats.json。
用法：.venv/Scripts/python research/wave/run.py
判準事先寫在 PLAN-B74 §5，這裡只照做；沒通過照實標。"""
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from wave import engine as E, levels as LV, features as F, forecast as FC   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
IS_END, OOS_START = "2015-12-31", "2016-01-01"
CH_IS_END, CH_OOS_START = "2021-12-31", "2022-01-01"
PERIODS = [("2000-01-01", "2007-12-31"), ("2008-01-01", "2015-12-31"), ("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")]
CH_PERIODS = PERIODS[2:]
N_BOOT = 2000
N_PLACEBO = 5
HOLD_ATR, BREAK_ATR, MAX_AFTER = 1.0, 0.5, 20
RNG = np.random.default_rng(20261020)


# ── 共用統計 ─────────────────────────────────────────────────────────────────
def month_of(dates):
    return np.array([str(d)[:7] for d in dates])


def block_boot(stat_fn, groups: np.ndarray, n=N_BOOT):
    """月份 block bootstrap：抽月份（放回）→ 重算統計量。回傳 (估計, 下限, 上限, 雙尾 p)"""
    ug = np.unique(groups)
    idx_by = {g: np.where(groups == g)[0] for g in ug}
    est = stat_fn(np.arange(len(groups)))
    vals = []
    for _ in range(n):
        pick = RNG.choice(ug, size=len(ug), replace=True)
        ii = np.concatenate([idx_by[g] for g in pick]) if len(pick) else np.array([], dtype=int)
        v = stat_fn(ii)
        if v is not None and np.isfinite(v):
            vals.append(v)
    if not vals or est is None or not np.isfinite(est):
        return est, None, None, None
    vals = np.array(vals)
    lo, hi = np.quantile(vals, [0.025, 0.975])
    p = 2 * min((vals <= 0).mean(), (vals >= 0).mean())
    return float(est), float(lo), float(hi), float(min(1.0, max(p, 1.0 / n)))


def bh(pvals: dict) -> dict:
    """Benjamini–Hochberg 校正：{key: p} → {key: q}"""
    items = [(k, p) for k, p in pvals.items() if p is not None]
    items.sort(key=lambda x: x[1])
    m = len(items)
    q = {}
    prev = 1.0
    for rank in range(m, 0, -1):
        k, p = items[rank - 1]
        prev = min(prev, p * m / rank)
        q[k] = prev
    return q


def r4(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 4)


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load():
    tw = pd.read_csv(os.path.join(DATA, "TWII.csv")).dropna(subset=["o", "h", "l", "c"])
    tw = tw[(tw.h >= tw.l) & (tw.c > 0)].reset_index(drop=True)
    sox = pd.read_csv(os.path.join(DATA, "SOX.csv"))
    inst = pd.read_csv(os.path.join(DATA, "fm_inst.csv"))
    fut = pd.read_csv(os.path.join(DATA, "fm_fut.csv"))
    mg = pd.read_csv(os.path.join(DATA, "fm_margin.csv"))
    chips = F.chips_from_finmind(inst, fut, mg)
    return tw, sox, chips


# ── 事件評估（R1b、R2 共用；PLAN §5「守住」定義）──────────────────────────────
def eval_level(h, l, c, atr, X, side, start, max_wait):
    """start 起（含）第一次碰到 → (碰到那天, 1 守住／0 跌破／None 20 天沒結果)；沒碰到 (None, None)"""
    n = len(c)
    end = min(n, start + max_wait)
    if start >= end:
        return None, None
    seg = l[start:end] <= X if side == "S" else h[start:end] >= X
    if not seg.any():
        return None, None
    t = start + int(np.argmax(seg))
    A = atr[t]
    if not np.isfinite(A) or A <= 0:
        return t, None
    if side == "S":
        if c[t] < X - BREAK_ATR * A:
            return t, 0
        for u in range(t + 1, min(n, t + 1 + MAX_AFTER)):
            if c[u] < X - BREAK_ATR * A:
                return t, 0
            if h[u] >= X + HOLD_ATR * A:
                return t, 1
    else:
        if c[t] > X + BREAK_ATR * A:
            return t, 0
        for u in range(t + 1, min(n, t + 1 + MAX_AFTER)):
            if c[u] > X + BREAK_ATR * A:
                return t, 0
            if l[u] <= X - HOLD_ATR * A:
                return t, 1
    return t, None


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    tw, sox, chips = load()
    dates = tw.date.astype(str).values
    o, h, l, c = (tw[k].values.astype(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    atr = E.atr(h, l, c)
    ma = {k: pd.Series(c).rolling(k).mean().values for k in LV.MA_LIST}
    trend = np.where(np.isnan(ma[240]), 0, np.where(c > ma[240], 1, -1))
    period_of = lambda d: "IS" if d <= IS_END else "OOS"
    piv = {deg: E.zigzag(h, l, E.thresholds(h, l, c, deg)) for deg in E.DEGREES}
    print("pivots", {k: len(v) for k, v in piv.items()}, f"{time.time() - t0:.0f}s")

    # ── 每天的數浪（R3 用、R2 波浪目標用、覆蓋率）────────────────────────────
    START = 260
    wstate = {deg: [None] * n for deg in E.DEGREES}
    nseg = {deg: [0] * n for deg in E.DEGREES}
    targets_by_day = defaultdict(list)
    for deg in E.DEGREES:
        for t in range(START, n):
            conf, tent = E.state_at(piv[deg], h, l, t)
            pts = conf + ([tent] if tent else [])
            cnt = E.count_waves(pts, trend=int(trend[t]))
            p, _ = E.primary_alternate(cnt)
            if p:
                wstate[deg][t] = f"{p['kind'][:3]}{'+' if p['dir'] > 0 else '-'}:{p['current']}"
                nseg[deg][t] = len(p["labels"]) - 1
                if deg in ("mid", "big"):
                    for x in p["targets"]:
                        if x["kind"] == "end":
                            targets_by_day[t].append((deg, x["price"]))
    coverage = {deg: {"any": round(sum(1 for x in wstate[deg][START:] if x) / (n - START), 4),
                      "ge3_segments": round(sum(1 for x in nseg[deg][START:] if x >= 3) / (n - START), 4)}
                for deg in E.DEGREES}
    print("coverage", coverage, f"{time.time() - t0:.0f}s")

    # ── 事件 ────────────────────────────────────────────────────────────────
    events = []   # dict(type, a, X, side, start, max_wait, ratio?)

    def add(typ, a, X, start, max_wait, **kw):
        if a < START or a >= n - 1 or not np.isfinite(X) or X <= 0:
            return
        side = "S" if c[a] > X else "R"
        events.append(dict(type=typ, a=a, X=float(X), side=side, start=start, max_wait=max_wait, **kw))

    seen = set()
    for deg in E.DEGREES:
        P = piv[deg]
        for j, p in enumerate(P):
            if (p["i"], p["t"]) not in seen:
                seen.add((p["i"], p["t"]))
                add("pivot", p["ci"], p["p"], p["ci"] + 1, 120)
            if j >= 1:
                A, B = P[j - 1]["p"], p["p"]
                nxt = P[j + 1]["ci"] if j + 1 < len(P) else n
                mw = max(1, min(120, nxt - p["ci"]))
                for r in LV.ZONE_FIB:
                    add("fib", p["ci"], B - r * (B - A), p["ci"] + 1, mw, ratio=r, deg=deg)
                for r in E.CTRL_RET:
                    add("fib_ctrl", p["ci"], B - r * (B - A), p["ci"] + 1, mw, ratio=r, deg=deg)
    for t in range(START, n):                                   # 近期高低點（k=3，60 天內）
        i = t - 3
        if i - 3 < 0:
            continue
        if h[i] > h[i - 3:i].max() and h[i] >= h[i + 1:i + 4].max():
            add("pivot_k3", t, h[i], t + 1, 57)
        if l[i] < l[i - 3:i].min() and l[i] <= l[i + 1:i + 4].min():
            add("pivot_k3", t, l[i], t + 1, 57)
    last_tg = {}
    for t in range(START, n):                                   # 波浪目標：新出現的才算一個事件
        for deg, X in targets_by_day.get(t, []):
            key = (deg, round(X / max(atr[t], 1) / 0.5))
            if key in last_tg and t - last_tg[key] < 120:
                continue
            last_tg[key] = t
            add("target", t, X, t + 1, 120, deg=deg)
    # 動態：均線、整數關卡——前 5 天收盤都在同一邊、今天碰到
    for t in range(START + 5, n):
        prev = c[t - 5:t]
        for k in LV.MA_LIST:
            m = ma[k]
            if np.isnan(m[t - 5:t + 1]).any():
                continue
            if (prev > m[t - 5:t]).all() and l[t] <= m[t]:
                events.append(dict(type=f"ma{k}", a=t - 1, X=float(m[t]), side="S", start=t, max_wait=1))
            elif (prev < m[t - 5:t]).all() and h[t] >= m[t]:
                events.append(dict(type=f"ma{k}", a=t - 1, X=float(m[t]), side="R", start=t, max_wait=1))
        step = LV.round_step(c[t - 1])
        below = math.floor(c[t - 1] / step) * step
        above = below + step
        if (prev > below).all() and l[t] <= below:
            events.append(dict(type="round", a=t - 1, X=float(below), side="S", start=t, max_wait=1))
        if (prev < above).all() and h[t] >= above:
            events.append(dict(type="round", a=t - 1, X=float(above), side="R", start=t, max_wait=1))
    print("events", len(events), f"{time.time() - t0:.0f}s")

    # 評估＋重疊（multi）標記
    piv_all = sorted({(p["ci"], p["p"]) for deg in E.DEGREES for p in piv[deg]})
    piv_ci = np.array([x[0] for x in piv_all])
    piv_p = np.array([x[1] for x in piv_all])
    rows = []
    for ev in events:
        t, res = eval_level(h, l, c, atr, ev["X"], ev["side"], ev["start"], ev["max_wait"])
        if t is None or res is None:
            continue
        a = ev["a"]
        tol = 0.5 * atr[a] if np.isfinite(atr[a]) else 0
        cats = {LV.CATEGORY.get(ev["type"], ev["type"])}
        for k in LV.MA_LIST:
            if np.isfinite(ma[k][a]) and abs(ma[k][a] - ev["X"]) <= tol:
                cats.add("ma")
        step = LV.round_step(c[a])
        if abs(round(ev["X"] / step) * step - ev["X"]) <= tol:
            cats.add("round")
        live = (piv_ci <= a) & (piv_ci >= a - 500)
        if np.any(np.abs(piv_p[live] - ev["X"]) <= tol):
            cats.add("pivot")
        rows.append(dict(type=ev["type"], a=a, t=t, X=ev["X"], side=ev["side"], hold=res,
                         date=dates[t], ratio=ev.get("ratio"), deg=ev.get("deg"),
                         dist=(c[a] - ev["X"]) / atr[a] if atr[a] > 0 else np.nan, max_wait=ev["max_wait"],
                         multi=len(cats) >= 2))
    ev_df = pd.DataFrame(rows)
    # multi：同一天、0.5 ATR 內只算一次
    mm = ev_df[ev_df.multi].copy()
    mm["bucket"] = (mm.X / np.maximum(atr[mm.t.values], 1) / 0.5).round()
    mm = mm.drop_duplicates(["t", "bucket"]).drop(columns="bucket")
    mm["type"] = "multi"
    ev_df = pd.concat([ev_df[ev_df.type != "multi"], mm], ignore_index=True)
    print("evaluated", len(ev_df), f"{time.time() - t0:.0f}s")

    # 隨機價位對照：同一個距離（ATR 倍數）、隨機日子、同樣的等待天數（動態的給 20 天）
    pl_rows = []
    valid_days = np.where(np.isfinite(atr) & (np.arange(n) >= START) & (np.arange(n) < n - 2))[0]
    is_days = valid_days[dates[valid_days] <= IS_END]
    oos_days = valid_days[dates[valid_days] > IS_END]
    for r in ev_df.itertuples():
        pool = is_days if r.date <= IS_END else oos_days
        mw = r.max_wait if r.max_wait > 1 else 20
        for a2 in RNG.choice(pool, size=N_PLACEBO, replace=True):
            X2 = c[a2] - r.dist * atr[a2]
            side2 = "S" if c[a2] > X2 else "R"
            t2, res2 = eval_level(h, l, c, atr, X2, side2, a2 + 1, mw)
            if t2 is None or res2 is None:
                continue
            pl_rows.append(dict(type=r.type, t=t2, date=dates[t2], hold=res2))
    pl_df = pd.DataFrame(pl_rows)
    print("placebo", len(pl_df), f"{time.time() - t0:.0f}s")

    pvals = {}
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "data_end": dates[-1], "data_start": dates[0],
           "coverage": coverage, "calibration": {k: {"m": v["m"], "floor": v["floor"]} for k, v in E.DEGREES.items()}}

    def hold_test(real: pd.DataFrame, plac: pd.DataFrame):
        """real − placebo 守住率；月份 block（兩邊一起抽月份）"""
        res = {}
        for per, (d0, d1) in {"IS": ("2000", IS_END), "OOS": (OOS_START, "2099")}.items():
            R = real[(real.date >= d0) & (real.date <= d1)]
            Pp = plac[(plac.date >= d0) & (plac.date <= d1)]
            if len(R) < 10 or len(Pp) < 10:
                res[per] = {"n": int(len(R))}
                continue
            allg = np.r_[month_of(R.date), month_of(Pp.date)]
            isreal = np.r_[np.ones(len(R)), np.zeros(len(Pp))].astype(bool)
            y = np.r_[R.hold.values, Pp.hold.values].astype(float)

            def st(ii, y=y, isreal=isreal):
                a_, b_ = ii[isreal[ii]], ii[~isreal[ii]]
                if len(a_) == 0 or len(b_) == 0:
                    return np.nan
                return y[a_].mean() - y[b_].mean()
            est, lo, hi, p = block_boot(st, allg)
            res[per] = {"n": int(len(R)), "rate": r4(R.hold.mean()), "placebo": r4(Pp.hold.mean()), "n_placebo": int(len(Pp)),
                        "diff": r4(est), "ci": [r4(lo), r4(hi)], "p": r4(p)}
        subs = []
        for d0, d1 in PERIODS:
            R = real[(real.date >= d0) & (real.date <= d1)]
            Pp = plac[(plac.date >= d0) & (plac.date <= d1)]
            subs.append(r4(R.hold.mean() - Pp.hold.mean()) if len(R) >= 5 and len(Pp) >= 5 else None)
        res["sub"] = subs
        return res

    # ── R1 費波那契 ───────────────────────────────────────────────────────────
    r1 = {"density": {}, "hold": {}}
    for deg in ("small", "mid"):
        P = piv[deg]
        rr, dd = [], []
        for j in range(2, len(P)):
            A, B, C = P[j - 2]["p"], P[j - 1]["p"], P[j]["p"]
            if abs(B - A) > 0:
                rr.append(abs(C - B) / abs(B - A))
                dd.append(dates[P[j]["i"]])
        rr, dd = np.array(rr), np.array(dd)
        yrs = np.array([d[:4] for d in dd])
        res = {}
        for per, msk in {"IS": dd <= IS_END, "OOS": dd > IS_END}.items():
            x, g = rr[msk], yrs[msk]

            def st(ii, x=x):
                v = x[ii]
                fib = sum(((v > f - 0.03) & (v < f + 0.03)).sum() for f in (0.382, 0.5, 0.618)) / (3 * 0.06)
                ctl = sum(((v > f - 0.03) & (v < f + 0.03)).sum() for f in E.CTRL_RET) / (4 * 0.06)
                return np.log(fib / ctl) if fib > 0 and ctl > 0 else np.nan
            est, lo, hi, p = block_boot(st, g)
            res[per] = {"n": int(len(x)), "log_density_ratio": r4(est), "ci": [r4(lo), r4(hi)], "p": r4(p),
                        "ratio_hist": np.histogram(x, bins=np.arange(0, 1.05, 0.05))[0].tolist()}
        r1["density"][deg] = res
        pvals[f"R1_density_{deg}"] = res.get("OOS", {}).get("p")
    fr = ev_df[ev_df.type == "fib"]
    fc = ev_df[ev_df.type == "fib_ctrl"]
    res = {}
    for per, (d0, d1) in {"IS": ("2000", IS_END), "OOS": (OOS_START, "2099")}.items():
        A_ = fr[(fr.date >= d0) & (fr.date <= d1) & fr.ratio.isin([0.382, 0.5, 0.618, 0.786])]
        B_ = fc[(fc.date >= d0) & (fc.date <= d1)]
        allg = np.r_[month_of(A_.date), month_of(B_.date)]
        isf = np.r_[np.ones(len(A_)), np.zeros(len(B_))].astype(bool)
        y = np.r_[A_.hold.values, B_.hold.values].astype(float)

        def st(ii, y=y, isf=isf):
            a_, b_ = ii[isf[ii]], ii[~isf[ii]]
            return y[a_].mean() - y[b_].mean() if len(a_) and len(b_) else np.nan
        est, lo, hi, p = block_boot(st, allg)
        res[per] = {"n_fib": int(len(A_)), "n_ctrl": int(len(B_)), "fib": r4(A_.hold.mean()), "ctrl": r4(B_.hold.mean()),
                    "diff": r4(est), "ci": [r4(lo), r4(hi)], "p": r4(p),
                    "by_ratio": {str(rt): {"n": int((A_.ratio == rt).sum()), "rate": r4(A_[A_.ratio == rt].hold.mean())}
                                 for rt in (0.382, 0.5, 0.618, 0.786)}}
    res["sub"] = [r4(fr[(fr.date >= d0) & (fr.date <= d1)].hold.mean() - fc[(fc.date >= d0) & (fc.date <= d1)].hold.mean())
                  for d0, d1 in PERIODS]
    r1["hold"] = res
    pvals["R1_hold_fib_vs_ctrl"] = res["OOS"].get("p")

    # ── R2 支撐壓力類型 ──────────────────────────────────────────────────────
    r2 = {}
    for typ in ["pivot", "pivot_k3", "fib", "target", "ma20", "ma60", "ma120", "ma240", "round", "multi"]:
        R = ev_df[ev_df.type == typ]
        Pp = pl_df[pl_df.type == typ] if len(pl_df) else pl_df
        if len(R) == 0:
            continue
        r2[typ] = hold_test(R, Pp)
        r2[typ]["by_side"] = {s: {"n": int((R.side == s).sum()), "rate": r4(R[R.side == s].hold.mean())} for s in ("S", "R")}
        pvals[f"R2_{typ}"] = r2[typ].get("OOS", {}).get("p")

    # ── 特徵（R3～R6）───────────────────────────────────────────────────────
    feat = F.build(tw, chips, sox)
    feat["wstate"] = wstate["mid"]
    feat["wstate_s"] = wstate["small"]

    def diff_test(mask_a: np.ndarray, mask_b: np.ndarray, col: str, d0: str, d1: str):
        sel = (feat.date >= d0).values & (feat.date <= d1).values & feat[col].notna().values
        A_ = sel & mask_a
        B_ = sel & mask_b
        y = feat[col].values
        ia, ib = np.where(A_)[0], np.where(B_)[0]
        if len(ia) < 20 or len(ib) < 20:
            return {"n_a": int(len(ia)), "n_b": int(len(ib))}
        allg = np.r_[month_of(feat.date.values[ia]), month_of(feat.date.values[ib])]
        isa = np.r_[np.ones(len(ia)), np.zeros(len(ib))].astype(bool)
        yy = np.r_[y[ia], y[ib]]

        def st(ii):
            a_, b_ = ii[isa[ii]], ii[~isa[ii]]
            return yy[a_].mean() - yy[b_].mean() if len(a_) and len(b_) else np.nan
        est, lo, hi, p = block_boot(st, allg, n=1000)
        return {"n_a": int(len(ia)), "n_b": int(len(ib)), "mean_a": r4(y[ia].mean()), "mean_b": r4(y[ib].mean()),
                "up_a": r4((y[ia] > 0).mean()), "diff": r4(est), "ci": [r4(lo), r4(hi)], "p": r4(p)}

    def sub_signs(mask_a, mask_b, col, periods):
        out_ = []
        for d0, d1 in periods:
            sel = (feat.date >= d0).values & (feat.date <= d1).values & feat[col].notna().values
            a_, b_ = sel & mask_a, sel & mask_b
            out_.append(r4(feat[col].values[a_].mean() - feat[col].values[b_].mean()) if a_.sum() >= 20 and b_.sum() >= 20 else None)
        return out_

    # ── R3 波浪狀態（中級主要劇本）vs 無條件 ─────────────────────────────────
    r3 = {}
    ws = feat["wstate"].values
    have = np.array([isinstance(x, str) for x in ws])
    for key in sorted({x for x in ws if isinstance(x, str)}):
        ma_ = np.array([x == key for x in ws])
        r3[key] = {}
        for hz in (5, 20, 60):
            col = f"fwd{hz}"
            r3[key][f"h{hz}"] = {"IS": diff_test(ma_, have & ~ma_, col, "2000", IS_END),
                                 "OOS": diff_test(ma_, have & ~ma_, col, OOS_START, "2099"),
                                 "sub": sub_signs(ma_, have & ~ma_, col, PERIODS)}
            pvals[f"R3_{key}_h{hz}"] = r3[key][f"h{hz}"]["OOS"].get("p")

    # ── R4 籌碼（三分位切點只用 2016–2021）───────────────────────────────────
    r4_ = {}
    ch_is = (feat.date >= "2016-01-01") & (feat.date <= CH_IS_END)
    for fac in ("f5_z", "fut_pct", "fut_chg5", "margin_chg20"):
        if fac not in feat:
            continue
        v = feat.loc[ch_is, fac].dropna()
        if len(v) < 100:
            continue
        edges = (float(v.quantile(1 / 3)), float(v.quantile(2 / 3)))
        tcol = f"{fac}_t"
        feat[tcol] = F.tercile(feat[fac], edges)
        hi_, lo_ = (feat[tcol] == 2).values, (feat[tcol] == 0).values
        r4_[fac] = {"edges": [r4(edges[0]), r4(edges[1])]}
        for hz in (5, 20):
            col = f"fwd{hz}"
            r4_[fac][f"h{hz}"] = {"IS": diff_test(hi_, lo_, col, "2016-01-01", CH_IS_END),
                                  "OOS": diff_test(hi_, lo_, col, CH_OOS_START, "2099"),
                                  "sub": sub_signs(hi_, lo_, col, CH_PERIODS)}
            pvals[f"R4_{fac}_h{hz}"] = r4_[fac][f"h{hz}"]["OOS"].get("p")

    # ── R5 國際 ──────────────────────────────────────────────────────────────
    r5 = {}
    ret1 = pd.Series(c).pct_change().values
    for per, (d0, d1) in {"IS": ("2000", IS_END), "OOS": (OOS_START, "2099")}.items():
        sel = (feat.date >= d0).values & (feat.date <= d1).values & feat.sox_ret1.notna().values & np.isfinite(ret1)
        x, y = feat.sox_ret1.values[sel], ret1[sel]
        cc = float(np.corrcoef(x, y)[0, 1]) if sel.sum() > 30 else None
        r5[f"sox_overnight_{per}"] = {"n": int(sel.sum()), "corr": r4(cc), "r2": r4(cc * cc if cc is not None else None)}
    # 前一晚費半 → 加權當天：樣本內估 β、樣本外驗 R²；網站用 2016 以後重估的 β
    def _ols(x, y):
        b = np.cov(x, y, ddof=0)[0, 1] / np.var(x)
        return float(y.mean() - b * x.mean()), float(b)
    m_all = feat.sox_ret1.notna().values & np.isfinite(ret1)
    m_is = m_all & (feat.date <= IS_END).values
    m_oos = m_all & (feat.date > IS_END).values
    a_is, b_is = _ols(feat.sox_ret1.values[m_is], ret1[m_is])
    yo, xo = ret1[m_oos], feat.sox_ret1.values[m_oos]
    r2_oos = 1 - np.sum((yo - (a_is + b_is * xo)) ** 2) / np.sum((yo - yo.mean()) ** 2)
    a_o, b_o = _ols(xo, yo)
    resid_sd = float(np.std(yo - (a_o + b_o * xo)))
    r5["sox_beta"] = {"is_alpha": r4(a_is), "is_beta": r4(b_is), "oos_r2_with_is_beta": r4(r2_oos),
                      "alpha": r4(a_o), "beta": r4(b_o), "resid_sd": r4(resid_sd), "fit_period": "2016-2026"}
    up_, dn_ = (feat.sox_above_ma60 == 1).values, (feat.sox_above_ma60 == 0).values
    r5["sox_above_ma60"] = {}
    for hz in (5, 20):
        col = f"fwd{hz}"
        r5["sox_above_ma60"][f"h{hz}"] = {"IS": diff_test(up_, dn_, col, "2000", IS_END),
                                          "OOS": diff_test(up_, dn_, col, OOS_START, "2099"),
                                          "sub": sub_signs(up_, dn_, col, PERIODS)}
        pvals[f"R5_sox_ma60_h{hz}"] = r5["sox_above_ma60"][f"h{hz}"]["OOS"].get("p")
    tr_, sr_ = pd.Series(ret1), feat.sox_ret1
    corr60 = tr_.rolling(60).corr(sr_)
    r5["corr60_median"] = {f"{d0[:4]}-{d1[:4]}": r4(corr60[(feat.date >= d0) & (feat.date <= d1)].median()) for d0, d1 in PERIODS}

    # ── 選因子（只看樣本內）→ R6 逐步往前校準 ─────────────────────────────────
    def is_sig(block):
        ci = block.get("ci") or [None, None]
        return ci[0] is not None and (ci[0] > 0 or ci[1] < 0)

    selected = []
    st3 = [k for k in r3 if is_sig(r3[k]["h20"]["IS"])]
    if st3:
        selected.append(("wstate", max(abs(r3[k]["h20"]["IS"]["diff"] or 0) for k in st3)))
    for fac in r4_:
        if is_sig(r4_[fac]["h20"]["IS"]):
            selected.append((f"{fac}_t", abs(r4_[fac]["h20"]["IS"]["diff"] or 0)))
    if is_sig(r5["sox_above_ma60"]["h20"]["IS"]):
        selected.append(("sox_above_ma60", abs(r5["sox_above_ma60"]["h20"]["IS"]["diff"] or 0)))
    selected.sort(key=lambda x: -x[1])
    conds = ["above_ma60", "dd_b"] + [k for k, _ in selected]
    print("R6 conds", conds, f"{time.time() - t0:.0f}s")

    r6 = {"conds": conds, "selected_is": [{"factor": k, "is_effect": r4(v)} for k, v in selected]}
    for hz in (5, 20):
        for lab, d0 in (("2022-2026", CH_OOS_START), ("2016-2026", OOS_START)):
            pred, base_p, yv, gg = [], [], [], []
            idx = np.where((feat.date >= d0).values & feat[f"fwd{hz}"].notna().values)[0]
            for t in idx:
                a_ = FC.analog(feat, int(t), conds, horizon=hz, start=START)
                b_ = FC.analog(feat, int(t), [], horizon=hz, start=START)
                if not a_.get("n") or not b_.get("n"):
                    continue
                pred.append(a_["p_up"])
                base_p.append(b_["p_up"])
                yv.append(1.0 if feat[f"fwd{hz}"].iat[t] > 0 else 0.0)
                gg.append(feat.date.iat[t][:7])
            pred, base_p, yv, gg = map(np.array, (pred, base_p, yv, gg))

            def st(ii):
                return float(np.mean((base_p[ii] - yv[ii]) ** 2) - np.mean((pred[ii] - yv[ii]) ** 2))
            est, lo, hi, p = block_boot(st, gg, n=1000)
            bins = []
            for b0 in np.arange(0, 1, 0.1):
                mk = (pred >= b0) & (pred < b0 + 0.1)
                if mk.sum() >= 20:
                    bins.append({"pred": round(float(b0 + 0.05), 2), "n": int(mk.sum()), "actual": r4(yv[mk].mean())})
            r6[f"h{hz}_{lab}"] = {"n": int(len(yv)), "brier_model": r4(np.mean((pred - yv) ** 2)),
                                  "brier_base": r4(np.mean((base_p - yv) ** 2)), "improve": r4(est), "ci": [r4(lo), r4(hi)],
                                  "p": r4(p), "calibration": bins}
            if lab == "2022-2026":
                pvals[f"R6_h{hz}"] = r4(p)
            print("R6", hz, lab, r6[f"h{hz}_{lab}"]["improve"], r6[f"h{hz}_{lab}"]["ci"], f"{time.time() - t0:.0f}s")

    # ── 整體 BH ＋判定 ✅／△ ────────────────────────────────────────────────
    q = bh(pvals)
    sign_ok = lambda subs, sgn, need: sum(1 for s in subs if s is not None and np.sign(s) == sgn) >= need

    def verdict_hold(blk, key):
        o_ = blk.get("OOS", {})
        ok = (o_.get("diff") or 0) >= 0.05 and (o_.get("ci") or [None])[0] is not None and o_["ci"][0] > 0 \
            and q.get(key, 1) < 0.05 and sign_ok(blk.get("sub", []), 1, 3)
        return bool(ok)

    for typ, blk in r2.items():
        blk["q"] = r4(q.get(f"R2_{typ}"))
        blk["pass"] = verdict_hold(blk, f"R2_{typ}")
    r1["hold"]["q"] = r4(q.get("R1_hold_fib_vs_ctrl"))
    r1["hold"]["pass"] = verdict_hold(r1["hold"], "R1_hold_fib_vs_ctrl")
    for deg, blk in r1["density"].items():
        o_ = blk.get("OOS", {})
        blk["q"] = r4(q.get(f"R1_density_{deg}"))
        blk["pass"] = bool((o_.get("ci") or [None])[0] is not None and o_["ci"][0] > 0 and q.get(f"R1_density_{deg}", 1) < 0.05
                           and (blk.get("IS", {}).get("log_density_ratio") or 0) > 0)

    def verdict_diff(blk, key, need, nper):
        i_, o_ = blk["IS"], blk["OOS"]
        if o_.get("diff") is None or i_.get("diff") is None:
            return False
        sg = np.sign(o_["diff"])
        return bool(q.get(key, 1) < 0.05 and np.sign(i_["diff"]) == sg and sign_ok(blk["sub"], sg, need))

    for key, blk in r3.items():
        for hz in (5, 20, 60):
            b = blk[f"h{hz}"]
            b["q"] = r4(q.get(f"R3_{key}_h{hz}"))
            b["pass"] = verdict_diff(b, f"R3_{key}_h{hz}", 3, 4)
    for fac, blk in r4_.items():
        for hz in (5, 20):
            b = blk[f"h{hz}"]
            b["q"] = r4(q.get(f"R4_{fac}_h{hz}"))
            b["pass"] = verdict_diff(b, f"R4_{fac}_h{hz}", 2, 2)
    for hz in (5, 20):
        b = r5["sox_above_ma60"][f"h{hz}"]
        b["q"] = r4(q.get(f"R5_sox_ma60_h{hz}"))
        b["pass"] = verdict_diff(b, f"R5_sox_ma60_h{hz}", 3, 4)
    for hz in (5, 20):
        b = r6[f"h{hz}_2022-2026"]
        b["q"] = r4(q.get(f"R6_h{hz}"))
        b["pass"] = bool((b.get("ci") or [None])[0] is not None and b["ci"][0] > 0 and q.get(f"R6_h{hz}", 1) < 0.05)

    out.update({"R1": r1, "R2": r2, "R3": r3, "R4": r4_, "R5": r5, "R6": r6, "n_tests": len(pvals),
                "bh_q": {k: r4(v) for k, v in q.items()}})
    with open(os.path.join(OUT, "stats_full.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=lambda x: None)
    ev_df.to_csv(os.path.join(OUT, "events.csv.gz"), index=False)
    site = site_stats(out)
    with open(os.path.join(ROOT, "wave", "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(site, fh, ensure_ascii=False, indent=1)
    print("done", f"{time.time() - t0:.0f}s")


def site_stats(out: dict) -> dict:
    """網站只需要的部分（守住率表、各研究通過與否、相似狀態的條件與切點）"""
    hold = {}
    for typ, blk in out["R2"].items():
        o_ = blk.get("OOS", {})
        hold[typ] = {"rate": o_.get("rate"), "n": o_.get("n"), "placebo": o_.get("placebo"), "diff": o_.get("diff"),
                     "ci": o_.get("ci"), "pass": blk.get("pass", False)}
    r3 = {k: {hz: {"oos_mean": v[hz]["OOS"].get("mean_a"), "oos_up": v[hz]["OOS"].get("up_a"), "oos_n": v[hz]["OOS"].get("n_a"),
                   "diff": v[hz]["OOS"].get("diff"), "pass": v[hz].get("pass", False)} for hz in ("h5", "h20", "h60")}
          for k, v in out["R3"].items()}
    r4_ = {k: {"edges": v["edges"], **{hz: {"oos_diff": v[hz]["OOS"].get("diff"), "ci": v[hz]["OOS"].get("ci"),
                                             "pass": v[hz].get("pass", False)} for hz in ("h5", "h20")}}
           for k, v in out["R4"].items()}
    r5 = {"sox_overnight_corr": out["R5"].get("sox_overnight_OOS", {}).get("corr"), "sox_beta": out["R5"].get("sox_beta"),
          "sox_above_ma60": {hz: {"oos_diff": v["OOS"].get("diff"), "pass": v.get("pass", False)}
                             for hz, v in out["R5"]["sox_above_ma60"].items()},
          "corr60_median": out["R5"].get("corr60_median")}
    r6 = out["R6"]
    return {"generated": out["generated"], "data_end": out["data_end"], "coverage": out["coverage"], "hold": hold,
            "fib": {"hold": {k: out["R1"]["hold"].get(k) for k in ("q", "pass")} | {"oos": out["R1"]["hold"].get("OOS")},
                    "density": {d: {"pass": v.get("pass"), "oos": v.get("OOS", {}).get("log_density_ratio")} for d, v in out["R1"]["density"].items()}},
            "wave_state": r3, "chips": r4_, "global": r5,
            "analog": {"conds": r6["conds"], "h5": {k: r6["h5_2022-2026"].get(k) for k in ("improve", "ci", "pass", "n")},
                       "h20": {k: r6["h20_2022-2026"].get(k) for k in ("improve", "ci", "pass", "n")}},
            "n_tests": out["n_tests"]}


if __name__ == "__main__":
    main()
