"""B94 回測：網站的支撐進多單、壓力進空單（規則見 PLAN.md，事先寫好、跑完不改）
python research/b94/run.py  → results/b94.json、REPORT.md"""
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
from wave import engine as E, intraday as I, levels as LV  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
COST = 0.0002                 # 來回 0.02%
N_BOOT = 2000
N_PLACEBO = 5
RNG = np.random.default_rng(20261104)
RULES = {"A": "價位到價位（目標對面價位、停損 1 ATR）", "B": "固定 1:2（停損 1 ATR、目標 2 ATR）", "C": "純方向（抱著不設停損停利）"}
SUBS = (("2016-01-01", "2018-12-31"), ("2019-01-01", "2020-12-31"), ("2021-01-01", "2023-12-31"), ("2024-01-01", "2026-12-31"))


def trend_at(c, t):
    """跟 wave.service._trend 一樣：年線上 +1、下 -1、不到 240 根 0"""
    if t + 1 < 240:
        return 0
    return 1 if c[t] > float(np.mean(c[t - 239:t + 1])) else -1


# ── 價位（網站同一套）──────────────────────────────────────────────────────────
def daily_levels(o, h, l, c, start=260):
    n = len(c)
    piv = {deg: E.zigzag(h, l, E.thresholds(h, l, c, deg)) for deg in E.DEGREES}
    atr = E.atr(h, l, c)
    lv = {w: (np.full(n, np.nan), np.full(n, np.nan)) for w in ("short", "swing")}
    for t in range(start, n):
        if not np.isfinite(atr[t]):
            continue
        tr = trend_at(c, t)
        an = {deg: E.analyze(o, h, l, c, deg, t=t, trend=tr, piv=piv[deg]) for deg in E.DEGREES}
        b = LV.build(h, l, c, t, an, float(atr[t]))
        for w in ("short", "swing"):
            g = b.get(w) or {}
            s, r = g.get("support") or [], g.get("resistance") or []
            if s:
                lv[w][0][t] = s[0]["price"]
            if r:
                lv[w][1][t] = r[0]["price"]
    return lv, atr


def m60_levels(m, d):
    """60 分：build_ultra；昨天高低收、月線、trend（現價 vs 日 K 月線）從日 K 來"""
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    piv = E.zigzag(h, l, I.theta(h, l, c))
    atr = E.atr(h, l, c)
    S, R = np.full(n, np.nan), np.full(n, np.nan)
    dd = d.copy()
    dd["ma20"] = dd.c.rolling(20).mean()
    ddate = dd.date.tolist()
    mdate = m.date.str[:10].tolist()
    import bisect
    for t in range(120, n):
        if not np.isfinite(atr[t]):
            continue
        k = bisect.bisect_left(ddate, mdate[t]) - 1                    # 前一個交易日（今天日 K 還沒收）
        if k < 20:
            continue
        prev = dd.iloc[k]
        daily = {"prev_h": float(prev.h), "prev_l": float(prev.l), "prev_c": float(prev.c), "ma20": float(prev.ma20)}
        tr = 0 if not np.isfinite(daily["ma20"]) else (1 if c[t] > daily["ma20"] else -1)
        an = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv)
        b = LV.build_ultra(h, l, c, t, an, float(atr[t]), float(c[t]), daily=daily)
        if b["support"]:
            S[t] = b["support"][0]["price"]
        if b["resistance"]:
            R[t] = b["resistance"][0]["price"]
    return (S, R), atr


# ── 交易模擬 ─────────────────────────────────────────────────────────────────
def simulate(o, h, l, c, A, t, side, level, opp, rule, max_after, hold_c):
    """第 t 根收盤的價位、第 t+1 根成交 → (報酬扣成本, 出場那根, 原因)；opp＝對面價位（規則 A 的目標）"""
    n = len(c)
    e = t + 1
    fill = min(o[e], level) if side > 0 else max(o[e], level)
    if rule == "A":
        stop = level - side * A
        target = opp if (opp is not None and np.isfinite(opp) and (opp - fill) * side > 0) else None
        last = min(n - 1, e + max_after)
    elif rule == "B":
        stop, target, last = fill - side * A, fill + side * 2 * A, min(n - 1, e + max_after)
    else:
        stop, target, last = None, None, min(n - 1, e + hold_c)
    hit_stop = lambda k: stop is not None and (l[k] <= stop if side > 0 else h[k] >= stop)       # noqa: E731
    hit_tg = lambda k: target is not None and (h[k] >= target if side > 0 else l[k] <= target)  # noqa: E731
    if hit_stop(e):                                                    # 進場那根只檢查停損
        ex = min(stop, o[e]) if side > 0 and o[e] <= stop else (max(stop, o[e]) if side < 0 and o[e] >= stop else stop)
        ex = fill if (fill - stop) * side <= 0 else ex                 # 跳空成交就已經在停損外 → 用成交價出（0 毛利）
        return side * (ex / fill - 1) - COST, e, "stop"
    for k in range(e + 1, last + 1):
        if stop is not None and ((side > 0 and o[k] <= stop) or (side < 0 and o[k] >= stop)):
            return side * (o[k] / fill - 1) - COST, k, "stop"
        if target is not None and ((side > 0 and o[k] >= target) or (side < 0 and o[k] <= target)):
            return side * (o[k] / fill - 1) - COST, k, "target"
        if hit_stop(k):
            return side * (stop / fill - 1) - COST, k, "stop"
        if hit_tg(k):
            return side * (target / fill - 1) - COST, k, "target"
    return side * (c[last] / fill - 1) - COST, last, "time"


def events(o, h, l, c, A, S, R, t0, t1, rule, max_after, hold_c):
    """每根「下一根只碰到 S1／只碰到 R1」都是一個事件（可以重疊）"""
    out = []
    for t in range(t0, min(t1, len(c) - 2)):
        if not np.isfinite(A[t]) or A[t] <= 0:
            continue
        s, r = S[t], R[t]
        ts = np.isfinite(s) and l[t + 1] <= s
        tr = np.isfinite(r) and h[t + 1] >= r
        if ts == tr:
            continue
        side, lev, opp = (1, s, r) if ts else (-1, r, s)
        if rule == "A" and not (np.isfinite(opp)):
            continue
        ret, k, why = simulate(o, h, l, c, A[t], t, side, lev, opp if np.isfinite(opp) else None, rule, max_after, hold_c)
        out.append({"t": t, "side": side, "ret": ret, "why": why, "d_lev": (c[t] - lev) / A[t] * side,
                    "d_opp": ((opp - c[t]) / A[t] * side) if np.isfinite(opp) else np.nan})
    return out


def placebo(o, h, l, c, A, real, pool, rule, max_after, hold_c):
    """每筆真事件：同一期間隨機挑一根，同樣 ATR 距離畫假價位；下一根碰到（而且沒碰到對面）才算"""
    out = []
    for ev in real:
        got, tries = 0, 0
        while got < N_PLACEBO and tries < 60:
            tries += 1
            t = int(RNG.choice(pool))
            if t + 2 >= len(c) or not np.isfinite(A[t]) or A[t] <= 0:
                continue
            side = ev["side"]
            lev = c[t] - side * ev["d_lev"] * A[t]
            opp = c[t] + side * ev["d_opp"] * A[t] if np.isfinite(ev["d_opp"]) else np.nan
            touch = l[t + 1] <= lev if side > 0 else h[t + 1] >= lev
            other = np.isfinite(opp) and (h[t + 1] >= opp if side > 0 else l[t + 1] <= opp)
            if not touch or other:
                continue
            ret, _, why = simulate(o, h, l, c, A[t], t, side, lev, opp if np.isfinite(opp) else None, rule, max_after, hold_c)
            out.append({"t": t, "side": side, "ret": ret, "why": why})
            got += 1
    return out


def book(o, h, l, c, A, S, R, t0, t1, rule, max_after, hold_c, dates):
    """一次只抱一筆的實際帳"""
    trades = []
    t = t0
    while t < min(t1, len(c) - 2):
        if not np.isfinite(A[t]) or A[t] <= 0:
            t += 1
            continue
        s, r = S[t], R[t]
        ts = np.isfinite(s) and l[t + 1] <= s
        tr = np.isfinite(r) and h[t + 1] >= r
        if ts == tr or (rule == "A" and not (np.isfinite(s) and np.isfinite(r))):
            t += 1
            continue
        side, lev, opp = (1, s, r) if ts else (-1, r, s)
        ret, k, why = simulate(o, h, l, c, A[t], t, side, lev, opp if np.isfinite(opp) else None, rule, max_after, hold_c)
        trades.append({"date": dates[t + 1], "side": side, "ret": ret, "why": why, "bars": k - t})
        t = k
    return trades


# ── 統計 ─────────────────────────────────────────────────────────────────────
def boot_diff(real, plac, months_r, months_p):
    """真 − 對照 的平均差；月份 block（兩邊一起抽月份）→ (估計, 下限, 上限, p)"""
    real, plac = np.asarray(real), np.asarray(plac)
    if len(real) < 10 or len(plac) < 10:
        return None
    est = real.mean() - plac.mean()
    ug = np.unique(np.r_[months_r, months_p])
    ir = {g: np.where(months_r == g)[0] for g in ug}
    ip = {g: np.where(months_p == g)[0] for g in ug}
    vals = []
    for _ in range(N_BOOT):
        pick = RNG.choice(ug, size=len(ug), replace=True)
        a = np.concatenate([ir[g] for g in pick])
        b = np.concatenate([ip[g] for g in pick])
        if len(a) and len(b):
            vals.append(real[a].mean() - plac[b].mean())
    vals = np.array(vals)
    lo, hi = np.quantile(vals, [0.025, 0.975])
    p = 2 * min((vals <= 0).mean(), (vals >= 0).mean())
    return float(est), float(lo), float(hi), float(max(p, 1 / N_BOOT))


def bh(pv: dict) -> dict:
    ks = [k for k, v in pv.items() if v is not None]
    ps = np.array([pv[k] for k in ks])
    if not len(ps):
        return {}
    order = np.argsort(ps)
    m = len(ps)
    q = np.empty(m)
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    return {k: float(q[j]) for j, k in enumerate(ks)}


def summ(rs):
    rs = np.asarray(rs, dtype=float)
    if not len(rs):
        return {"n": 0}
    win = rs[rs > 0].sum()
    loss = -rs[rs < 0].sum()
    eq = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq)) if len(eq) else 0.0
    return {"n": int(len(rs)), "win": round(float((rs > 0).mean()), 4), "mean": round(float(rs.mean()), 5),
            "sum": round(float(rs.sum()), 4), "pf": round(float(win / loss), 3) if loss > 0 else None, "mdd": round(dd, 4)}


def r4(x):
    return None if x is None else round(float(x), 5)


def run_set(name, o, h, l, c, dates, A, S, R, periods, max_after, hold_c, tests, books):
    months = np.array([str(d)[:7] for d in dates])
    for pname, (d0, d1) in periods.items():
        idx = np.where((dates >= d0) & (dates <= d1))[0]
        if len(idx) < 50:
            continue
        t0, t1 = int(idx[0]), int(idx[-1]) + 1
        pool = idx[idx < len(c) - 2]
        for rule in RULES:
            evs = events(o, h, l, c, A, S, R, t0, t1, rule, max_after, hold_c)
            pls = placebo(o, h, l, c, A, evs, pool, rule, max_after, hold_c)
            for side, sn in ((1, "long"), (-1, "short")):
                rr = [e for e in evs if e["side"] == side]
                pp = [e for e in pls if e["side"] == side]
                b = boot_diff([e["ret"] for e in rr], [e["ret"] for e in pp],
                              months[[e["t"] + 1 for e in rr]] if rr else np.array([]),
                              months[[e["t"] + 1 for e in pp]] if pp else np.array([]))
                sub = []
                for s0, s1 in SUBS:
                    a = [e["ret"] for e in rr if s0 <= dates[e["t"] + 1] <= s1]
                    bb = [e["ret"] for e in pp if s0 <= dates[e["t"] + 1] <= s1]
                    sub.append(None if len(a) < 5 or len(bb) < 5 else round(float(np.mean(a) - np.mean(bb)), 5))
                tests[f"{name}|{pname}|{rule}|{sn}"] = {
                    "real": summ([e["ret"] for e in rr]), "placebo": summ([e["ret"] for e in pp]),
                    "diff": None if not b else {"est": r4(b[0]), "lo": r4(b[1]), "hi": r4(b[2]), "p": r4(b[3])},
                    "subs": sub, "why": {k: sum(1 for e in rr if e["why"] == k) for k in ("target", "stop", "time")}}
            bk = book(o, h, l, c, A, S, R, t0, t1, rule, max_after, hold_c, dates)
            by_year = defaultdict(list)
            for x in bk:
                by_year[str(x["date"])[:4]].append(x["ret"])
            books[f"{name}|{pname}|{rule}"] = {"all": summ([x["ret"] for x in bk]),
                                               "long": summ([x["ret"] for x in bk if x["side"] > 0]),
                                               "short": summ([x["ret"] for x in bk if x["side"] < 0]),
                                               "years": {y: summ(v) for y, v in sorted(by_year.items())}}


def main():
    t_start = time.time()
    os.makedirs(OUT, exist_ok=True)
    tests, books, meta = {}, {}, {}
    d = pd.read_csv(os.path.join(DATA, "twii_d.csv")).dropna(subset=["o", "h", "l", "c"])
    d = d[(d.h >= d.l) & (d.c > 0)].reset_index(drop=True)
    o, h, l, c = (d[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    dates = d.date.astype(str).to_numpy()
    lv, A = daily_levels(o, h, l, c)
    meta["twii_d"] = {"start": dates[0], "end": dates[-1], "n": len(d)}
    print("twii_d levels", f"{time.time() - t_start:.0f}s", flush=True)
    per = {"IS": ("2001-01-01", "2015-12-31"), "OOS": ("2016-01-01", "2026-12-31")}
    for w in ("short", "swing"):
        run_set(f"加權日K-{w}", o, h, l, c, dates, A, lv[w][0], lv[w][1], per, 10, 5, tests, books)
    print("twii_d done", f"{time.time() - t_start:.0f}s", flush=True)
    p_tx = os.path.join(DATA, "tx_d.csv")
    if os.path.exists(p_tx):
        x = pd.read_csv(p_tx).dropna(subset=["o", "h", "l", "c"])
        x = x[(x.h >= x.l) & (x.c > 0)].reset_index(drop=True)
        xo, xh, xl, xc = (x[k].to_numpy(float) for k in ("o", "h", "l", "c"))
        xd = x.date.astype(str).str[:10].to_numpy()
        xlv, xA = daily_levels(xo, xh, xl, xc, start=250)
        meta["tx_d"] = {"start": xd[0], "end": xd[-1], "n": len(x)}
        run_set("台指期日K-short", xo, xh, xl, xc, xd, xA, xlv["short"][0], xlv["short"][1], {"ALL": ("2018-01-01", "2026-12-31")},
                10, 5, tests, books)
        print("tx_d done", f"{time.time() - t_start:.0f}s", flush=True)
    m = pd.read_csv(os.path.join(DATA, "twii_60m.csv")).dropna(subset=["o", "h", "l", "c"])
    m = m[(m.h >= m.l) & (m.c > 0)].reset_index(drop=True)
    (S6, R6), A6 = m60_levels(m, d)
    mo, mh, ml, mc = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    md = m.date.astype(str).to_numpy()
    meta["twii_60m"] = {"start": md[0], "end": md[-1], "n": len(m)}
    run_set("加權60分", mo, mh, ml, mc, md, A6, S6, R6, {"ALL": (md[0][:10], "2026-12-31")}, 20, 10, tests, books)
    print("60m done", f"{time.time() - t_start:.0f}s", flush=True)
    q = bh({k: (v["diff"] or {}).get("p") for k, v in tests.items()})
    for k, v in tests.items():
        v["q"] = r4(q.get(k))
        dd = v["diff"]
        subs_ok = sum(1 for s in v["subs"] if s is not None and dd and s * dd["est"] > 0)
        if dd is None:
            v["verdict"] = "樣本不夠"
        elif dd["lo"] > 0 and (v["q"] or 1) < 0.05 and (v["real"]["mean"] or 0) > 0 and ("OOS" not in k or subs_ok >= 3):
            v["verdict"] = "✅"
        elif dd["hi"] < 0 and (v["q"] or 1) < 0.05:
            v["verdict"] = "✗ 比隨便畫線差"
        else:
            v["verdict"] = "△"
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "meta": meta, "cost": COST, "rules": RULES, "tests": tests, "books": books}
    with open(os.path.join(OUT, "b94.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    report(res)
    print("done", f"{time.time() - t_start:.0f}s")


def pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(res):
    L = ["# B94 回測：網站的支撐進多單、壓力進空單", "",
         f"規則見 PLAN.md（事先寫好）。成本來回 {res['cost'] * 100:.2f}%。資料：" +
         "、".join(f"{k} {v['start']}～{v['end']}（{v['n']} 根）" for k, v in res["meta"].items()), "",
         "## 1. 跟隨便畫線比（每次碰到都算一筆、可以重疊）", "",
         "| 資料｜期間｜規則｜方向 | 筆數 | 勝率 | 平均（扣成本） | 隨便畫線 | 差 [95% 區間] | q | 4 個時期 | 結果 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["tests"].items():
        nm, per, rule, side = k.split("|")
        rl, pl, dd = v["real"], v["placebo"], v["diff"]
        L.append(f"| {nm}｜{per}｜{rule}｜{'多' if side == 'long' else '空'} | {rl.get('n', 0)} | {pct(rl.get('win'), 0) if rl.get('n') else '—'} "
                 f"| {pct(rl.get('mean'))} | {pct(pl.get('mean'))} | "
                 + ("—" if not dd else f"{pct(dd['est'])} [{pct(dd['lo'])}, {pct(dd['hi'])}]") + f" | {v.get('q') if v.get('q') is not None else '—'} | "
                 + "／".join("—" if s is None else ("+" if s > 0 else "−") for s in v["subs"]) + f" | {v['verdict']} |")
    L += ["", "## 2. 一次只抱一筆的實際帳", "",
          "| 資料｜期間｜規則 | 筆數 | 勝率 | 每筆平均 | 總報酬（加總） | 獲利因子 | 最大回落 | 多單平均 | 空單平均 |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["books"].items():
        a, lo, sh = v["all"], v["long"], v["short"]
        if not a.get("n"):
            continue
        L.append(f"| {k.replace('|', '｜')} | {a['n']} | {pct(a['win'], 0)} | {pct(a['mean'])} | {pct(a['sum'], 1)} | {a.get('pf') or '—'} | "
                 f"{pct(-a['mdd'], 1)} | {pct(lo.get('mean'))}（{lo.get('n', 0)}） | {pct(sh.get('mean'))}（{sh.get('n', 0)}） |")
    L += ["", "規則：A＝" + RULES["A"] + "；B＝" + RULES["B"] + "；C＝" + RULES["C"] + "（日 K 抱 5 根、60 分抱 10 根）。",
          "「隨便畫線」＝同一期間隨機挑一天、同樣 ATR 距離畫假支撐／假壓力，用同樣規則交易；差＝真的價位比隨便畫線多賺（或少賠）多少。"]
    with open(os.path.join(HERE, "REPORT.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
