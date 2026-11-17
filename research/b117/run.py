"""B117 回測：四大金剛 項目1（日 K 分數）、項目9 KSAR（60 分 K），規則見 PLAN.md（照他們網頁的程式抄）。
用法：python research/b117/run.py  → results/b117.json、REPORT.md"""
import json
import math
import os
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
COST = 0.00585                     # 來回：手續費 0.1425%×2＋證交稅 0.3%
N_CTRL = 5
N_BOOT = 2000
RNG = np.random.default_rng(117)


# ── 指標（照他們的 JS）──────────────────────────────────────────────────────
def ema(a, span):
    al = 2.0 / (span + 1.0)
    r = np.empty(len(a))
    r[0] = a[0]
    for i in range(1, len(a)):
        r[i] = a[i] * al + r[i - 1] * (1 - al)
    return r


def sma(a, span):
    c = np.cumsum(np.r_[0.0, a])
    i = np.arange(len(a))
    st = np.maximum(0, i - span + 1)
    return (c[i + 1] - c[st]) / (i - st + 1)


def boll(c):
    mid = sma(c, 20)
    n = len(c)
    std = np.empty(n)
    for i in range(n):
        s = max(0, i - 19)
        w = c[s:i + 1]
        std[i] = math.sqrt(((w - mid[i]) ** 2).mean())
    return mid, mid + 2 * std, mid - 2 * std


def kdj(h, l, c):
    n = len(c)
    k, d = np.full(n, 50.0), np.full(n, 50.0)
    for i in range(n):
        s = max(0, i - 8)
        lo, hi = l[s:i + 1].min(), h[s:i + 1].max()
        rsv = 50.0 if hi == lo else (c[i] - lo) / (hi - lo) * 100
        pk, pd_ = (k[i - 1], d[i - 1]) if i else (50.0, 50.0)
        k[i] = 2 / 3 * pk + rsv / 3
        d[i] = 2 / 3 * pd_ + k[i] / 3
    return k, d, 3 * k - 2 * d


def sar1(h, l):
    """項目1 的 SAR（precipitation）"""
    n = len(h)
    sar, tr = np.zeros(n), np.ones(n)
    bull, af, ep = True, 0.02, h[0]
    sar[0] = l[0]
    for i in range(1, n):
        cur = sar[i - 1] + af * (ep - sar[i - 1])
        if bull:
            cur = min(cur, l[i - 1], l[i - 2]) if i >= 2 else min(cur, l[i - 1])
            if l[i] < cur:
                bull, cur, ep, af = False, ep, l[i], 0.02
            elif h[i] > ep:
                ep, af = h[i], min(0.2, af + 0.02)
        else:
            cur = max(cur, h[i - 1], h[i - 2]) if i >= 2 else max(cur, h[i - 1])
            if h[i] > cur:
                bull, cur, ep, af = True, ep, h[i], 0.02
            elif l[i] < ep:
                ep, af = l[i], min(0.2, af + 0.02)
        sar[i], tr[i] = cur, 1 if bull else -1
    return sar, tr


def score_item1(df):
    """df：一檔的日 K（t, o, h, l, c, v）。回每天的 (分數, 月線支撐過濾)；照 computeItem1Strategy"""
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("o", "h", "l", "c", "v"))
    n = len(c)
    e5, e20, e60 = ema(c, 5), ema(c, 20), ema(c, 60)
    mv5, mv20 = sma(v, 5), sma(v, 20)
    mid, up, dn = boll(c)
    bw = np.where(mid > 0, (up - dn) / np.where(mid > 0, mid, 1), 0.2)
    k, d, _ = kdj(h, l, c)
    dif = ema(c, 12) - ema(c, 26)
    osc = 2 * (dif - ema(dif, 9))
    _, st = sar1(h, l)
    # 週線：ISO 週；當週還沒走完的那週收盤＝今天收盤（他們用切到第 t 天的資料重組週 K）
    wk = pd.to_datetime(df.t).dt.isocalendar()
    wkey = (wk.year.astype(int) * 100 + wk.week.astype(int)).to_numpy()
    score = np.full(n, np.nan)
    trend = np.zeros(n, bool)
    done = []                                                         # 已走完的週收盤
    for i in range(n):
        if i and wkey[i] != wkey[i - 1]:
            done.append(c[i - 1])
        if i < 20:
            continue
        wcl = done + [c[i]]
        wn = len(wcl)
        if wn >= 20:
            ma = np.mean(wcl[-20:])
            prev_w = wcl[:-1]
            ma_p = np.mean(prev_w[-20:])
            above, wup = wcl[-1] > ma, ma > ma_p
        else:
            above, wup = c[i] > e20[i], e20[i] > e20[i - 1]
        s = 30 if above and wup else 18 if above else -10
        s += 25 if bw[i] < 0.15 else 18 if bw[i] < 0.20 else (-5 if bw[i] > 0.40 else 0)
        if v[i] < mv5[i] and v[i] < mv20[i]:
            s += 25
        elif mv5[i] <= v[i] <= mv5[i] * 1.6:
            s += 18
        elif v[i] > mv5[i] * 2.2:
            s -= 10
        red = c[i] > o[i]
        rg = h[i] - l[i]
        pos = (c[i] - l[i]) / rg if rg > 0 else 0.5
        if c[i] > up[i]:
            pass
        elif red and (c[i] - o[i]) / o[i] > 0.03:
            s += 20
        elif red:
            s += 12
        elif pos <= 0.35:
            s += 15
        bull = e5[i] > e20[i] > e60[i]
        e20up = e20[i] > e20[i - 1]
        near = abs(c[i] - e20[i]) / e20[i] <= 0.04
        overs = c[i] <= dn[i] * 1.03 or k[i] < 25
        s += 12 if bull else 8 if (e20up and near) else 10 if overs else 0
        s += 8 if st[i] == 1 else 0
        s += 6 if k[i] > d[i] else 0
        s += 6 if (osc[i] > 0 or dif[i] > dif[i] - osc[i] / 2) else 0
        score[i] = min(100, max(0, s))
        trend[i] = bull or (e20up and c[i] >= e20[i] * 0.98) or c[i] >= e20[i] or overs
    return score, trend


def ksar(h, l, c):
    """項目9 KSAR（ksar-trade 的 computeAllIndicators）"""
    n = len(c)
    sar = np.zeros(n)
    bull, af, ep = True, 0.02, h[0]
    sar[0] = l[0]
    for i in range(1, n):
        p = sar[i - 1]
        if bull:
            cs = min(p + af * (ep - p), l[i - 1])
            if i >= 2:
                cs = min(cs, l[i - 2])
            if l[i] < cs:
                bull, cs, ep, af = False, ep, l[i], 0.02
            elif h[i] > ep:
                ep, af = h[i], min(af + 0.02, 0.2)
        else:
            cs = max(p - af * (p - ep), h[i - 1])
            if i >= 2:
                cs = max(cs, h[i - 2])
            if h[i] > cs:
                bull, cs, ep, af = True, ep, h[i], 0.02
            elif l[i] < ep:
                ep, af = l[i], min(af + 0.02, 0.2)
        sar[i] = cs
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = sma(tr, 14)
    _, _, j = kdj(h, l, c)
    dist = (c - sar) / np.where(atr > 0, atr, 1)
    return 0.5 * np.clip(j, 0, 100) + 0.5 * (50 + 50 * np.tanh(dist / 2))


# ── 統計 ─────────────────────────────────────────────────────────────────────
def boot(real, plac, mr, mp):
    real, plac = np.asarray(real, float), np.asarray(plac, float)
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
    return {"est": float(real.mean() - plac.mean()), "lo": float(lo), "hi": float(hi),
            "p": float(max(2 * min((vals <= 0).mean(), (vals >= 0).mean()), 1 / N_BOOT))}


def bh(pv):
    ks = [k for k, v in pv.items() if v is not None]
    ps = np.array([pv[k] for k in ks])
    order = np.argsort(ps)
    q, prev, m = np.empty(len(ps)), 1.0, len(ps)
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    return {k: float(q[j]) for j, k in enumerate(ks)}


# ── 進出場 ───────────────────────────────────────────────────────────────────
def trades(sig, hold):
    """sig：{tk: bool 陣列}；同一檔出場前不重複進場 → [(tk, t)]"""
    out = []
    for tk, s in sig.items():
        nxt = 0
        for t in np.flatnonzero(s):
            if t >= nxt:
                out.append((tk, t))
                nxt = t + hold + 1
    return out


def run_set(name, events, panel, hold, keyfun, metric="ret"):
    """events：[(tk, t)]；panel：{tk: (o, h, l, c, key[])}；keyfun(tk, t)→ 時間鍵（同一天／同一根）
    報酬＝第 t+1 根開盤買、第 t+hold 根收盤賣；metric='runup'＝t+1～t+hold 最高價 ÷ 第 t 根收盤 −1 ≥ 20%"""
    by_key = {}
    for tk, (o, h, l, c, keys) in panel.items():
        for t in range(len(c) - hold):
            by_key.setdefault(keys[t], []).append((tk, t))

    def val(tk, t):
        o, h, l, c, _ = panel[tk]
        if metric == "runup":
            return float(h[t + 1:t + hold + 1].max() / c[t] - 1 >= 0.20)
        return c[t + hold] / o[t + 1] - 1 - COST
    real, plac, mr, mp, yr = [], [], [], [], []
    for tk, t in events:
        o, h, l, c, keys = panel[tk]
        if t + hold >= len(c) or o[t + 1] <= 0:
            continue
        k = keys[t]
        pool = [x for x in by_key.get(k, []) if x[0] != tk]
        if len(pool) < N_CTRL:
            continue
        real.append(val(tk, t))
        mr.append(k[:7])
        yr.append(k[:4])
        for j in RNG.choice(len(pool), N_CTRL, replace=False):
            plac.append(val(*pool[j]))
            mp.append(k[:7])
    real, plac, mr, mp, yr = map(np.asarray, (real, plac, mr, mp, yr))
    py = np.repeat(yr, N_CTRL)
    years = {y: {"n": int((yr == y).sum()), "diff": float(real[yr == y].mean() - plac[py == y].mean())} for y in sorted(set(yr))}
    return {"name": name, "n": int(len(real)), "real": float(real.mean()) if len(real) else None,
            "ctrl": float(plac.mean()) if len(plac) else None, "win": float((real > 0).mean()) if len(real) and metric == "ret" else None,
            "boot": boot(real, plac, mr, mp), "years": years}


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "tests": {}, "desc": {}}
    # ── A：日 K ──
    d = pd.read_csv(os.path.join(DATA, "daily.csv.gz"), dtype={"tk": str})
    d = d[(d.h >= d.l) & (d.c > 0) & (d.o > 0)].sort_values(["tk", "t"])
    panel, sig = {}, {k: {} for k in ("A55", "A65", "A85", "A55T")}
    for tk, g in d.groupby("tk"):
        g = g.reset_index(drop=True)
        if len(g) < 130:
            continue
        sc, tr = score_item1(g)
        vol_ok = g.v.to_numpy(float) > 0
        keys = g.t.astype(str).to_numpy()
        panel[tk] = (g.o.to_numpy(float), g.h.to_numpy(float), g.l.to_numpy(float), g.c.to_numpy(float), keys)
        ok = ~np.isnan(sc) & vol_ok
        sig["A55"][tk] = ok & (sc >= 55)
        sig["A65"][tk] = ok & (sc >= 65)
        sig["A85"][tk] = ok & (sc >= 85)
        sig["A55T"][tk] = ok & (sc >= 55) & tr
    print("A 分數", len(panel), f"{time.time() - t0:.0f}s", flush=True)
    res["data"] = {"daily": {"stocks": len(panel), "start": str(d.t.min()), "end": str(d.t.max())}}
    kf = None
    A = {}
    for nm in ("A55", "A65", "A85", "A55T"):
        ev = trades(sig[nm], 5)
        A[nm] = run_set(nm, ev, panel, 5, kf)
        print(nm, A[nm]["n"], f"{time.time() - t0:.0f}s", flush=True)
    A["A55_runup"] = run_set("A55_runup", trades(sig["A55"], 5), panel, 5, kf, metric="runup")
    # ── B：60 分 K ──
    m = pd.read_csv(os.path.join(DATA, "h60.csv.gz"), dtype={"tk": str})
    m = m[(m.h >= m.l) & (m.c > 0) & (m.o > 0)].sort_values(["tk", "t"])
    p60, s60 = {}, {k: {} for k in ("B80", "B50", "B35")}
    for tk, g in m.groupby("tk"):
        g = g.reset_index(drop=True)
        if len(g) < 100:
            continue
        o, h, l, c = (g[k].to_numpy(float) for k in ("o", "h", "l", "c"))
        ks = ksar(h, l, c)
        pv = np.r_[np.nan, ks[:-1]]
        warm = np.arange(len(c)) >= 30
        p60[tk] = (o, h, l, c, g.t.astype(str).to_numpy())
        s60["B80"][tk] = warm & (pv < 80) & (ks >= 80)
        s60["B50"][tk] = warm & (pv < 50) & (ks >= 50)
        s60["B35"][tk] = warm & (pv >= 35) & (ks < 35)
    res["data"]["h60"] = {"stocks": len(p60), "start": str(m.t.min()), "end": str(m.t.max())}
    B = {}
    for nm in ("B80", "B50", "B35"):
        B[nm] = run_set(nm, trades(s60[nm], 5), p60, 5, kf)
        B[nm + "_25"] = run_set(nm + "_25", trades(s60[nm], 25), p60, 25, kf)
        print(nm, B[nm]["n"], f"{time.time() - t0:.0f}s", flush=True)
    allr = {**A, **B}
    main_t = {"H1": "A55", "H2": "A85", "H3": "A55_runup", "H4": "B80", "H5": "B50"}
    q = bh({h: (allr[k]["boot"] or {}).get("p") for h, k in main_t.items()})
    for h, k in main_t.items():
        r = allr[k]
        b = r["boot"] or {}
        yrs = [y["diff"] for y in r["years"].values() if y["n"] >= 30]
        same = sum(1 for x in yrs if (x > 0) == (b.get("est", 0) > 0)) / len(yrs) if yrs else 0
        ok = (b and b["est"] > 0 and b["lo"] > 0 and q.get(h, 1) < 0.05 and (r["real"] > 0 if k != "A55_runup" else True) and same > 0.5)
        bad = b and b["hi"] < 0
        res["tests"][h] = {"set": k, "q": q.get(h), "verdict": "✅" if ok else "✗" if bad else "△", **{x: r[x] for x in ("n", "real", "ctrl")},
                           "boot": b, "years_same": same}
    res["desc"] = allr
    json.dump(res, open(os.path.join(OUT, "b117.json"), "w"), ensure_ascii=False, indent=1)
    write_report(res)
    print("done", f"{time.time() - t0:.0f}s")


def pct(x, nd=2):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def write_report(res):
    L = ["# B117 回測結果：四大金剛 項目1（日 K 分數）、項目9 KSAR（60 分 K）", "",
         f"產生：{res['generated']}；日 K {res['data']['daily']['stocks']} 檔（{res['data']['daily']['start']}～{res['data']['daily']['end']}）、"
         f"60 分 K {res['data']['h60']['stocks']} 檔（{res['data']['h60']['start']}～{res['data']['h60']['end']}）", "",
         "報酬＝隔天（下一根）開盤買、持有期最後一根收盤賣，已扣來回成本 0.585%。隨機＝同一天（同一根）隨便挑 5 檔、同樣進出。", "",
         "## 主要檢定", "", "| 代號 | 內容 | 筆數 | 平均報酬 | 隨機 | 差（95% 區間） | q | 結果 |", "|---|---|---|---|---|---|---|---|"]
    nm = {"H1": "項目1 ≥55 分，5 天", "H2": "項目1 ≥85 分，5 天", "H3": "項目1 ≥55 分，5 天內最高漲 ≥20% 的比例", "H4": "KSAR 升破 80，5 根",
          "H5": "KSAR 升破 50，5 根"}
    for h, t in res["tests"].items():
        b = t["boot"] or {}
        L.append(f"| {h} | {nm[h]} | {t['n']:,} | {pct(t['real'])} | {pct(t['ctrl'])} | {pct(b.get('est'))}（{pct(b.get('lo'))}～{pct(b.get('hi'))}） | "
                 f"{t['q']:.3f} | {t['verdict']} |" if b else f"| {h} | {nm[h]} | {t['n']} | — | — | — | — | △ |")
    L += ["", "## 全部版本（非主要的只當線索）", "", "| 版本 | 筆數 | 平均報酬 | 勝率 | 隨機 | 差 | 分年（差） |", "|---|---|---|---|---|---|---|"]
    for k, r in res["desc"].items():
        b = r["boot"] or {}
        ys = "、".join(f"{y} {pct(v['diff'], 1)}" for y, v in r["years"].items())
        L.append(f"| {k} | {r['n']:,} | {pct(r['real'])} | {'—' if r['win'] is None else f'{r[chr(119) + chr(105) + chr(110)] * 100:.0f}%'} | {pct(r['ctrl'])} | {pct(b.get('est'))} | {ys} |")
    open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
