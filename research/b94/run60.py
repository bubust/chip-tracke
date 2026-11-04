"""B94b 精確版回測（用戶：「回測條件要精確一點，要做多就不會空，用 60 分 K 看，做多支撐區買進、到壓力區就賣，反之」）
規則（事先寫好、跑完不改）見 PLAN60.md；資料＝加權 60 分 K（Yahoo，research/b94/fetch.py 在 GitHub Actions 抓）。
python research/b94/run60.py → results/b94_60m.json、REPORT60.md"""
import bisect
import json
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
COST = 0.0002               # 來回 0.02%（4 萬點約 9 點；台指期實際手續費＋稅約 2～4 點，偏保守）
MAX_BARS = 25               # 最多抱 25 根 60 分 K（5 個交易日）
N_PLACEBO = 5
N_BOOT = 2000
RNG = np.random.default_rng(20261105)
STOPS = {"atr": "支撐區下緣再往下 1 個 ATR（觸價就停損）", "close": "60 分 K 收盤跌破支撐區下緣就停損", "none": "不設停損"}


def zones_60m(m: pd.DataFrame, d: pd.DataFrame):
    """每根 60 分 K 收盤：網站 build_ultra 的最近支撐區（lo、hi）、最近壓力區（lo、hi）、ATR；trend＝前一天日 K 收盤 vs 月線"""
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    n = len(c)
    piv = E.zigzag(h, l, I.theta(h, l, c))
    atr = E.atr(h, l, c)
    z = {k: np.full(n, np.nan) for k in ("s_lo", "s_hi", "r_lo", "r_hi")}
    trend = np.zeros(n)
    dd = d.copy()
    dd["ma20"] = dd.c.rolling(20).mean()
    ddate = dd.date.tolist()
    mdate = m.date.str[:10].tolist()
    for t in range(120, n):
        if not np.isfinite(atr[t]):
            continue
        k = bisect.bisect_left(ddate, mdate[t]) - 1                    # 前一個交易日（今天的日 K 還沒收）
        if k < 20:
            continue
        prev = dd.iloc[k]
        daily = {"prev_h": float(prev.h), "prev_l": float(prev.l), "prev_c": float(prev.c), "ma20": float(prev.ma20)}
        trend[t] = 1 if prev.c > prev.ma20 else -1                       # 順勢版用：前一天收盤在月線上＝只做多
        tr = 1 if c[t] > daily["ma20"] else -1                           # 網站 60 分數浪用的 trend
        an = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv)
        b = LV.build_ultra(h, l, c, t, an, float(atr[t]), float(c[t]), daily=daily)
        if b["support"]:
            z["s_lo"][t], z["s_hi"][t] = b["support"][0]["lo"], b["support"][0]["hi"]
        if b["resistance"]:
            z["r_lo"][t], z["r_hi"][t] = b["resistance"][0]["lo"], b["resistance"][0]["hi"]
    return z, atr, trend


def trade(o, h, l, c, t, side, entry_lv, zone_far, target, A, stop_kind):
    """第 t 根收盤掛單、第 t+1 根成交。side=+1 做多（entry_lv＝支撐區上緣、zone_far＝支撐區下緣、target＝壓力區下緣）；
    side=-1 放空（entry_lv＝壓力區下緣、zone_far＝壓力區上緣、target＝支撐區上緣）。
    回 dict(ret, pts, why, bars, fill, exit)；不成交回 None"""
    n = len(c)
    e = t + 1
    touched = l[e] <= entry_lv if side > 0 else h[e] >= entry_lv
    if not touched:
        return None
    fill = min(o[e], entry_lv) if side > 0 else max(o[e], entry_lv)
    if (target - fill) * side <= 0:
        return None
    stop = zone_far - side * A if stop_kind == "atr" else None
    last = min(n - 1, e + MAX_BARS)

    def out(px, k, why):
        return {"ret": side * (px / fill - 1) - COST, "pts": side * (px - fill) - COST * fill, "why": why, "bars": k - e + 1,
                "fill": fill, "exit": px}
    # 進場那根：只檢查停損（看不到同一根裡的先後；保守）
    if stop is not None and ((side > 0 and l[e] <= stop) or (side < 0 and h[e] >= stop)):
        return out(fill if (fill - stop) * side <= 0 else stop, e, "停損")
    if stop_kind == "close" and (c[e] - zone_far) * side < 0:
        return out(c[e], e, "停損")
    for k in range(e + 1, last + 1):
        if stop is not None and (o[k] - stop) * side <= 0:                # 跳空越過停損
            return out(o[k], k, "停損")
        if (o[k] - target) * side >= 0:                                  # 跳空越過目標
            return out(o[k], k, "到目標")
        if stop is not None and ((side > 0 and l[k] <= stop) or (side < 0 and h[k] >= stop)):
            return out(stop, k, "停損")                                   # 同一根停損、目標都碰到 → 算停損（保守）
        if (side > 0 and h[k] >= target) or (side < 0 and l[k] <= target):
            return out(target, k, "到目標")
        if stop_kind == "close" and (c[k] - zone_far) * side < 0:
            return out(c[k], k, "停損")
    return out(c[last], last, "時間到")


def setup(z, t, side):
    """第 t 根的掛單參數 (進場價, 區的另一邊, 目標)；沒有支撐或壓力回 None"""
    if side > 0:
        a, b, g = z["s_hi"][t], z["s_lo"][t], z["r_lo"][t]
    else:
        a, b, g = z["r_lo"][t], z["r_hi"][t], z["s_hi"][t]
    return None if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(g)) else (a, b, g)


def book(o, h, l, c, z, atr, trend, dates, side_mode, stop_kind):
    """一次只抱一筆。side_mode：'long'＝只做多、'short'＝只做空、'trend'＝前一天收盤在月線上只做多、下只做空"""
    trades, t = [], 120
    while t < len(c) - 2:
        side = 1 if side_mode == "long" else -1 if side_mode == "short" else int(trend[t])
        st = setup(z, t, side) if side else None
        if st is None or not np.isfinite(atr[t]):
            t += 1
            continue
        r = trade(o, h, l, c, t, side, st[0], st[1], st[2], atr[t], stop_kind)
        if r is None:
            t += 1
            continue
        r.update(t=t, side=side, date=dates[t + 1], atr=float(atr[t]), d_in=(c[t] - st[0]) / atr[t] * side,
                 d_far=(c[t] - st[1]) / atr[t] * side, d_tg=(st[2] - c[t]) / atr[t] * side)
        trades.append(r)
        t = t + r["bars"]                                                 # 出場那根收盤後才找下一筆
    return trades


def placebo(o, h, l, c, atr, trades, stop_kind):
    """每筆真交易：隨機挑一根，用同樣的 ATR 距離畫假支撐／假壓力，同樣規則（不連續、只看每筆平均）"""
    out, pool = [], np.arange(120, len(c) - 2)
    for tr_ in trades:
        got, tries = 0, 0
        while got < N_PLACEBO and tries < 80:
            tries += 1
            t = int(RNG.choice(pool))
            A = atr[t]
            if not np.isfinite(A) or A <= 0:
                continue
            s = tr_["side"]
            ent = c[t] - s * tr_["d_in"] * A
            far = c[t] - s * tr_["d_far"] * A
            tg = c[t] + s * tr_["d_tg"] * A
            r = trade(o, h, l, c, t, s, ent, far, tg, A, stop_kind)
            if r is None:
                continue
            r["date"] = None
            r["t"] = t
            out.append(r)
            got += 1
    return out


def summ(tr):
    if not tr:
        return {"n": 0}
    r = np.array([x["ret"] for x in tr])
    p = np.array([x["pts"] for x in tr])
    eq = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq))
    gain, loss = r[r > 0].sum(), -r[r < 0].sum()
    why = defaultdict(int)
    for x in tr:
        why[x["why"]] += 1
    peq = np.cumsum(p)
    pdd = float(np.max(np.maximum.accumulate(np.r_[0, peq])[1:] - peq))
    return {"n": len(tr), "win": round(float((r > 0).mean()), 4), "mean": round(float(r.mean()), 5), "sum": round(float(r.sum()), 4),
            "pts_mean": round(float(p.mean()), 1), "pts_sum": round(float(p.sum()), 0), "pts_mdd": round(pdd, 0),
            "pf": round(float(gain / loss), 3) if loss > 0 else None, "mdd": round(dd, 4),
            "bars": round(float(np.mean([x["bars"] for x in tr])), 1), "why": dict(why),
            "avg_win": round(float(r[r > 0].mean()), 5) if (r > 0).any() else None,
            "avg_loss": round(float(r[r <= 0].mean()), 5) if (r <= 0).any() else None}


def boot(real, plac, mr, mp):
    real, plac = np.asarray(real), np.asarray(plac)
    if len(real) < 10 or len(plac) < 10:
        return None
    ug = np.unique(np.r_[mr, mp])
    ir = {g: np.where(mr == g)[0] for g in ug}
    ip = {g: np.where(mp == g)[0] for g in ug}
    vals = []
    for _ in range(N_BOOT):
        pk = RNG.choice(ug, size=len(ug), replace=True)
        a = np.concatenate([ir[g] for g in pk])
        b = np.concatenate([ip[g] for g in pk])
        if len(a) and len(b):
            vals.append(real[a].mean() - plac[b].mean())
    vals = np.array(vals)
    lo, hi = np.quantile(vals, [0.025, 0.975])
    return {"est": round(float(real.mean() - plac.mean()), 5), "lo": round(float(lo), 5), "hi": round(float(hi), 5),
            "p": round(float(max(2 * min((vals <= 0).mean(), (vals >= 0).mean()), 1 / N_BOOT)), 4)}


def bh(pv):
    ks = [k for k, v in pv.items() if v is not None]
    ps = np.array([pv[k] for k in ks])
    if not len(ps):
        return {}
    order = np.argsort(ps)
    q, prev, m = np.empty(len(ps)), 1.0, len(ps)
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    return {k: float(q[j]) for j, k in enumerate(ks)}


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
    z, atr, trend = zones_60m(m, d)
    print("zones", f"{time.time() - t0:.0f}s", flush=True)
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "data": {"start": dates[0], "end": dates[-1], "bars": len(m)},
           "cost": COST, "max_bars": MAX_BARS, "stops": STOPS, "atr_median": {}, "zone": {}, "books": {}, "baseline": {}}
    for y in sorted({x[:4] for x in dates}):
        ii = [i for i in range(len(dates)) if dates[i][:4] == y and np.isfinite(atr[i])]
        res["atr_median"][y] = {"pts": round(float(np.median(atr[ii])), 0), "pct": round(float(np.median(atr[ii] / c[ii])) * 100, 2)}
    ok = np.isfinite(z["s_hi"]) & np.isfinite(z["r_lo"])
    res["zone"] = {"s_dist_pct": round(float(np.nanmedian((c - z["s_hi"])[ok] / c[ok])) * 100, 2),
                   "r_dist_pct": round(float(np.nanmedian((z["r_lo"] - c)[ok] / c[ok])) * 100, 2),
                   "s_width_pct": round(float(np.nanmedian((z["s_hi"] - z["s_lo"])[ok] / c[ok])) * 100, 2),
                   "both_pct": round(float(ok[120:].mean()), 3)}
    pv = {}
    for mode in ("long", "short", "trend"):
        for sk in STOPS:
            tr = book(o, h, l, c, z, atr, trend, dates, mode, sk)
            pl = placebo(o, h, l, c, atr, tr, sk)
            b = boot([x["ret"] for x in tr], [x["ret"] for x in pl], months[[x["t"] + 1 for x in tr]] if tr else np.array([]),
                     months[[x["t"] + 1 for x in pl]] if pl else np.array([]))
            years = defaultdict(list)
            for x in tr:
                years[x["date"][:4]].append(x)
            key = f"{mode}|{sk}"
            res["books"][key] = {"real": summ(tr), "placebo": summ(pl), "diff": b, "years": {y: summ(v) for y, v in sorted(years.items())},
                                 "long": summ([x for x in tr if x["side"] > 0]), "short": summ([x for x in tr if x["side"] < 0]),
                                 "sample": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in x.items() if k in ("date", "side", "fill", "exit", "why", "bars", "pts")}
                                            for x in tr[-8:]]}
            pv[key] = (b or {}).get("p")
            print(key, res["books"][key]["real"].get("n"), f"{time.time() - t0:.0f}s", flush=True)
    q = bh(pv)
    for k, v in res["books"].items():
        v["q"] = round(q[k], 4) if k in q else None
    # 對照：同期間買進抱著；每天隨便一根進場抱 25 根
    i0 = 120
    res["baseline"] = {"buy_hold": round(float(c[-1] / o[i0 + 1] - 1), 4),
                       "random_25_long": round(float(np.mean([c[min(len(c) - 1, t + 1 + MAX_BARS)] / o[t + 1] - 1 for t in range(i0, len(c) - 2)])) - COST, 5)}
    with open(os.path.join(OUT, "b94_60m.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    report(res)
    print("done", f"{time.time() - t0:.0f}s")


def pc(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(res):
    MODE = {"long": "只做多（支撐區買、壓力區賣）", "short": "只做空（壓力區空、支撐區補）", "trend": "順勢（前一天在月線上只做多、下只做空）"}
    L = ["# B94b 精確版：60 分 K 只做多／只做空（網站的支撐區、壓力區）", "",
         f"資料：加權 60 分 K {res['data']['start']}～{res['data']['end']}（{res['data']['bars']} 根，一天 5 根）。規則見 PLAN60.md。"
         f"成本來回 {res['cost'] * 100:.2f}%、最多抱 {res['max_bars']} 根（5 個交易日）。", "",
         "60 分 K 的 1 ATR（最近 14 根平均波動）中位數：" + "、".join(f"{y} 年 {v['pts']:.0f} 點（{v['pct']}%）" for y, v in res["atr_median"].items()) + "。",
         f"最近的支撐區上緣離現價中位數 {res['zone']['s_dist_pct']}%、壓力區下緣 {res['zone']['r_dist_pct']}%、支撐區寬 {res['zone']['s_width_pct']}%。", "",
         "| 做法 | 停損 | 筆數 | 勝率 | 到目標／停損／時間到 | 每筆平均 | 每筆點數 | 加總 | 點數加總 | 點數最大回落 | 獲利因子 | 隨便畫線每筆 | 差 [95%] | q |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["books"].items():
        mode, sk = k.split("|")
        r, p, dd = v["real"], v["placebo"], v["diff"]
        if not r.get("n"):
            continue
        w = r["why"]
        stop_t = {"atr": "區的外緣再 1 ATR（觸價）", "close": "收盤穿過區的外緣", "none": "不設停損"}[sk]
        L.append(f"| {MODE[mode]} | {stop_t} | {r['n']} | {pc(r['win'], 0)} | {w.get('到目標', 0)}／{w.get('停損', 0)}／{w.get('時間到', 0)} "
                 f"| {pc(r['mean'])} | {r['pts_mean']:+.0f} | {pc(r['sum'], 1)} | {r['pts_sum']:+,.0f} | {-r['pts_mdd']:,.0f} | {r.get('pf') or '—'} | {pc(p.get('mean'))} | "
                 + ("—" if not dd else f"{pc(dd['est'])} [{pc(dd['lo'])}, {pc(dd['hi'])}]") + f" | {v.get('q') if v.get('q') is not None else '—'} |")
    b = res["baseline"]
    L += ["", f"對照：同期間第一天買進抱到最後 {pc(b['buy_hold'], 1)}；任何一根隨便買、抱 25 根，每筆平均 {pc(b['random_25_long'])}。", "",
          "## 各年（只做多、1 ATR 停損／只做空、1 ATR 停損）", "", "| 年 | 只做多 筆數 | 勝率 | 加總 | 只做空 筆數 | 勝率 | 加總 |", "|---|---|---|---|---|---|---|"]
    yl, ys = res["books"]["long|atr"]["years"], res["books"]["short|atr"]["years"]
    for y in sorted(set(yl) | set(ys)):
        a, s = yl.get(y, {"n": 0}), ys.get(y, {"n": 0})
        L.append(f"| {y} | {a.get('n', 0)} | {pc(a.get('win'), 0) if a.get('n') else '—'} | {pc(a.get('sum'), 1) if a.get('n') else '—'} | "
                 f"{s.get('n', 0)} | {pc(s.get('win'), 0) if s.get('n') else '—'} | {pc(s.get('sum'), 1) if s.get('n') else '—'} |")
    with open(os.path.join(HERE, "REPORT60.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
