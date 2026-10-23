"""B81 R-B 量能新角度（PLAN-B81 §4、§5b；門檻事先定好）
資料：D1 加權日 K＋證交所成交金額（2000～）、D4 台指期近月口數（日盤＋夜盤，2017-06～；價格結果用同一天加權現貨；
換月日前後 2 個交易日不取事件也不進相對量基準）、D2 加權 60 分＋MI_5MINS（同時段相對量）
虛無假設：A 組跟 B 組（一般量）之後的結果沒有差別；報告效果大小與 95% 區間（整年重抽）、p＝同一年內打亂組別 2,000 次
- V6 量縮變盤：A rvol≤0.6、B 0.9～1.1；結果＝之後 5 根（最高−最低）÷ATR；在 ATR% 三分位內比（置換也在年×三分位內）；|效果| ≥10%
- V7 爆量長 K（長紅、長黑分開）：A rvol≥2 且實體≥1 ATR、B 實體≥1 ATR 且 rvol 0.8～1.2；結果＝先順 K 棒方向走 1 ATR；|A−B| ≥8 點
- V8 新高量縮：收盤創 20 根新高（5 根內第一次）；A rvol<0.8、B ≥1.2；結果＝先回 1 ATR；|A−B| ≥8 點
- V9 價量齊揚：5 根漲幅 ≥1.5 ATR（5 根內第一次）；A 這 5 根平均 rvol≥1.2、B ≤0.8；結果＝先續漲 1 ATR；|A−B| ≥8 點
- 同一根兩邊都碰 → 不算；每組 ≥30 筆；15 個一起 BH；各時期（D1 四段、D4／D2 前後半）方向一樣才 ✅
用法：python research/b81/run_vol2.py"""
import json
import os
import sqlite3
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "b80"))
import common as C  # noqa: E402
import run_vol as RV  # noqa: E402
from wave import engine as E, volume as VO  # noqa: E402

OUT = os.path.join(HERE, "results")
H = {"D1": 10, "D4": 10, "D2": 15}
MIN_N = 30
MIN_PP = 0.08
MIN_RATIO = 0.10


def load_d4(D1):
    con = sqlite3.connect(os.path.join(RV.ROOT, "chip_data", "wave.db"))
    rows = con.execute("SELECT date, sess, contract, v FROM fut_daily WHERE date >= '2017-06-01' ORDER BY date").fetchall()
    vol, con_of = {}, {}
    for d, s, k, v in rows:
        if v is None:
            continue
        vol[d] = vol.get(d, 0.0) + float(v)
        if s == "day":
            con_of[d] = k
    idx = {d: i for i, d in enumerate(D1["dates"])}
    dates = [d for d in sorted(vol) if d in idx]
    # 換月：近月合約換掉的那天；前後 2 個交易日（含當天）排除
    roll = set()
    for j in range(1, len(dates)):
        if con_of.get(dates[j]) and con_of.get(dates[j - 1]) and con_of[dates[j]] != con_of[dates[j - 1]]:
            for q in range(max(0, j - 3), min(len(dates), j + 2)):
                roll.add(dates[q])
    ii = [idx[d] for d in dates]
    v = [None if d in roll else vol[d] for d in dates]
    D = {"name": "D4", "dates": dates, "years": np.array([int(d[:4]) for d in dates]),
         "o": D1["o"][ii], "h": D1["h"][ii], "l": D1["l"][ii], "c": D1["c"][ii], "v": v, "slot": None}
    D["th"] = E.thresholds(D["h"], D["l"], D["c"], "small")
    D["n_roll"] = len(roll)
    return D


def first_side(D, t, Hn, up_lv, dn_lv):
    r = RV.first_hit(D, t, Hn, up_lv=up_lv, dn_lv=dn_lv)
    return None if r in (None, "both") else r


def ev_v6(D):
    c, h, l, atr, rv = D["c"], D["h"], D["l"], D["atr"], D["rv"]
    n = len(c)
    ap = atr / c
    ok = np.isfinite(ap)
    cut = np.nanpercentile(ap[ok], [33.3, 66.7]) if ok.any() else [0, 0]
    out, last = [], {"A": -99, "B": -99}
    for t in range(30, n - 6):
        r = rv[t]
        if r is None or not np.isfinite(atr[t]) or atr[t] <= 0:
            continue
        g = "A" if r <= 0.6 else "B" if 0.9 <= r <= 1.1 else None
        if g is None or t - last[g] < 5:
            continue
        last[g] = t
        y = (np.max(h[t + 1:t + 6]) - np.min(l[t + 1:t + 6])) / atr[t]
        s = 0 if ap[t] <= cut[0] else 1 if ap[t] <= cut[1] else 2
        out.append({"t": t, "g": g, "y": float(y), "s": s, "year": int(D["years"][t])})
    return out


def _bar_events(D, kind):
    c, o, h, l, atr, rv = D["c"], D["o"], D["h"], D["l"], D["atr"], D["rv"]
    n = len(c)
    Hn = H[D["name"]]
    out = []
    last = -99
    for t in range(30, n - 1):
        a = atr[t]
        if not np.isfinite(a) or a <= 0 or rv[t] is None:
            continue
        if kind in ("V7u", "V7d"):
            body = c[t] - o[t]
            d = 1 if kind == "V7u" else -1
            if body * d < a:
                continue
            g = "A" if rv[t] >= 2.0 else "B" if 0.8 <= rv[t] <= 1.2 else None
            if g is None:
                continue
            r = first_side(D, t, Hn, c[t] + a, c[t] - a)
            if r is None:
                continue
            out.append({"t": t, "g": g, "y": (r == "up") if d > 0 else (r == "dn"), "year": int(D["years"][t])})
        elif kind == "V8":
            if t < 20 or c[t] < np.max(c[t - 19:t + 1]) or t - last < 5:
                continue
            last = t
            g = "A" if rv[t] < 0.8 else "B" if rv[t] >= 1.2 else None
            if g is None:
                continue
            r = first_side(D, t, Hn, c[t] + a, c[t] - a)
            if r is None:
                continue
            out.append({"t": t, "g": g, "y": r == "dn", "year": int(D["years"][t])})
        elif kind == "V9":
            if t < 5 or c[t] - c[t - 5] < 1.5 * a or t - last < 5:
                continue
            last = t
            rs = [x for x in rv[t - 4:t + 1] if x is not None]
            if len(rs) < 5:
                continue
            m = float(np.mean(rs))
            g = "A" if m >= 1.2 else "B" if m <= 0.8 else None
            if g is None:
                continue
            r = first_side(D, t, Hn, c[t] + a, c[t] - a)
            if r is None:
                continue
            out.append({"t": t, "g": g, "y": r == "up", "year": int(D["years"][t])})
    return out


def diff_stat(groups, vals):
    a = vals[groups == "A"]
    b = vals[groups == "B"]
    if len(a) == 0 or len(b) == 0:
        return None
    return float(np.mean(a) - np.mean(b))


def ratio_stat_factory(strata):
    def f(groups, vals):
        tot, w = 0.0, 0
        for s in (0, 1, 2):
            m = strata == s
            a = vals[m & (groups == "A")]
            b = vals[m & (groups == "B")]
            if len(a) >= 3 and len(b) >= 3 and np.mean(b) > 0:
                tot += len(a) * (np.mean(a) / np.mean(b) - 1)
                w += len(a)
        return tot / w if w else None
    return f


def analyze(D, name, ev, kind, periods, rng):
    if not ev:
        return {"nA": 0, "nB": 0}
    g = np.array([e["g"] for e in ev])
    y = np.array([float(e["y"]) for e in ev])
    yrs = np.array([e["year"] for e in ev])
    if kind == "V6":
        st = np.array([e["s"] for e in ev])
        fn = ratio_stat_factory(st)
        cells = yrs * 10 + st
        obs, p = C.perm_within_year(cells, g, y, fn, rng)

        def bstat(idx):
            return fn(g[idx], y[idx]) if len(idx) else None
        boot = C.year_boot(yrs, lambda idx: ratio_stat_factory(st[idx])(g[idx], y[idx]) if len(idx) else None, rng)
        thr = MIN_RATIO
    else:
        obs, p = C.perm_within_year(yrs, g, y, diff_stat, rng)
        boot = C.year_boot(yrs, lambda idx: diff_stat(g[idx], y[idx]) if len(idx) else None, rng)
        thr = MIN_PP
    per = {}
    for a, b in periods:
        m = (yrs >= int(a)) & (yrs <= int(b))
        if m.sum() >= 6:
            v = (ratio_stat_factory(np.array([e["s"] for e in ev])[m]) if kind == "V6" else diff_stat)(g[m], y[m])
            if v is not None:
                per[f"{a}–{b[2:]}"] = round(v * 100, 1)
    nA, nB = int(np.sum(g == "A")), int(np.sum(g == "B"))
    return {"nA": nA, "nB": nB, "A": round(float(np.mean(y[g == "A"])), 4) if nA else None, "B": round(float(np.mean(y[g == "B"])), 4) if nB else None,
            "effect": None if obs is None else round(obs, 4), "p": p, "thr": thr,
            "ci": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)] if len(boot) else None,
            "periods": per}


def main():
    rng = np.random.default_rng(C.SEED)
    D1 = RV.prep(RV.load_d1())
    D4 = RV.prep(load_d4(D1))
    D2 = RV.prep(RV.load_d2())
    sets = [("D1", D1, C.PERIODS_D1), ("D4", D4, (("2017", "2021"), ("2022", "2026"))),
            ("D2", D2, ((str(D2["years"].min()), "2024"), ("2025", str(D2["years"].max()))))]
    res = {"data": {nm: {"bars": len(D["c"]), "with_vol": int(D["n_vol"]), "from": str(D["dates"][0]), "to": str(D["dates"][-1])} for nm, D, _ in sets},
           "rows": {}}
    res["data"]["D4"]["roll_days_excluded"] = D4["n_roll"]
    for nm, D, per in sets:
        for kind in ("V6", "V7u", "V7d", "V8", "V9"):
            ev = ev_v6(D) if kind == "V6" else _bar_events(D, kind)
            r = analyze(D, nm, ev, kind, per, rng)
            res["rows"][f"{kind}:{nm}"] = r
            print(kind, nm, json.dumps(r, ensure_ascii=False), flush=True)
    q = C.bh({k: r.get("p") for k, r in res["rows"].items()})
    for k, r in res["rows"].items():
        r["q"] = q.get(k)
        per = list((r.get("periods") or {}).values())
        eff = r.get("effect")
        r["pass"] = bool(eff is not None and r["nA"] >= MIN_N and r["nB"] >= MIN_N and abs(eff) >= r["thr"]
                         and r["q"] is not None and r["q"] < 0.05 and r.get("ci") and (r["ci"][0] > 0 or r["ci"][1] < 0)
                         and per and (all(v > 0 for v in per) if eff > 0 else all(v < 0 for v in per)))
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, "vol2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, r in res["rows"].items():
        print(f"{k:8s} nA={r.get('nA')} nB={r.get('nB')} A={r.get('A')} B={r.get('B')} eff={r.get('effect')} ci={r.get('ci')} q={r.get('q')} per={r.get('periods')} pass={r.get('pass')}")


if __name__ == "__main__":
    main()
