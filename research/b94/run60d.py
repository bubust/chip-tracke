"""B94d：依波浪理論進出（用戶：「你要依據波浪理論裡面的去做進出，不是瞎猜」）
規則（事先寫好、跑完不改）見 PLAN60d.md；資料同 run60.py（加權 60 分 K）。
python research/b94/run60d.py → results/b94_60m_d.json、REPORT60d.md"""
import bisect
import json
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run60 as R6  # noqa: E402
import run60c as C  # noqa: E402
from wave import engine as E, intraday as I  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
COST = R6.COST
MAX_BARS = 50               # 最多抱 50 根（10 個交易日）
N_PLACEBO = 5
RNG = np.random.default_rng(20261107)
V = {
    "limit": dict(confirm=False, trend=False, name="掛單"),
    "confirm": dict(confirm=True, trend=False, name="等確認"),
    "limit_t": dict(confirm=False, trend=True, name="掛單＋順勢"),
    "confirm_t": dict(confirm=True, trend=True, name="等確認＋順勢"),
}
PRIMARY = ("long|limit", "long|confirm")
SETUP_NAME = {"W2": "第 2 浪回檔買", "W4": "第 4 浪回檔買", "C": "C 浪末端買"}


def counts(m: pd.DataFrame, d: pd.DataFrame):
    """每根 60 分 K 收盤的主要劇本（網站 60 分同一套）＋前一天日 K vs 月線；快取在 data/"""
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    key = f"{n}_{m.date.iloc[-1]}"
    cache = os.path.join(DATA, "counts60.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            got = pickle.load(f)
        if got["key"] == key:
            return got["prim"], got["trend"]
    piv = E.zigzag(h, l, I.theta(h, l, c))
    dd = d.copy()
    dd["ma20"] = dd.c.rolling(20).mean()
    ddate = dd.date.tolist()
    mdate = m.date.str[:10].tolist()
    prim = [None] * n
    trend = np.zeros(n)
    for t in range(120, n):
        k = bisect.bisect_left(ddate, mdate[t]) - 1
        if k < 20:
            continue
        prev = dd.iloc[k]
        trend[t] = 1 if prev.c > prev.ma20 else -1
        tr = 1 if c[t] > prev.ma20 else -1
        an = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv)
        p = an.get("primary")
        if p:
            prim[t] = {"kind": p["kind"], "cur": p["current"], "dir": p["dir"], "text": p["text"], "invalid": p["invalid"],
                       "labels": [{"i": q["i"], "p": float(q["p"]), "s": q["disp"], "tent": q["tentative"]} for q in p["labels"]]}
    with open(cache, "wb") as f:
        pickle.dump({"key": key, "prim": prim, "trend": trend}, f)
    return prim, trend


def wave_setup(p, close):
    """主要劇本 → (side, 種類, 進場價, 停損, 目標, 說明 dict)；不符合回 None。全部照 PLAN60d.md"""
    if not p or p["kind"] not in ("impulse", "correction"):
        return None
    d, cur = p["dir"], p["cur"]
    x = [d * q["p"] for q in p["labels"]]                                # x 空間：第一段往上
    xc = d * close
    info = {}
    if p["kind"] == "impulse" and cur == "2":
        len1 = x[1] - x[0]
        lv = [(r, x[1] - r * len1) for r in (0.5, 0.618)]
        r, ent = next(((r, v) for r, v in lv if v <= xc), (None, None))
        if ent is None:
            return None
        side, kind, stop, tg = d, "W2", x[0], ent + 1.618 * len1
        info = {"ratio": r, "len": len1, "lv": [(rr, d * v) for rr, v in lv]}
    elif p["kind"] == "impulse" and cur == "4":
        len1, len3 = x[1] - x[0], x[3] - x[2]
        lv = [(r, x[3] - r * len3) for r in (0.382, 0.5)]
        r, ent = next(((r, v) for r, v in lv if x[1] < v <= xc), (None, None))
        if ent is None:
            return None
        side, kind, stop, tg = d, "W4", x[1], ent + len1
        info = {"ratio": r, "len": len1, "len3": len3, "lv": [(rr, d * v) for rr, v in lv]}
    elif cur == "C" and p["kind"] == "impulse":                          # 五浪後的 A-B-C：C 往回走
        lenA = x[5] - x[6]
        ent, stop, tg = x[7] - lenA, x[7] - 1.618 * lenA, x[7]
        if not ent <= xc:
            return None
        side, kind = d, "C"
        info = {"lenA": lenA, "lv": [(1.0, d * ent), (1.618, d * stop)]}
    elif cur == "C" and p["kind"] == "correction":                       # 單純 A-B-C：C 跟 A 同方向
        lenA = x[1] - x[0]
        c1, c2 = x[2] + lenA, x[2] + 1.618 * lenA
        if not c1 >= xc:
            return None
        side, kind = -d, "C"
        ent, stop, tg = c1, c2, x[2]
        info = {"lenA": lenA, "lv": [(1.0, d * c1), (1.618, d * c2)]}
        ent, stop, tg = d * ent, d * stop, d * tg                       # 直接換回價格
        return side, kind, ent, stop, tg, info
    else:
        return None
    return side, kind, d * ent, d * stop, d * tg, info


def trade(o, h, l, c, t, side, ent, stop, tg, confirm):
    """第 t 根收盤後掛單（或等確認），固定停損、目標；回 dict 或 None"""
    n = len(c)
    if confirm:
        s, e = t + 1, t + 2
        if e >= n:
            return None
        ok = (l[s] <= ent and c[s] >= ent) if side > 0 else (h[s] >= ent and c[s] <= ent)
        if not ok:
            return None
        fill = o[e]
    else:
        e = t + 1
        if not (l[e] <= ent if side > 0 else h[e] >= ent):
            return None
        fill = min(o[e], ent) if side > 0 else max(o[e], ent)
    if (fill - stop) * side <= 0 or (tg - fill) * side <= 0:
        return None
    risk = (fill - stop) * side
    last = min(n - 1, e + MAX_BARS)

    def out(px, k, why, both=False):
        pts = side * (px - fill) - COST * fill
        return {"ret": side * (px / fill - 1) - COST, "pts": pts, "R": pts / risk, "why": why, "both": both,
                "bars": k - e + 1, "e": e, "k": k, "fill": fill, "exit": px, "tg": tg, "stop": stop, "risk": risk,
                "rr": (tg - fill) * side / risk}

    def hit(k, lv, toward):
        return (h[k] >= lv) if side * toward > 0 else (l[k] <= lv)
    if hit(e, stop, -1):
        return out(stop, e, "停損", both=confirm and hit(e, tg, 1))
    if confirm and hit(e, tg, 1):                                        # 開盤進場：整根都在進場後
        return out(tg, e, "到目標")
    for k in range(e + 1, last + 1):
        if (o[k] - stop) * side <= 0:
            return out(o[k], k, "停損")
        if (o[k] - tg) * side >= 0:
            return out(o[k], k, "到目標")
        hs, ht = hit(k, stop, -1), hit(k, tg, 1)
        if hs:
            return out(stop, k, "停損", both=ht)
        if ht:
            return out(tg, k, "到目標")
    return out(c[last], last, "時間到")


def book(o, h, l, c, prim, trend, dates, side, v):
    trades, t = [], 120
    while t < len(c) - 3:
        st = wave_setup(prim[t], c[t]) if prim[t] else None
        if st is None or st[0] != side or (v["trend"] and trend[t] != side):
            t += 1
            continue
        sd, kind, ent, stop, tg, info = st
        r = trade(o, h, l, c, t, side, ent, stop, tg, v["confirm"])
        if r is None:
            t += 1
            continue
        r.update(t=t, side=side, kind=kind, date=dates[r["e"]], yr=dates[t][:4], trend=int(trend[t]), ent=ent,
                 off_in=(c[t] - ent) * side, off_stop=(c[t] - stop) * side, off_tg=(tg - c[t]) * side, info=info)
        trades.append(r)
        t = r["k"]
    return trades


def placebo(o, h, l, c, trend, dates, trades, v):
    yr = np.array([x[:4] for x in dates])
    idx = np.arange(len(c))
    pools, out = {}, []
    for tr_ in trades:
        key = (tr_["yr"], tr_["trend"] if v["trend"] else 0)
        if key not in pools:
            msk = (yr == tr_["yr"]) & (idx >= 120) & (idx < len(c) - 3)
            if v["trend"]:
                msk &= trend == tr_["trend"]
            pools[key] = idx[msk]
        pool, s = pools[key], tr_["side"]
        got, tries = 0, 0
        while got < N_PLACEBO and tries < 400 and len(pool):
            tries += 1
            t = int(RNG.choice(pool))
            r = trade(o, h, l, c, t, s, c[t] - s * tr_["off_in"], c[t] - s * tr_["off_stop"], c[t] + s * tr_["off_tg"], v["confirm"])
            if r is None:
                continue
            r.update(t=t, date=dates[r["e"]], side=s)
            out.append(r)
            got += 1
    return out


def summ(tr):
    s = C.summ(tr)
    if tr:
        eq = np.cumsum([x["ret"] for x in tr])
        s["mdd"] = round(float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq)), 4)
        s["rr_med"] = round(float(np.median([x["rr"] for x in tr])), 2)
        s["tg_med"] = round(float(np.median([(x["tg"] - x["fill"]) * x["side"] for x in tr])), 0)
    return s


def main():
    t0 = time.time()
    m = pd.read_csv(os.path.join(DATA, "twii_60m.csv")).dropna(subset=["o", "h", "l", "c"])
    m = m[(m.h >= m.l) & (m.c > 0)].reset_index(drop=True)
    d = pd.read_csv(os.path.join(DATA, "twii_d.csv")).dropna(subset=["o", "h", "l", "c"])
    d = d[(d.h >= d.l) & (d.c > 0)].reset_index(drop=True)
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    dates = m.date.astype(str).to_numpy()
    months = np.array([x[:7] for x in dates])
    prim, trend = counts(m, d)
    print("counts", f"{time.time() - t0:.0f}s", flush=True)
    # 數浪狀態有多常出現（每根收盤的主要劇本）
    seen = defaultdict(int)
    for t in range(120, len(c)):
        p = prim[t]
        if p:
            seen[f"{p['kind']}|{p['cur']}|{'+' if p['dir'] > 0 else '-'}"] += 1
        st = wave_setup(p, c[t]) if p else None
        if st:
            seen[f"setup|{'long' if st[0] > 0 else 'short'}|{st[1]}"] += 1
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "data": {"start": dates[0], "end": dates[-1], "bars": len(m)},
           "cost": COST, "max_bars": MAX_BARS, "variants": {k: v["name"] for k, v in V.items()},
           "seen": dict(sorted(seen.items(), key=lambda kv: -kv[1])), "books": {}}
    pv = {}
    for side, sname in ((1, "long"), (-1, "short")):
        for vk, v in V.items():
            tr = book(o, h, l, c, prim, trend, dates, side, v)
            pl = placebo(o, h, l, c, trend, dates, tr, v)
            b = R6.boot([x["ret"] for x in tr], [x["ret"] for x in pl],
                        months[[x["e"] for x in tr]] if tr else np.array([]), months[[x["e"] for x in pl]] if pl else np.array([]))
            years, kinds = defaultdict(list), defaultdict(list)
            for x in tr:
                years[x["date"][:4]].append(x)
                kinds[x["kind"]].append(x)
            key = f"{sname}|{vk}"
            res["books"][key] = {"real": summ(tr), "placebo": summ(pl), "diff": b,
                                 "years": {y: summ(w) for y, w in sorted(years.items())},
                                 "kinds": {k: summ(w) for k, w in sorted(kinds.items())}}
            pv[key] = (b or {}).get("p")
            print(key, res["books"][key]["real"].get("n"), res["books"][key]["real"].get("pts_sum"), f"{time.time() - t0:.0f}s", flush=True)
    q = R6.bh(pv)
    for k, x in res["books"].items():
        x["q"] = round(q[k], 4) if k in q else None
        dd, r = x["diff"] or {}, x["real"]
        yrs = [x["years"].get(y, {}).get("mean", 0) for y in ("2024", "2025", "2026")]
        good = (dd.get("est", 0) > 0 and dd.get("lo", 0) > 0 and (x["q"] or 1) < 0.05 and r.get("mean", 0) > 0
                and sum(1 for y in yrs if y > 0) >= 2)
        x["verdict"] = ("✅" if good else ("✗" if dd.get("hi", 1) < 0 else "△")) + ("" if k in PRIMARY else "（非主要）")
    i0 = 121
    eq = c[i0:] - o[i0]
    res["buy_hold"] = {"pts": round(float(c[-1] - o[i0]), 0), "pts_mdd": round(float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])), 0)}
    try:
        with open(os.path.join(OUT, "b94_60m_c.json")) as f:
            pc_ = json.load(f)
        res["b94c"] = {k: pc_["books"][k]["real"] for k in ("long|D", "long|E", "long|F", "short|E")}
    except (OSError, KeyError):
        res["b94c"] = None
    with open(os.path.join(OUT, "b94_60m_d.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    report(res)
    print("done", f"{time.time() - t0:.0f}s")


def counts_daily(d: pd.DataFrame, deg: str):
    """日 K：網站日線數浪（small／mid）每天收盤的主要劇本；trend 參數＝收盤 vs 年線（同 service._trend）；順勢＝收盤 vs 月線"""
    o, h, l, c = (d[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    key = f"{deg}_{n}_{d.date.iloc[-1]}"
    cache = os.path.join(DATA, f"counts_d_{deg}.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            got = pickle.load(f)
        if got["key"] == key:
            return got["prim"], got["trend"]
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    ma20 = pd.Series(c).rolling(20).mean().to_numpy()
    prim, trend = [None] * n, np.zeros(n)
    for t in range(120, n):
        trend[t] = 1 if c[t] > ma20[t] else -1
        tr = 0 if t + 1 < 240 else (1 if c[t] > float(np.mean(c[t - 239:t + 1])) else -1)
        p = E.analyze(o, h, l, c, deg, t=t, trend=tr, piv=piv).get("primary")
        if p:
            prim[t] = {"kind": p["kind"], "cur": p["current"], "dir": p["dir"], "text": p["text"], "invalid": p["invalid"],
                       "labels": [{"i": q["i"], "p": float(q["p"]), "s": q["disp"], "tent": q["tentative"]} for q in p["labels"]]}
    with open(cache, "wb") as f:
        pickle.dump({"key": key, "prim": prim, "trend": trend}, f)
    return prim, trend


PERIODS = (("2016–18", "2016", "2018"), ("2019–20", "2019", "2020"), ("2021–23", "2021", "2023"), ("2024–26", "2024", "2026"))
PRIMARY_D = ("mid|long|limit", "mid|long|confirm")


def main_daily():
    t0 = time.time()
    d = pd.read_csv(os.path.join(DATA, "twii_d.csv")).dropna(subset=["o", "h", "l", "c"])
    d = d[(d.h >= d.l) & (d.c > 0)].reset_index(drop=True)
    o, h, l, c = (d[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    dates = d.date.astype(str).to_numpy()
    months = np.array([x[:7] for x in dates])
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "data": {"start": dates[0], "end": dates[-1], "bars": len(d)},
           "cost": COST, "max_bars": MAX_BARS, "variants": {k: v["name"] for k, v in V.items()}, "books": {}}
    pv = {}
    for deg in ("small", "mid"):
        prim, trend = counts_daily(d, deg)
        print(deg, "counts", f"{time.time() - t0:.0f}s", flush=True)
        for side, sname in ((1, "long"), (-1, "short")):
            for vk, v in V.items():
                tr_all = [x for x in book(o, h, l, c, prim, trend, dates, side, v) if x["date"] >= "2001"]
                pl_all = placebo(o, h, l, c, trend, dates, tr_all, v)
                key = f"{deg}|{sname}|{vk}"
                res["books"][key] = {}
                for per, a, b in (("ins", "2001", "2015"), ("oos", "2016", "2026")):
                    tr = [x for x in tr_all if a <= x["date"][:4] <= b]
                    pl = [x for x in pl_all if a <= x["date"][:4] <= b]
                    bt = R6.boot([x["ret"] for x in tr], [x["ret"] for x in pl],
                                 months[[x["e"] for x in tr]] if tr else np.array([]), months[[x["e"] for x in pl]] if pl else np.array([]))
                    kinds = defaultdict(list)
                    for x in tr:
                        kinds[x["kind"]].append(x)
                    res["books"][key][per] = {"real": summ(tr), "placebo": summ(pl), "diff": bt, "kinds": {k: summ(w) for k, w in sorted(kinds.items())}}
                    if per == "oos":
                        res["books"][key][per]["periods"] = {nm: summ([x for x in tr if pa <= x["date"][:4] <= pb]) for nm, pa, pb in PERIODS}
                        pv[key] = (bt or {}).get("p")
                print(key, res["books"][key]["ins"]["real"].get("n"), res["books"][key]["oos"]["real"].get("n"),
                      res["books"][key]["oos"]["real"].get("pts_sum"), f"{time.time() - t0:.0f}s", flush=True)
    q = R6.bh(pv)
    for k, x in res["books"].items():
        o_ = x["oos"]
        o_["q"] = round(q[k], 4) if k in q else None
        dd, r = o_["diff"] or {}, o_["real"]
        per = [o_["periods"][nm].get("mean", 0) for nm, _, _ in PERIODS]
        good = (dd.get("est", 0) > 0 and dd.get("lo", 0) > 0 and (o_["q"] or 1) < 0.05 and r.get("mean", 0) > 0
                and sum(1 for y in per if y > 0) >= 3)
        o_["verdict"] = ("✅" if good else ("✗" if dd.get("hi", 1) < 0 else "△")) + ("" if k in PRIMARY_D else "（非主要）")
    i0 = int(np.searchsorted(dates, "2016"))
    res["buy_hold_oos"] = {"pct": round(float(c[-1] / o[i0] - 1), 4)}
    k0 = int(np.searchsorted(dates, "2016"))
    res["random_long_oos"] = round(float(np.mean([c[min(len(c) - 1, t + 1 + MAX_BARS)] / o[t + 1] - 1 for t in range(k0, len(c) - 2)])) - COST, 5)
    with open(os.path.join(OUT, "b94_d_wave.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    report_daily(res)
    print("done daily", f"{time.time() - t0:.0f}s")


def report_daily(res):
    DEG = {"small": "小級（日 K 短線）", "mid": "中級（日 K 波段）"}
    SIDE = {"long": "只做多", "short": "只做空"}
    L = ["", "## 日 K 補充：同一套規則用加權日 K（2001–2026）", "",
         f"資料：加權日 K {res['data']['start']}～{res['data']['end']}。樣本內 2001–2015、樣本外 2016–2026。最多抱 {res['max_bars']} 根（天）。"
         f"樣本外買進抱著 {pc(res['buy_hold_oos']['pct'], 0)}；樣本外隨便哪天買、抱 {res['max_bars']} 天每筆 {pc(res['random_long_oos'])}。", "",
         "| 級數 | 做法 | 樣本內 筆數／勝率／每筆 | 樣本外 筆數 | 勝率 | 到目標／停損／時間到 | 風報比 | 每筆 | 每筆 R | 加總 | 最大回落 | 隨便畫線每筆 | 差 [95%] | q | 4 個時期每筆 | 判定 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, x in res["books"].items():
        deg, sd, vk = k.split("|")
        i_, o_ = x["ins"]["real"], x["oos"]
        r, p, dd = o_["real"], o_["placebo"], o_["diff"]
        ins = "—" if not i_.get("n") else f"{i_['n']}／{i_['win'] * 100:.0f}%／{pc(i_['mean'])}"
        if not r.get("n"):
            L.append(f"| {DEG[deg]} | {SIDE[sd]} {res['variants'][vk]} | {ins} | 0 |" + " |" * 12)
            continue
        w = r["why"]
        per = "、".join("—" if not o_["periods"][nm].get("n") else pc(o_["periods"][nm]["mean"], 1) for nm, _, _ in PERIODS)
        L.append(f"| {DEG[deg]} | {SIDE[sd]} {res['variants'][vk]} | {ins} | {r['n']} | {r['win'] * 100:.0f}% | {w.get('到目標', 0)}／{w.get('停損', 0)}／{w.get('時間到', 0)} | "
                 f"{r['rr_med']} | {pc(r['mean'])} | {r['R_mean']:+.2f} | {pc(r['sum'], 0)} | {pc(-r['mdd'], 0)} | {pc(p.get('mean'))} | "
                 + ("—" if not dd else f"{pc(dd['est'])} [{pc(dd['lo'])}, {pc(dd['hi'])}]") + f" | {o_.get('q') if o_.get('q') is not None else '—'} | {per} | {o_.get('verdict', '')} |")
    L += ["", "### 日 K 樣本外：三種進場時機分開（筆數／勝率／每筆／每筆 R）", "", "| 級數 | 做法 | W2 第 2 浪 | W4 第 4 浪 | C 浪末端 |", "|---|---|---|---|---|"]
    for k, x in res["books"].items():
        deg, sd, vk = k.split("|")
        cells = []
        for kd in ("W2", "W4", "C"):
            s = x["oos"]["kinds"].get(kd)
            cells.append("—" if not s or not s.get("n") else f"{s['n']}／{s['win'] * 100:.0f}%／{pc(s['mean'])}／{s['R_mean']:+.2f}R")
        L.append(f"| {DEG[deg]} | {SIDE[sd]} {res['variants'][vk]} | " + " | ".join(cells) + " |")
    with open(os.path.join(HERE, "REPORT60d.md"), "a") as f:
        f.write("\n".join(L) + "\n")


def pc(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(res):
    SIDE = {"long": "只做多", "short": "只做空"}
    L = ["# B94d：依波浪理論進出（60 分 K、只做多／只做空）", "",
         f"資料：加權 60 分 K {res['data']['start']}～{res['data']['end']}（{res['data']['bars']} 根）。規則見 PLAN60d.md。"
         f"最多抱 {res['max_bars']} 根、成本來回 {res['cost'] * 100:.2f}%。", "",
         "## 主要劇本出現的次數（每根收盤算一次）", "",
         "、".join(f"{k} {v}" for k, v in list(res["seen"].items())[:24]), "",
         "## 結果（一次只抱一筆，扣成本）", "",
         "| 做法 | 筆數 | 勝率 | 到目標／停損／時間到 | 最多連續沒賺 | 停損距離 | 目標距離 | 風報比 | 賺的平均 | 賠的平均 | 每筆點數 | 每筆 R | "
         "點數加總 | 點數最大回落 | 隨便畫線每筆 | 差 [95%] | q | 判定 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, x in res["books"].items():
        sd, vk = k.split("|")
        r, p, dd = x["real"], x["placebo"], x["diff"]
        if not r.get("n"):
            L.append(f"| {SIDE[sd]} {res['variants'][vk]} | 0 |" + " |" * 16)
            continue
        w = r["why"]
        L.append(f"| {SIDE[sd]} {res['variants'][vk]} | {r['n']} | {r['win'] * 100:.0f}% | {w.get('到目標', 0)}／{w.get('停損', 0)}／{w.get('時間到', 0)} | "
                 f"{r['streak']} | {r['risk_med']:.0f} | {r['tg_med']:.0f} | {r['rr_med']} | {r['pts_win'] or 0:+.0f} | {r['pts_loss'] or 0:+.0f} | "
                 f"{r['pts_mean']:+.0f} | {r['R_mean']:+.2f} | {r['pts_sum']:+,.0f} | {-r['pts_mdd']:,.0f} | {pc(p.get('mean'))} | "
                 + ("—" if not dd else f"{pc(dd['est'])} [{pc(dd['lo'])}, {pc(dd['hi'])}]") + f" | {x.get('q') if x.get('q') is not None else '—'} | {x.get('verdict', '')} |")
    L += ["", f"同期間買進 1 口抱著：{res['buy_hold']['pts']:+,.0f} 點（最大回落 {-res['buy_hold']['pts_mdd']:,.0f}）。"]
    if res.get("b94c"):
        L.append("B94c 對照：" + "；".join(f"{k} {v['n']} 筆、{v['pts_sum']:+,.0f} 點、回落 {-v['pts_mdd']:,.0f}" for k, v in res["b94c"].items()) + "。")
    L += ["", "## 三種進場時機分開（點數加總／筆數／勝率／每筆 R）", "", "| 做法 | W2 第 2 浪 | W4 第 4 浪 | C 浪末端 |", "|---|---|---|---|"]
    for k, x in res["books"].items():
        sd, vk = k.split("|")
        cells = []
        for kd in ("W2", "W4", "C"):
            s = x["kinds"].get(kd)
            cells.append("—" if not s or not s.get("n") else f"{s['pts_sum']:+,.0f}（{s['n']} 筆、{s['win'] * 100:.0f}%、{s['R_mean']:+.2f}R）")
        L.append(f"| {SIDE[sd]} {res['variants'][vk]} | " + " | ".join(cells) + " |")
    ys = sorted({y for x in res["books"].values() for y in x["years"]})
    L += ["", "## 各年（點數加總／筆數／勝率）", "", "| 做法 | " + " | ".join(ys) + " |", "|---|" + "---|" * len(ys)]
    for k, x in res["books"].items():
        sd, vk = k.split("|")
        L.append(f"| {SIDE[sd]} {res['variants'][vk]} | " + " | ".join(
            "—" if not x["years"].get(y, {}).get("n") else f"{x['years'][y]['pts_sum']:+,.0f}（{x['years'][y]['n']} 筆、{x['years'][y]['win'] * 100:.0f}%）" for y in ys) + " |")
    with open(os.path.join(HERE, "REPORT60d.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
    main_daily()
