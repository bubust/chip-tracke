"""B94e：60 分數浪決定進場區、15 分 K 決定進出（用戶：「真要進出的時候可以改成 15 分吧」）
規則（事先寫好、跑完不改）見 PLAN60e.md；資料＝research/b94/fetch15.py（證交所每 5 秒指數組成的 15 分 K、60 分 K）。
python research/b94/run15.py → results/b94_15m.json、REPORT15.md"""
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
import run60d as W  # noqa: E402
from wave import engine as E, intraday as I  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
COST = R6.COST
MAX15 = 180                 # 最多抱 180 根 15 分 K（10 個交易日）
N_PLACEBO = 5
RNG = np.random.default_rng(20261108)
V = {"A": "15A 15 分掛單（B94d 規則）", "B": "15B 15 分轉折、停損 15 分低點", "C": "15C 15 分轉折、停損數法失效價"}
PRIMARY = ("long|B",)


def load(name):
    df = pd.read_csv(os.path.join(DATA, name)).dropna(subset=["o", "h", "l", "c"])
    return df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)


def counts60(m60: pd.DataFrame, d: pd.DataFrame):
    """跟 run60d.counts 一樣，只是 60 分 K 換成證交所資料組的（快取另一個檔）"""
    o, h, l, c = (m60[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    key = f"twse_{n}_{m60.date.iloc[-1]}"
    cache = os.path.join(DATA, "counts60_twse.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            got = pickle.load(f)
        if got["key"] == key:
            return got["prim"]
    piv = E.zigzag(h, l, I.theta(h, l, c))
    dd = d.copy()
    dd["ma20"] = dd.c.rolling(20).mean()
    ddate = dd.date.tolist()
    mdate = m60.date.str[:10].tolist()
    prim = [None] * n
    for t in range(120, n):
        k = bisect.bisect_left(ddate, mdate[t]) - 1
        if k < 20:
            continue
        tr = 1 if c[t] > dd.ma20.iloc[k] else -1
        p = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv).get("primary")
        if p:
            prim[t] = {"kind": p["kind"], "cur": p["current"], "dir": p["dir"], "text": p["text"], "invalid": p["invalid"],
                       "labels": [{"i": q["i"], "p": float(q["p"]), "s": q["disp"], "tent": q["tentative"]} for q in p["labels"]]}
    with open(cache, "wb") as f:
        pickle.dump({"key": key, "prim": prim}, f)
    return prim


def zone_setup(p):
    """60 分主要劇本 → 進場區（y 空間＝side×價格，往有利方向是 y 變大）。回 dict 或 None"""
    if not p or p["kind"] not in ("impulse", "correction"):
        return None
    d, cur = p["dir"], p["cur"]
    x = [d * q["p"] for q in p["labels"]]
    I_ = [q["i"] for q in p["labels"]]
    if p["kind"] == "impulse" and cur == "2":
        w1 = x[1] - x[0]
        return {"side": d, "kind": "W2", "lo": x[0], "hi": x[1] - 0.382 * w1, "inval": x[0], "tk": ("len", 1.618 * w1), "t0": I_[1]}
    if p["kind"] == "impulse" and cur == "4":
        w1, w3 = x[1] - x[0], x[3] - x[2]
        return {"side": d, "kind": "W4", "lo": x[1], "hi": x[3] - 0.236 * w3, "inval": x[1], "tk": ("len", w1), "t0": I_[3]}
    if p["kind"] == "impulse" and cur == "C":
        la = x[5] - x[6]
        return {"side": d, "kind": "C", "lo": x[7] - 1.618 * la, "hi": x[7] - 0.618 * la, "inval": x[7] - 1.618 * la, "tk": ("abs", x[7]), "t0": I_[7]}
    if p["kind"] == "correction" and cur == "C":                        # 單純 A-B-C：C 跟 A 同方向，交易方向相反
        la = x[1] - x[0]
        yb = -x[2]
        return {"side": -d, "kind": "C", "lo": yb - 1.618 * la, "hi": yb - 0.618 * la, "inval": yb - 1.618 * la, "tk": ("abs", yb), "t0": I_[2]}
    return None


def target_y(z, ly):
    k, v = z["tk"]
    return ly + v if k == "len" else v


def sim(o, h, l, c, e, fill, side, stop, tg, at_open):
    """從第 e 根（15 分）成交 fill 開始，固定停損、目標；at_open＝開盤進場（整根都在進場後）"""
    n = len(c)
    risk = (fill - stop) * side
    last = min(n - 1, e + MAX15)

    def out(px, k, why, both=False):
        pts = side * (px - fill) - COST * fill
        return {"ret": side * (px / fill - 1) - COST, "pts": pts, "R": pts / risk, "why": why, "both": both, "bars": k - e + 1,
                "e": e, "k": k, "fill": fill, "exit": px, "tg": tg, "stop": stop, "risk": risk, "rr": (tg - fill) * side / risk}

    def hit(k, lv, toward):
        return (h[k] >= lv) if side * toward > 0 else (l[k] <= lv)
    if hit(e, stop, -1):
        return out(stop if (fill - stop) * side > 0 else fill, e, "停損", both=at_open and hit(e, tg, 1))
    if at_open and hit(e, tg, 1):
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


class Ctx:
    """15 分、60 分對齊：j（15 分）收盤時最近一根收完的 60 分是哪一根；60 分第 t 根的第一根 15 分"""

    def __init__(self, m15, m60):
        self.d15 = m15.date.astype(str).to_numpy()
        self.d60 = m60.date.astype(str).to_numpy()
        hour15 = np.array([x[:13] for x in self.d15])                    # 'YYYY-MM-DD HH'
        hour60 = [x[:13] for x in self.d60]
        pos = {hh: k for k, hh in enumerate(hour60)}
        self.k60 = np.array([pos.get(hh, -1) for hh in hour15])           # 這根 15 分屬於哪根 60 分
        last_in = {}
        for j, k in enumerate(self.k60):
            if k >= 0:
                last_in[k] = j
        self.end15 = np.array([last_in.get(k, -1) for k in range(len(self.d60))])
        self.first15 = np.full(len(self.d60), -1)
        for j in range(len(self.d15) - 1, -1, -1):
            if self.k60[j] >= 0:
                self.first15[self.k60[j]] = j
        ok = self.end15 >= 0
        self._ends = self.end15[ok]
        self._ks = np.where(ok)[0]

    def done60(self, j):
        """第 j 根 15 分收盤時，最近一根已經收完的 60 分 K"""
        r = bisect.bisect_right(self._ends, j) - 1
        return int(self._ks[r]) if r >= 0 else -1


def book_A(o, h, l, c, o60, h60, l60, c60, prim, ctx, side):
    """15A：B94d 的掛單（每根 60 分收盤掛、只在下一根 60 分的時間內有效），用 15 分 K 成交、管理"""
    trades, k = [], 120
    while k < len(c60) - 2:
        j_end = ctx.end15[k]
        st = W.wave_setup(prim[k], c60[k]) if prim[k] else None
        if j_end < 0 or st is None or st[0] != side:
            k += 1
            continue
        _, kind, ent, stop, tg, info = st
        nxt = ctx.first15[k + 1] if ctx.first15[k + 1] >= 0 else -1
        fill_j = None
        if nxt >= 0:
            for j in range(nxt, ctx.end15[k + 1] + 1):
                if (l[j] <= ent) if side > 0 else (h[j] >= ent):
                    fill_j = j
                    break
        if fill_j is None:
            k += 1
            continue
        fill = min(o[fill_j], ent) if side > 0 else max(o[fill_j], ent)
        if (fill - stop) * side <= 0 or (tg - fill) * side <= 0:
            k += 1
            continue
        r = sim(o, h, l, c, fill_j, fill, side, stop, tg, at_open=False)
        r.update(sig=j_end, side=side, kind=kind, date=ctx.d15[fill_j], k60=k, ent=ent,
                 off_in=(c[j_end] - ent) * side, info=info, L=None)
        trades.append(r)
        k = max(k + 1, int(ctx.k60[r["k"]]))                             # 出場那根所在的 60 分收盤以後才再掛單
    return trades


def book_B(o, h, l, c, piv15, prim, ctx, side, wide):
    """15B／15C：60 分進場區裡，15 分確認的低點 L、收盤站上 L 前面那個 15 分高點 → 下一根 15 分開盤進"""
    n = len(c)
    ci = np.array([p["ci"] for p in piv15])
    trades, j = [], 0
    zc = {}
    while j < n - 2:
        k = ctx.done60(j)
        if k < 120:
            j += 1
            continue
        if k not in zc:
            zc[k] = zone_setup(prim[k]) if prim[k] else None
        z = zc[k]
        if not z or z["side"] != side:
            j += 1
            continue
        m = bisect.bisect_right(ci, j) - 1                               # 最後一個已確認的 15 分轉折
        if m < 1:
            j += 1
            continue
        P, Q = piv15[m], piv15[m - 1]
        is_low = (P["t"] == "L") if side > 0 else (P["t"] == "H")
        yP, yQ = side * P["p"], side * Q["p"]
        t0_15 = ctx.first15[z["t0"]] if z["t0"] < len(ctx.first15) else -1
        if not is_low or t0_15 < 0 or P["i"] < t0_15 or not (z["lo"] < yP <= z["hi"]) or side * c[j] <= yQ:
            j += 1
            continue
        start = max(P["ci"], P["i"] + 1)
        if any(side * c[q] > yQ for q in range(start, j)):                # 之前已經站上過（不是第一次）
            j += 1
            continue
        e = j + 1
        fill = o[e]
        stop = side * (z["inval"] if wide else yP)
        tg = side * target_y(z, yP)
        if (fill - stop) * side <= 0 or (tg - fill) * side <= 0:
            j += 1
            continue
        r = sim(o, h, l, c, e, fill, side, stop, tg, at_open=True)
        r.update(sig=j, side=side, kind=z["kind"], date=ctx.d15[e], k60=k, L=P["p"], Li=P["i"], Qp=Q["p"], Qi=Q["i"],
                 zone=(side * z["lo"], side * z["hi"]), inval=side * z["inval"])
        trades.append(r)
        j = r["k"] + 1
    return trades


def placebo(o, h, l, c, dates, trades, mode):
    """同一年隨機挑一根 15 分 K；B／C：下一根開盤進、同樣停損目標距離；A：同樣距離掛單（下 4 根內碰到才成交）"""
    yr = np.array([x[:4] for x in dates])
    idx = np.arange(len(c))
    out, pools = [], {}
    for tr_ in trades:
        y = tr_["date"][:4]
        if y not in pools:
            pools[y] = idx[(yr == y) & (idx < len(c) - 6)]
        pool, s = pools[y], tr_["side"]
        d_stop, d_tg = (tr_["fill"] - tr_["stop"]) * s, (tr_["tg"] - tr_["fill"]) * s
        got, tries = 0, 0
        while got < N_PLACEBO and tries < 400 and len(pool):
            tries += 1
            j = int(RNG.choice(pool))
            if mode == "A":
                ent = c[j] - s * tr_["off_in"]
                fj = next((q for q in range(j + 1, min(len(c), j + 5)) if ((l[q] <= ent) if s > 0 else (h[q] >= ent))), None)
                if fj is None:
                    continue
                fill = min(o[fj], ent) if s > 0 else max(o[fj], ent)
                r = sim(o, h, l, c, fj, fill, s, fill - s * d_stop, fill + s * d_tg, at_open=False)
            else:
                e = j + 1
                r = sim(o, h, l, c, e, o[e], s, o[e] - s * d_stop, o[e] + s * d_tg, at_open=True)
            r.update(side=s, date=dates[r["e"]])
            out.append(r)
            got += 1
    return out


def summ(tr):
    s = W.summ(tr)
    return s


def main():
    t0 = time.time()
    m15, m60, d = load("twii_15m.csv"), load("twii_60m_twse.csv"), load("twii_d.csv")
    y60 = load("twii_60m.csv")
    o, h, l, c = (m15[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    o60, h60, l60, c60 = (m60[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    dates = m15.date.astype(str).to_numpy()
    months = np.array([x[:7] for x in dates])
    # 核對：證交所組的 60 分 vs Yahoo 60 分（同一個時間的收盤差幾點）
    mg = m60.merge(y60, on="date", suffixes=("", "_y"))
    chk = {"common": int(len(mg)), "close_diff_med": round(float((mg.c - mg.c_y).abs().median()), 1),
           "close_diff_p95": round(float((mg.c - mg.c_y).abs().quantile(0.95)), 1),
           "high_diff_med": round(float((mg.h - mg.h_y).abs().median()), 1), "low_diff_med": round(float((mg.l - mg.l_y).abs().median()), 1)}
    print("check", chk, flush=True)
    prim = counts60(m60, d)
    ctx = Ctx(m15, m60)
    piv15 = E.zigzag(h, l, I.theta(h, l, c, E.INTRA15))
    print("prep", f"{time.time() - t0:.0f}s", "piv15", len(piv15), flush=True)
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "data": {"start": dates[0], "end": dates[-1], "bars15": len(m15), "bars60": len(m60)},
           "check": chk, "cost": COST, "max15": MAX15, "variants": V, "books": {}}
    pv, keep = {}, {}
    for side, sname in ((1, "long"), (-1, "short")):
        for vk in V:
            tr = (book_A(o, h, l, c, o60, h60, l60, c60, prim, ctx, side) if vk == "A"
                  else book_B(o, h, l, c, piv15, prim, ctx, side, wide=(vk == "C")))
            pl = placebo(o, h, l, c, dates, tr, vk)
            b = R6.boot([x["ret"] for x in tr], [x["ret"] for x in pl],
                        months[[x["e"] for x in tr]] if tr else np.array([]), months[[x["e"] for x in pl]] if pl else np.array([]))
            years, kinds = defaultdict(list), defaultdict(list)
            for x in tr:
                years[x["date"][:4]].append(x)
                kinds[x["kind"]].append(x)
            key = f"{sname}|{vk}"
            keep[key] = tr
            res["books"][key] = {"real": summ(tr), "placebo": summ(pl), "diff": b,
                                 "years": {y: summ(w) for y, w in sorted(years.items())}, "kinds": {k: summ(w) for k, w in sorted(kinds.items())}}
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
    i0 = ctx.first15[120]
    res["buy_hold"] = {"pts": round(float(c[-1] - o[i0]), 0)}
    try:
        with open(os.path.join(OUT, "b94_60m_d.json")) as f:
            pd_ = json.load(f)
        res["b94d"] = {k: pd_["books"][k]["real"] for k in ("long|limit", "short|limit")}
    except (OSError, KeyError):
        res["b94d"] = None
    with open(os.path.join(OUT, "b94_15m.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    with open(os.path.join(DATA, "trades15.pkl"), "wb") as f:              # 圖解用
        pickle.dump(keep, f)
    report(res)
    print("done", f"{time.time() - t0:.0f}s")


def pc(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(res):
    SIDE = {"long": "只做多", "short": "只做空"}
    ck = res["check"]
    L = ["# B94e：60 分數浪定進場區、15 分 K 進出", "",
         f"資料：加權 15 分 K（證交所每 5 秒指數組成）{res['data']['start']}～{res['data']['end']}，{res['data']['bars15']} 根；"
         f"60 分 K 同一份資料組的 {res['data']['bars60']} 根。規則見 PLAN60e.md。最多抱 {res['max15']} 根 15 分 K、成本來回 {res['cost'] * 100:.2f}%。", "",
         f"核對：證交所組的 60 分跟 Yahoo 60 分同時間 {ck['common']} 根，收盤差中位數 {ck['close_diff_med']} 點（95% 在 {ck['close_diff_p95']} 點內）、"
         f"最高差 {ck['high_diff_med']}、最低差 {ck['low_diff_med']}。", "",
         "| 做法 | 筆數 | 勝率 | 到目標／停損／時間到 | 最多連續沒賺 | 停損距離 | 目標距離 | 風報比 | 賺的平均 | 賠的平均 | 每筆點數 | 每筆 R | "
         "點數加總 | 點數最大回落 | 隨便挑每筆 | 差 [95%] | q | 判定 |",
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
    L += ["", f"同期間買進 1 口抱著：{res['buy_hold']['pts']:+,.0f} 點。"]
    if res.get("b94d"):
        L.append("B94d（60 分掛單）對照：" + "；".join(f"{k} {v['n']} 筆、{v['pts_sum']:+,.0f} 點" for k, v in res["b94d"].items()) + "。")
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
    with open(os.path.join(HERE, "REPORT15.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
