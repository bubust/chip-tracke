"""B94c：停損 100 點＋改善風報比（用戶：「我覺得這個風報比有問題，停損抓個 100 點，加上你的建議」）
規則（事先寫好、跑完不改）見 PLAN60c.md；資料同 run60.py（加權 60 分 K）。
python research/b94/run60c.py → results/b94_60m_c.json、REPORT60c.md"""
import bisect
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run60 as R6  # noqa: E402  （也把 repo 根目錄加進 sys.path）
from wave import engine as E, intraday as I, levels as LV  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
COST = R6.COST              # 來回 0.02%
MAX_BARS = 25               # 最多抱 25 根（5 個交易日）
N_PLACEBO = 5
STOP_PTS = 100.0            # 用戶：停損 100 點
RR = 2.0                    # 目標至少 2 倍停損距離
BUF_ATR = 0.25              # F：支撐區下緣再 0.25 ATR
RNG = np.random.default_rng(20261106)
V = {
    "A": dict(rr=False, be=False, trend=False, confirm=False, struct=False, name="A 100 點停損"),
    "B": dict(rr=True, be=False, trend=False, confirm=False, struct=False, name="B ＋風報比≥2"),
    "C": dict(rr=True, be=True, trend=False, confirm=False, struct=False, name="C ＋保本"),
    "D": dict(rr=True, be=True, trend=True, confirm=False, struct=False, name="D ＋順勢"),
    "E": dict(rr=True, be=True, trend=True, confirm=True, struct=False, name="E ＋等收盤站回"),
    "F": dict(rr=True, be=True, trend=True, confirm=False, struct=True, name="F 結構停損（區外 0.25 ATR）"),
}
PRIMARY = ("long|A", "long|D", "long|F")


def zones3(m: pd.DataFrame, d: pd.DataFrame):
    """每根 60 分 K 收盤：build_ultra 上下各最多 3 區（近→遠）的 lo、hi；ATR；trend＝前一天日 K 收盤 vs 月線。結果快取在 data/"""
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    key = f"{n}_{m.date.iloc[-1]}"
    cache = os.path.join(DATA, "zones3.npz")
    if os.path.exists(cache):
        f = np.load(cache, allow_pickle=False)
        if str(f["key"]) == key:
            return {k: f[k] for k in ("s_lo", "s_hi", "r_lo", "r_hi")}, f["atr"], f["trend"]
    piv = E.zigzag(h, l, I.theta(h, l, c))
    atr = E.atr(h, l, c)
    Z = {k: np.full((n, 3), np.nan) for k in ("s_lo", "s_hi", "r_lo", "r_hi")}
    trend = np.zeros(n)
    dd = d.copy()
    dd["ma20"] = dd.c.rolling(20).mean()
    ddate = dd.date.tolist()
    mdate = m.date.str[:10].tolist()
    for t in range(120, n):
        if not np.isfinite(atr[t]):
            continue
        k = bisect.bisect_left(ddate, mdate[t]) - 1
        if k < 20:
            continue
        prev = dd.iloc[k]
        daily = {"prev_h": float(prev.h), "prev_l": float(prev.l), "prev_c": float(prev.c), "ma20": float(prev.ma20)}
        trend[t] = 1 if prev.c > prev.ma20 else -1
        tr = 1 if c[t] > daily["ma20"] else -1
        an = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv)
        b = LV.build_ultra(h, l, c, t, an, float(atr[t]), float(c[t]), daily=daily)
        for j, x in enumerate(b["support"][:3]):
            Z["s_lo"][t, j], Z["s_hi"][t, j] = x["lo"], x["hi"]
        for j, x in enumerate(b["resistance"][:3]):
            Z["r_lo"][t, j], Z["r_hi"][t, j] = x["lo"], x["hi"]
    np.savez(cache, key=key, atr=atr, trend=trend, **Z)
    return Z, atr, trend


def trade(o, h, l, c, t, side, v, near, far, targets, A, rr_check=True):
    """第 t 根收盤後的掛單。side=+1 做多（near＝支撐區上緣、far＝支撐區下緣、targets＝上面各壓力區下緣，近→遠）；
    side=-1 放空（near＝壓力區下緣、far＝壓力區上緣、targets＝下面各支撐區上緣）。不成交／不做回 None"""
    n = len(c)
    if v["confirm"]:                                                     # 下一根碰到、收盤站回，再下一根開盤進
        s, e = t + 1, t + 2
        if e >= n:
            return None
        ok = (l[s] <= near and c[s] >= near) if side > 0 else (h[s] >= near and c[s] <= near)
        if not ok:
            return None
        ref, fill = c[s], o[e]
    else:                                                                # 掛單：下一根碰到就成交
        e = t + 1
        if not (l[e] <= near if side > 0 else h[e] >= near):
            return None
        ref = near
        fill = min(o[e], near) if side > 0 else max(o[e], near)
    stop0 = far - side * BUF_ATR * A if v["struct"] else None
    risk_ref = (ref - stop0) * side if v["struct"] else STOP_PTS
    if risk_ref <= 0:
        return None
    need = RR * risk_ref if (v["rr"] and rr_check) else 1e-9
    tg = next((g for g in targets if (g - ref) * side >= need), None)
    if tg is None or (tg - fill) * side <= 0:
        return None
    stop = stop0 if v["struct"] else fill - side * STOP_PTS
    risk = (fill - stop) * side
    if risk <= 0:                                                        # 開盤就跳過停損：成交即出場
        risk = risk_ref
    be_dist = risk
    last = min(n - 1, e + MAX_BARS)
    st = {"be": False, "stop": stop, "be_k": None}

    def out(px, k, why, both=False):
        pts = side * (px - fill) - COST * fill
        return {"ret": side * (px / fill - 1) - COST, "pts": pts, "R": pts / risk, "why": why, "both": both,
                "bars": k - e + 1, "e": e, "k": k, "fill": fill, "exit": px, "tg": tg, "risk": risk, "stop0": stop,
                "be_k": st["be_k"]}

    def hit(k, lv, toward):                                              # toward=+1：往有利方向碰到 lv
        return (h[k] >= lv) if side * toward > 0 else (l[k] <= lv)

    # 進場那根
    if hit(e, st["stop"], -1):
        return out(fill if (fill - st["stop"]) * side <= 0 else st["stop"], e, "停損", both=hit(e, tg, 1) and v["confirm"])
    if v["confirm"]:                                                     # 開盤進場：整根都在進場後
        if hit(e, tg, 1):
            return out(tg, e, "到目標")
        if v["be"] and hit(e, fill + side * be_dist, 1):
            st["be"], st["stop"], st["be_k"] = True, fill, e
    for k in range(e + 1, last + 1):
        if (o[k] - st["stop"]) * side <= 0:                              # 跳空越過停損
            return out(o[k], k, "保本" if st["be"] else "停損")
        if (o[k] - tg) * side >= 0:                                      # 跳空越過目標
            return out(o[k], k, "到目標")
        hs, ht = hit(k, st["stop"], -1), hit(k, tg, 1)
        if hs:                                                           # 同一根都碰到 → 算停損（保守）
            return out(st["stop"], k, "保本" if st["be"] else "停損", both=ht)
        if ht:
            return out(tg, k, "到目標")
        if v["be"] and not st["be"] and hit(k, fill + side * be_dist, 1):
            st["be"], st["stop"], st["be_k"] = True, fill, k             # 下一根起停損移到成本
    return out(c[last], last, "時間到")


def setup(Z, t, side):
    if side > 0:
        near, far, tg = Z["s_hi"][t, 0], Z["s_lo"][t, 0], Z["r_lo"][t]
    else:
        near, far, tg = Z["r_lo"][t, 0], Z["r_hi"][t, 0], Z["s_hi"][t]
    tg = [float(x) for x in tg if np.isfinite(x)]
    return None if not (np.isfinite(near) and np.isfinite(far) and tg) else (float(near), float(far), tg)


def book(o, h, l, c, Z, atr, trend, dates, side, v):
    """一次只抱一筆；出場那根收盤後才找下一筆"""
    trades, t = [], 120
    while t < len(c) - 3:
        if not np.isfinite(atr[t]) or (v["trend"] and trend[t] != side):
            t += 1
            continue
        st = setup(Z, t, side)
        r = trade(o, h, l, c, t, side, v, *st, float(atr[t])) if st else None
        if r is None:
            t += 1
            continue
        r.update(t=t, side=side, date=dates[r["e"]], yr=dates[t][:4], A=float(atr[t]), trend=int(trend[t]),
                 off_near=(c[t] - st[0]) * side, off_far=(c[t] - st[1]) * side, off_tg=(r["tg"] - c[t]) * side)
        trades.append(r)
        t = r["k"]
    return trades


def placebo(o, h, l, c, trend, dates, trades, v):
    """每筆真交易：同一年（順勢版還要同樣在月線上／下）隨機挑一根，同樣的點數距離畫假支撐／假壓力、同樣目標距離、同樣停損"""
    yr = np.array([x[:4] for x in dates])
    idx = np.arange(len(c))
    pools = {}
    out = []
    for tr_ in trades:
        key = (tr_["yr"], tr_["trend"] if v["trend"] else 0)
        if key not in pools:
            msk = (yr == tr_["yr"]) & (idx >= 120) & (idx < len(c) - 3)
            if v["trend"]:
                msk &= trend == tr_["trend"]
            pools[key] = idx[msk]
        pool = pools[key]
        if not len(pool):
            continue
        got, tries, s = 0, 0, tr_["side"]
        while got < N_PLACEBO and tries < 400:
            tries += 1
            t = int(RNG.choice(pool))
            near, far, tg = c[t] - s * tr_["off_near"], c[t] - s * tr_["off_far"], c[t] + s * tr_["off_tg"]
            r = trade(o, h, l, c, t, s, v, near, far, [tg], tr_["A"], rr_check=False)
            if r is None:
                continue
            r.update(t=t, date=dates[r["e"]])
            out.append(r)
            got += 1
    return out


def summ(tr):
    if not tr:
        return {"n": 0}
    r = np.array([x["ret"] for x in tr])
    p = np.array([x["pts"] for x in tr])
    R = np.array([x["R"] for x in tr])
    peq = np.cumsum(p)
    pdd = float(np.max(np.maximum.accumulate(np.r_[0, peq])[1:] - peq))
    Req = np.cumsum(R)
    Rdd = float(np.max(np.maximum.accumulate(np.r_[0, Req])[1:] - Req))
    why = defaultdict(int)
    for x in tr:
        why[x["why"]] += 1
    gain, loss = p[p > 0].sum(), -p[p < 0].sum()
    return {"n": len(tr), "win": round(float((p > 0).mean()), 4), "mean": round(float(r.mean()), 5), "sum": round(float(r.sum()), 4),
            "pts_mean": round(float(p.mean()), 1), "pts_sum": round(float(p.sum()), 0), "pts_mdd": round(pdd, 0),
            "pts_win": round(float(p[p > 0].mean()), 0) if (p > 0).any() else None,
            "pts_loss": round(float(p[p <= 0].mean()), 0) if (p <= 0).any() else None,
            "R_mean": round(float(R.mean()), 3), "R_sum": round(float(R.sum()), 1), "R_mdd": round(Rdd, 1),
            "risk_med": round(float(np.median([x["risk"] for x in tr])), 0),
            "tg_med": round(float(np.median([(x["tg"] - x["fill"]) * x["side"] for x in tr if "side" in x] or [0])), 0),
            "pf": round(float(gain / loss), 3) if loss > 0 else None, "bars": round(float(np.mean([x["bars"] for x in tr])), 1),
            "why": dict(why), "both": int(sum(x["both"] for x in tr)), "streak": streak(p)}


def streak(p):
    """最多連續幾筆沒賺（含保本）"""
    best = cur = 0
    for x in p:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return best


def describe(c, Z, atr, dates):
    """各年：支撐區上緣、最近壓力區下緣離現價幾點；有沒有離支撐區上緣 ≥200 點的壓力區"""
    yr = np.array([x[:4] for x in dates])
    res = {}
    for y in sorted(set(yr)):
        ii = np.where((yr == y) & np.isfinite(Z["s_hi"][:, 0]) & np.isfinite(Z["r_lo"][:, 0]))[0]
        if not len(ii):
            continue
        s_hi, r_lo = Z["s_hi"][ii, 0], Z["r_lo"][ii, 0]
        far_ok = np.array([any(np.isfinite(g) and g - s >= RR * STOP_PTS for g in Z["r_lo"][i]) for i, s in zip(ii, s_hi)])
        res[y] = {"bars": int(len(ii)), "atr": round(float(np.median(atr[ii])), 0), "price": round(float(np.median(c[ii])), 0),
                  "stop_in_atr": round(float(STOP_PTS / np.median(atr[ii])), 2),
                  "s_dist": round(float(np.median(c[ii] - s_hi)), 0), "r_dist": round(float(np.median(r_lo - c[ii])), 0),
                  "s_to_r": round(float(np.median(r_lo - s_hi)), 0),
                  "s_width": round(float(np.median(Z["s_hi"][ii, 0] - Z["s_lo"][ii, 0])), 0),
                  "rr_ok": round(float(far_ok.mean()), 3)}
    return res


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    m = pd.read_csv(os.path.join(DATA, "twii_60m.csv")).dropna(subset=["o", "h", "l", "c"])
    m = m[(m.h >= m.l) & (m.c > 0)].reset_index(drop=True)
    d = pd.read_csv(os.path.join(DATA, "twii_d.csv")).dropna(subset=["o", "h", "l", "c"])
    d = d[(d.h >= d.l) & (d.c > 0)].reset_index(drop=True)
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    dates = m.date.astype(str).to_numpy()
    months = np.array([x[:7] for x in dates])
    Z, atr, trend = zones3(m, d)
    print("zones", f"{time.time() - t0:.0f}s", flush=True)
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "data": {"start": dates[0], "end": dates[-1], "bars": len(m)},
           "cost": COST, "max_bars": MAX_BARS, "stop_pts": STOP_PTS, "rr": RR, "buf_atr": BUF_ATR,
           "variants": {k: v["name"] for k, v in V.items()}, "describe": describe(c, Z, atr, dates), "books": {}}
    pv = {}
    for side, sname in ((1, "long"), (-1, "short")):
        for vk, v in V.items():
            tr = book(o, h, l, c, Z, atr, trend, dates, side, v)
            pl = placebo(o, h, l, c, trend, dates, tr, v)
            b = R6.boot([x["ret"] for x in tr], [x["ret"] for x in pl],
                        months[[x["e"] for x in tr]] if tr else np.array([]), months[[x["e"] for x in pl]] if pl else np.array([]))
            years = defaultdict(list)
            for x in tr:
                years[x["date"][:4]].append(x)
            key = f"{sname}|{vk}"
            res["books"][key] = {"real": summ(tr), "placebo": summ(pl), "diff": b, "years": {y: summ(w) for y, w in sorted(years.items())},
                                 "sample": [{k: (round(x[k], 1) if isinstance(x[k], float) else x[k]) for k in ("date", "fill", "exit", "tg", "why", "bars", "pts")}
                                            for x in tr[-6:]]}
            pv[key] = (b or {}).get("p")
            print(key, res["books"][key]["real"].get("n"), res["books"][key]["real"].get("pts_sum"), f"{time.time() - t0:.0f}s", flush=True)
    q = R6.bh(pv)
    for k, x in res["books"].items():
        x["q"] = round(q[k], 4) if k in q else None
    # 判準（只看主要檢定）
    for k in res["books"]:
        x = res["books"][k]
        dd, r = x["diff"] or {}, x["real"]
        yrs = [x["years"].get(y, {}).get("mean", 0) for y in ("2024", "2025", "2026")]
        good = (dd.get("est", 0) > 0 and dd.get("lo", 0) > 0 and (x["q"] or 1) < 0.05 and r.get("mean", 0) > 0
                and sum(1 for y in yrs if y > 0) >= 2)
        bad = dd.get("hi", 1) < 0
        x["verdict"] = ("✅" if good else ("✗" if bad else "△")) + ("" if k in PRIMARY else "（非主要）")
    i0 = 121
    eq = c[i0:] - o[i0]
    res["buy_hold"] = {"pts": round(float(c[-1] - o[i0]), 0), "pct": round(float(c[-1] / o[i0] - 1), 4),
                       "pts_mdd": round(float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])), 0),
                       "years": {y: round(float(c[np.where([x[:4] == y for x in dates])[0][-1]] - o[max(i0, np.where([x[:4] == y for x in dates])[0][0])]), 0)
                                 for y in sorted({x[:4] for x in dates})}}
    try:
        with open(os.path.join(OUT, "b94_60m.json")) as f:
            prev = json.load(f)
        res["b94b"] = {"long|atr": prev["books"]["long|atr"]["real"], "short|atr": prev["books"]["short|atr"]["real"],
                       "baseline": prev["baseline"]}
    except (OSError, KeyError):
        res["b94b"] = None
    with open(os.path.join(OUT, "b94_60m_c.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    report(res)
    print("done", f"{time.time() - t0:.0f}s")


def pc(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(res):
    SIDE = {"long": "只做多", "short": "只做空"}
    L = ["# B94c：停損 100 點＋改善風報比（60 分 K、只做多／只做空）", "",
         f"資料：加權 60 分 K {res['data']['start']}～{res['data']['end']}（{res['data']['bars']} 根）。規則見 PLAN60c.md。"
         f"停損 {res['stop_pts']:.0f} 點、風報比 ≥ {res['rr']:.0f}、成本來回 {res['cost'] * 100:.2f}%、最多抱 {res['max_bars']} 根。", "",
         "## 各年的尺度（中位數，點）", "",
         "| 年 | 加權 | 60 分 1 ATR | 100 點＝幾個 ATR | 現價→支撐區上緣 | 現價→壓力區下緣 | 支撐區上緣→壓力區下緣 | 支撐區寬 | 有 ≥200 點目標的比例 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for y, x in res["describe"].items():
        L.append(f"| {y} | {x['price']:,.0f} | {x['atr']:.0f} | {x['stop_in_atr']} | {x['s_dist']:.0f} | {x['r_dist']:.0f} | {x['s_to_r']:.0f} | "
                 f"{x['s_width']:.0f} | {x['rr_ok'] * 100:.0f}% |")
    L += ["", "## 結果（一次只抱一筆，扣成本）", "",
          "| 做法 | 筆數 | 勝率 | 到目標／停損／保本／時間到 | 最多連續沒賺 | 同根都碰到 | 停損距離 | 目標距離 | 賺的平均 | 賠的平均 | 每筆點數 | 每筆 R | "
          "點數加總 | 點數最大回落 | 隨便畫線每筆 | 差 [95%] | q | 判定 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, x in res["books"].items():
        sd, vk = k.split("|")
        r, p, dd = x["real"], x["placebo"], x["diff"]
        if not r.get("n"):
            L.append(f"| {SIDE[sd]} {res['variants'][vk]} | 0 | | | | | | | | | | | | | | | | |")
            continue
        w = r["why"]
        L.append(f"| {SIDE[sd]} {res['variants'][vk]} | {r['n']} | {r['win'] * 100:.0f}% | {w.get('到目標', 0)}／{w.get('停損', 0)}／{w.get('保本', 0)}／{w.get('時間到', 0)} | "
                 f"{r['streak']} | {r['both']} | {r['risk_med']:.0f} | {r['tg_med']:.0f} | {r['pts_win']:+.0f} | {r['pts_loss']:+.0f} | {r['pts_mean']:+.0f} | {r['R_mean']:+.2f} | "
                 f"{r['pts_sum']:+,.0f} | {-r['pts_mdd']:,.0f} | {pc(p.get('mean'))} | "
                 + ("—" if not dd else f"{pc(dd['est'])} [{pc(dd['lo'])}, {pc(dd['hi'])}]") + f" | {x.get('q') if x.get('q') is not None else '—'} | {x.get('verdict', '')} |")
    pb = res.get("b94b")
    if pb:
        a = pb["long|atr"]
        L += ["", f"B94b 對照（只做多、區外緣再 1 ATR 停損）：{a['n']} 筆、勝率 {a['win'] * 100:.0f}%、每筆 {a['pts_mean']:+.0f} 點、加總 {a['pts_sum']:+,.0f} 點、"
                  f"最大回落 {-a['pts_mdd']:,.0f} 點。同期間買進抱著 {pc(pb['baseline']['buy_hold'], 1)}、隨便一根買抱 25 根每筆 {pc(pb['baseline']['random_25_long'])}。"]
    bh_ = res["buy_hold"]
    L += ["", f"同期間買進 1 口抱著：{bh_['pts']:+,.0f} 點（{pc(bh_['pct'], 1)}），中間最大回落 {-bh_['pts_mdd']:,.0f} 點；各年 "
          + "、".join(f"{y} {v:+,.0f}" for y, v in bh_["years"].items()) + " 點。"]
    L += ["", "## 各年（點數加總／筆數／勝率／停損距離中位數）", "", "| 做法 | " + " | ".join(sorted({y for x in res["books"].values() for y in x["years"]})) + " |",
          "|---|" + "---|" * len({y for x in res["books"].values() for y in x["years"]})]
    ys = sorted({y for x in res["books"].values() for y in x["years"]})
    L.append("| 買進抱著 | " + " | ".join(f"{bh_['years'].get(y, 0):+,.0f}" for y in ys) + " |")
    for k, x in res["books"].items():
        sd, vk = k.split("|")
        cells = []
        for y in ys:
            s = x["years"].get(y)
            cells.append("—" if not s or not s.get("n") else f"{s['pts_sum']:+,.0f}（{s['n']} 筆、{s['win'] * 100:.0f}%、停損距離 {s['risk_med']:.0f}）")
        L.append(f"| {SIDE[sd]} {res['variants'][vk]} | " + " | ".join(cells) + " |")
    with open(os.path.join(HERE, "REPORT60c.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
