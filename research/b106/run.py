"""B106：她的進場做法回測——事先畫好的價位被刺穿、又收回來才進場，停損放尖端外，三口分批出。
規則（事先寫死、跑完不改）見 research/b106/PLAN.md。資料在 research/b94/data（加權 15 分、60 分），不連網。
python research/b106/run.py → results/b106.json、REPORT.md"""
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from wave import engine as E, intraday as I  # noqa: E402

B94 = os.path.join(ROOT, "research", "b94", "data")
OUT = os.path.join(HERE, "results")
COST = 0.0002            # 來回 0.02%
WIN = 8                  # 刺穿後 8 根 15 分 K 內要收回
DMIN, DMAX = 0.15, 1.0   # 刺穿深度：≥ 0.15 ATR15、≤ 1 ATR60
BUF = 0.1                # 停損放尖端外 0.1 ATR15
HOLD = 36                # 最多抱 36 根 15 分 K
N_PIV = 6                # 最近 6 個確認轉折
FIBS = (0.382, 0.5, 0.618)
C1_LIFE, C1_TRY = 90, 300
N_PLACEBO = 5
N_BOOT = 2000
SPLIT = "2025-05-01"


# ── 資料 ─────────────────────────────────────────────────────────────────
def _read(path):
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]
    rows = [r for r in rows if r["o"] and float(r["h"]) >= float(r["l"]) > 0]
    return [r["date"] for r in rows], *(np.array([float(r[k]) for r in rows]) for k in ("o", "h", "l", "c"))


def build(st, o, h, l, c, st6, o6, h6, l6, c6, i60=None):
    """15 分＋60 分 → 回測要用的東西（價位只用確認過、而且那根 60 分 K 已經收完的轉折）
    i60[j]＝第 j 根 15 分 K 落在哪一根 60 分 K（沒給就用「同一個小時」對）"""
    D = {"st": st, "o": o, "h": h, "l": l, "c": c, "st6": st6, "h6": h6, "l6": l6, "c6": c6}
    if i60 is None:
        k60 = {s[:13]: i for i, s in enumerate(st6)}
        i60 = np.array([k60.get(s[:13], -1) for s in st])
    end15 = np.full(len(st6), -1)
    for j, M in enumerate(i60):
        if M >= 0:
            end15[M] = j
    for M in range(1, len(st6)):                                      # 15 分沒有對到的 60 分 K：用前一根的
        if end15[M] < 0:
            end15[M] = end15[M - 1]
    D["atr15"] = E.atr(h, l, c, 14)
    a60 = E.atr(h6, l6, c6, 14)
    D["atr60"] = np.array([a60[M - 1] if M >= 1 else np.nan for M in i60])   # 用上一根收完的 60 分 K
    piv = E.zigzag(h6, l6, I.theta(h6, l6, c6))
    D["piv"] = piv
    known = np.array([end15[p["ci"]] if p["ci"] < len(end15) else 10 ** 9 for p in piv])
    assert np.all(np.diff(known) >= 0), "確認順序要遞增"
    D["npiv"] = np.searchsorted(known, np.arange(len(st)), side="left")  # 第 j 根開盤前已確認的轉折數
    # 日線 20 日均線（D2 過濾）：用前一天收盤
    days, dclose = [], []
    for j, s in enumerate(st):
        if not days or days[-1] != s[:10]:
            days.append(s[:10])
            dclose.append(c[j])
        else:
            dclose[-1] = c[j]
    dclose = np.array(dclose)
    ma20 = np.r_[np.full(19, np.nan), np.convolve(dclose, np.ones(20) / 20, mode="valid")]
    didx = {d: i for i, d in enumerate(days)}
    D["d2"] = np.array([0 if didx[s[:10]] < 1 or not np.isfinite(ma20[didx[s[:10]] - 1])
                        else (1 if dclose[didx[s[:10]] - 1] > ma20[didx[s[:10]] - 1] else -1) for s in st])
    return D


def load():
    st, o, h, l, c = _read(os.path.join(B94, "twii_15m.csv"))
    st6, o6, h6, l6, c6 = _read(os.path.join(B94, "twii_60m_twse.csv"))
    return build(st, o, h, l, c, st6, o6, h6, l6, c6)


def levels(D, j):
    """第 j 根開盤前看得到的價位組：[(價位, 'P'/'F')]"""
    k = int(D["npiv"][j])
    if k < 2:
        return []
    pv = D["piv"][:k]
    out = [(p["p"], "P") for p in pv[-N_PIV:]]
    a, b = pv[-2]["p"], pv[-1]["p"]
    out += [(b + (a - b) * r, "F") for r in FIBS]
    return out


def ysp(D, side):
    if side > 0:
        return D["o"], D["h"], D["l"], D["c"]
    return -D["o"], -D["l"], -D["h"], -D["c"]


# ── 訊號：刺穿再收回 ─────────────────────────────────────────────────────
def find_reclaim(D, Y, side, j, S):
    """第 j 根刺穿 S（y 空間：往下刺）之後 8 根內收回 → (k, 尖端 X) 或 None"""
    o, h, l, c = Y
    n = len(c)
    X = np.inf
    a60 = D["atr60"][j]
    if not np.isfinite(a60):
        return None
    for k in range(j, min(j + WIN, n - 1)):
        X = min(X, l[k])
        if S - X > DMAX * a60:
            return None                                               # 真的跌破
        if c[k] > S:
            a15 = D["atr15"][k]
            if not np.isfinite(a15) or S - X < DMIN * a15:
                return None                                           # 沒有真的刺過去
            return k, X
    return None


def candidates(D):
    """所有「刺穿再收回」訊號（還沒套一次只抱一筆）：每根收回 K、每個方向一筆"""
    n = len(D["c"])
    best = {}
    for side in (1, -1):
        Y = ysp(D, side)
        o, h, l, c = Y
        for j in range(1, n - 1):
            for S0, typ in levels(D, j):
                S = side * S0
                if not (c[j - 1] > S and l[j] < S):
                    continue
                r = find_reclaim(D, Y, side, j, S)
                if r is None:
                    continue
                k, X = r
                key = (k, side)
                if key in best and c[k] - S >= c[k] - best[key]["S"]:
                    continue                                          # 同一根同方向：取離收盤最近的線
                best[key] = {"side": side, "j": j, "k": k, "S": S, "X": X, "typ": typ, "dist": c[j - 1] - S,
                             "depth": S - X, "a60": float(D["atr60"][j]), "a15": float(D["atr15"][k])}
    return sorted(best.values(), key=lambda z: (z["k"], -z["side"]))


# ── 出場 ─────────────────────────────────────────────────────────────────
def sim(Y, e_bar, e, stop, tg, lots=3, trail=True):
    """從 e_bar 開盤 e 進場（整根算進場後）。tg＝每口的目標；lots＝3：碰 T1 後停損拉到成本、碰 T2 後拉到 T1。
    回 (每口平均點數, 結果, 出場那根)"""
    o, h, l, c = Y
    n = len(c)
    exits = [None] * lots
    st = stop
    nxt = 0
    tag = "time"
    kend = min(e_bar + HOLD - 1, n - 1)
    for b in range(e_bar, kend + 1):
        if b > e_bar and o[b] <= st:                                  # 跳空越過停損
            for i in range(nxt, lots):
                exits[i] = o[b]
            tag = "stop" if nxt == 0 else ("BE" if nxt == 1 else "trail")
            kend = b
            break
        if l[b] <= st:                                                # 先算停損（保守）
            for i in range(nxt, lots):
                exits[i] = st
            tag = "stop" if nxt == 0 else ("BE" if nxt == 1 else "trail")
            kend = b
            break
        while nxt < lots and h[b] >= tg[nxt]:
            exits[nxt] = max(tg[nxt], o[b]) if b > e_bar else tg[nxt]
            nxt += 1
            if trail and lots > 1:
                st = e if nxt == 1 else tg[nxt - 2]
        if nxt == lots:
            tag = f"T{lots}" if lots > 1 else "T"
            kend = b
            break
        if nxt > 0 and l[b] <= st:                                    # 同一根碰到目標又碰到拉高的停損＝算停損
            for i in range(nxt, lots):
                exits[i] = st
            tag = "BE" if nxt == 1 else "trail"
            kend = b
            break
    else:
        tag = "time" if nxt == 0 else f"T{nxt}+time"
    exits = [c[kend] if x is None else x for x in exits]
    return float(np.mean(exits) - e), tag, kend


def lvl_targets(lv_y, e, R):
    up = sorted(x for x in lv_y if x >= e + R)
    out, prev = [], e
    for k in range(3):
        need = (e + R) if k == 0 else out[-1] + 0.5 * R
        t = next((x for x in up if x >= need), None)
        out.append(t if t is not None else max(e + (k + 1) * R, need))
        prev = out[-1]
    return out


def trade(D, z, mode="E3"):
    side, k = z["side"], z["k"]
    Y = ysp(D, side)
    o = Y[0]
    n = len(o)
    if k + 1 >= n:
        return None
    e = o[k + 1]
    stop = z["X"] - BUF * z["a15"]
    R = e - stop
    if R <= 0:
        return None
    if mode == "E1":
        pts, tag, kend = sim(Y, k + 1, e, stop, [e + 2 * R], lots=1, trail=False)
    elif mode == "EL":
        lv = [side * p for p, _ in levels(D, z["j"])]
        pts, tag, kend = sim(Y, k + 1, e, stop, lvl_targets(lv, e, R))
    else:
        pts, tag, kend = sim(Y, k + 1, e, stop, [e + R, e + 2 * R, e + 3 * R])
    return {"r": pts / abs(e) - COST, "pts": pts, "R": R, "tag": tag, "e_bar": k + 1, "x_bar": kend, "e": side * e}


def walk(D, cands, keep=lambda z: True, mode="E3"):
    """一次只抱一筆：出場那根收完才找下一筆"""
    out, free = [], 0
    for z in cands:
        if z["k"] < free or not keep(z):
            continue
        t = trade(D, z, mode)
        if t is None:
            continue
        out.append(z | t | {"date": D["st"][z["k"] + 1]})
        free = t["x_bar"] + 1
    return out


# ── 對照 ─────────────────────────────────────────────────────────────────
def year_bars(D):
    by = defaultdict(list)
    n = len(D["c"])
    for j, s in enumerate(D["st"]):
        if 30 <= j < n - HOLD - C1_LIFE - WIN - 2:
            by[s[:4]].append(j)
    return {y: np.array(v) for y, v in by.items()}


def plc_c1(D, t, yb, rng):
    """假價位：同一年隨機一根，同樣距離畫假線，照同一套刺穿再收回、同樣出場"""
    side = t["side"]
    Y = ysp(D, side)
    o, h, l, c = Y
    pool = yb[t["date"][:4]]
    got = []
    for _ in range(C1_TRY):
        r = int(rng.choice(pool))
        S = c[r] - t["dist"]
        hit = None
        for j in range(r + 1, r + C1_LIFE):
            if c[j - 1] > S and l[j] < S:
                rr = find_reclaim(D, Y, side, j, S)
                if rr is not None:
                    hit = (j, rr)
                    break
        if hit is None:
            continue
        j, (k, X) = hit
        a15 = D["atr15"][k]
        z = {"side": side, "j": j, "k": k, "S": S, "X": X, "a15": float(a15)}
        tt = trade(D, z)
        if tt is not None:
            got.append(tt["r"])
        if len(got) >= N_PLACEBO:
            break
    return float(np.mean(got)) if len(got) >= N_PLACEBO else None


def plc_c2(D, t, yb, rng):
    """隨便挑時間：同一年隨機一根，下一根開盤同方向進場，同樣停損點數、同樣三口出場"""
    side = t["side"]
    Y = ysp(D, side)
    pool = yb[t["date"][:4]]
    got = []
    for _ in range(N_PLACEBO):
        r = int(rng.choice(pool))
        e = Y[0][r + 1]
        R = t["R"]
        pts, _, _ = sim(Y, r + 1, e, e - R, [e + R, e + 2 * R, e + 3 * R])
        got.append(pts / abs(e) - COST)
    return float(np.mean(got))


# ── 統計 ─────────────────────────────────────────────────────────────────
def boot(months, vals, rng):
    months, vals = np.asarray(months), np.asarray(vals, float)
    um = np.unique(months)
    g = {m: np.where(months == m)[0] for m in um}
    out = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pk = rng.choice(um, size=len(um), replace=True)
        out[b] = vals[np.concatenate([g[m] for m in pk])].mean()
    return out


def bh(p):
    ks = sorted(p, key=lambda k: p[k])
    m, q, prev = len(ks), {}, 1.0
    for rank in range(m, 0, -1):
        k = ks[rank - 1]
        prev = min(prev, p[k] * m / rank)
        q[k] = prev
    return q


def test(xs, rng):
    xs = [(d, v) for d, v in xs if v is not None]
    if len(xs) < 10:
        return {"n": len(xs), "mean": None, "p": None}
    vals = np.array([v for _, v in xs])
    bs = boot([d[:7] for d, _ in xs], vals, rng)
    h1 = [v for d, v in xs if d < SPLIT]
    h2 = [v for d, v in xs if d >= SPLIT]
    return {"n": len(xs), "mean": float(vals.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
            "p": float((bs <= 0).mean()), "half1": float(np.mean(h1)) if h1 else None, "half2": float(np.mean(h2)) if h2 else None,
            "n1": len(h1), "n2": len(h2)}


def summ(tr):
    if not tr:
        return {"n": 0}
    r = np.array([t["r"] for t in tr])
    pts = np.array([t["pts"] for t in tr])
    cum = np.cumsum(pts)
    mdd = float(np.max(np.maximum.accumulate(np.r_[0, cum])[1:] - cum))
    run, mx = 0, 0
    for p in pts:
        run = run + 1 if p <= 0 else 0
        mx = max(mx, run)
    tags = defaultdict(int)
    for t in tr:
        tags[t["tag"]] += 1
    return {"n": len(tr), "win": float((r > 0).mean()), "mean": float(r.mean()), "pts_mean": float(pts.mean()), "pts": float(pts.sum()),
            "mdd": mdd, "streak": mx, "R_med": float(np.median([t["R"] for t in tr])), "tags": dict(tags),
            "per_year": {y: {"n": int(sum(1 for t in tr if t["date"][:4] == y)), "pts": float(sum(t["pts"] for t in tr if t["date"][:4] == y)),
                             "mean": float(np.mean([t["r"] for t in tr if t["date"][:4] == y]))}
                         for y in sorted({t["date"][:4] for t in tr})}}


def verdict(v):
    if v.get("p") is None:
        return "△"
    if v["q"] < 0.05 and v["lo"] > 0 and (v["half1"] or 0) > 0 and (v["half2"] or 0) > 0:
        return "✅"
    return "✗" if v["hi"] < 0 else "△"


def her_check():
    """參考：同一套規則套在網站快照存的台指期 15 分 K（含夜盤），看有沒有抓到她那幾筆"""
    p = os.path.join(HERE, "data", "tx_snap_bars.json")
    if not os.path.exists(p):
        return None
    import datetime as dt
    tw = dt.timezone(dt.timedelta(hours=8))
    J = json.load(open(p, encoding="utf-8"))
    f = lambda b: dt.datetime.fromtimestamp(b["time"], tw).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    b15, b60 = J["i15"], J["i60"]
    arr = lambda bs: [np.array([x[k] for x in bs], float) for k in ("open", "high", "low", "close")]  # noqa: E731
    o, h, l, c = arr(b15)
    o6, h6, l6, c6 = arr(b60)
    st, st6 = [f(b) for b in b15], [f(b) for b in b60]
    t6 = [b["time"] for b in b60]                                     # 60 分 K 的開始時間
    i60 = np.searchsorted(t6, [b["time"] for b in b15], side="right") - 1
    D = build(st, o, h, l, c, st6, o6, h6, l6, c6, i60=i60)
    cands = candidates(D)
    tr = walk(D, cands)
    out = []
    for t in tr:
        if t["date"] < "2026-11-02":
            continue
        out.append({"date": t["date"], "side": t["side"], "line": round(t["side"] * t["S"]), "typ": t["typ"],
                    "tip": round(t["side"] * t["X"]), "e": round(t["e"]), "R": round(t["R"]), "pts": round(t["pts"]), "tag": t["tag"]})
    return out


def main():
    rng = np.random.default_rng(20261112)
    D = load()
    cands = candidates(D)
    tr = walk(D, cands)
    yb = year_bars(D)
    for t in tr:
        t["c1"] = plc_c1(D, t, yb, rng)
        t["c2"] = plc_c2(D, t, yb, rng)
        t1 = trade(D, t, "E1")
        t["e1"] = t1["r"] if t1 else None
    H = {
        "H1": ("真交易 − 假價位（同樣距離、同一套規則）", [(t["date"], None if t["c1"] is None else t["r"] - t["c1"]) for t in tr]),
        "H2": ("真交易 − 隨便挑時間（同方向、同樣停損點數）", [(t["date"], t["r"] - t["c2"]) for t in tr]),
        "H3": ("真交易每筆（扣成本）", [(t["date"], t["r"]) for t in tr]),
        "H4": ("三口分批（E3）− 一次出 2R（E1）", [(t["date"], None if t["e1"] is None else t["r"] - t["e1"]) for t in tr]),
    }
    res = {k: {"name": nm} | test(xs, rng) for k, (nm, xs) in H.items()}
    q = bh({k: v["p"] for k, v in res.items() if v.get("p") is not None})
    for k, v in res.items():
        v["q"] = q.get(k)
        v["verdict"] = verdict(v)
    # 次要
    var = {
        "main": ("主要：多空都做、9 條線、三口分批", walk(D, cands)),
        "long": ("只做多", walk(D, cands, lambda z: z["side"] > 0)),
        "short": ("只做空", walk(D, cands, lambda z: z["side"] < 0)),
        "D1": ("D1 跟著 60 分最後確認轉折", walk(D, cands, lambda z: (1 if D["piv"][int(D["npiv"][z["j"]]) - 1]["t"] == "L" else -1) == z["side"])),
        "D2": ("D2 日線站上／跌破 20 日均線", walk(D, cands, lambda z: D["d2"][z["j"]] == z["side"])),
        "P": ("只用前高前低", walk(D, cands, lambda z: z["typ"] == "P")),
        "F": ("只用黃金切割", walk(D, cands, lambda z: z["typ"] == "F")),
        "shallow": ("刺穿淺（< 0.5 ATR60）", walk(D, cands, lambda z: z["depth"] < 0.5 * z["a60"])),
        "deep": ("刺穿深（≥ 0.5 ATR60）", walk(D, cands, lambda z: z["depth"] >= 0.5 * z["a60"])),
        "E1": ("一次出 2R（停損不動）", walk(D, cands, mode="E1")),
        "EL": ("目標用下一、二、三條線", walk(D, cands, mode="EL")),
    }
    desc = {k: {"name": nm} | summ(t) for k, (nm, t) in var.items()}
    # 跑完才補（看到 D2「順著日線 20 日均線方向」是次要做法裡最好的才加；非主要，只當線索）
    rng3 = np.random.default_rng(20261113)
    d2 = var["D2"][1]
    for t in d2:
        t["c1"] = plc_c1(D, t, yb, rng3)
        t["c2"] = plc_c2(D, t, yb, rng3)
    PH = {"P1": ("D2 真交易 − 假價位（非主要）", [(t["date"], None if t["c1"] is None else t["r"] - t["c1"]) for t in d2]),
          "P2": ("D2 真交易 − 隨便挑時間（非主要）", [(t["date"], t["r"] - t["c2"]) for t in d2]),
          "P3": ("D2 真交易每筆（非主要）", [(t["date"], t["r"]) for t in d2])}
    post = {k: {"name": nm} | test(xs, rng3) for k, (nm, xs) in PH.items()}
    q3 = bh({k: v["p"] for k, v in post.items() if v.get("p") is not None})
    for k, v in post.items():
        v["q"] = q3.get(k)
        v["verdict"] = verdict(v)
    c1 = [t["c1"] for t in tr if t["c1"] is not None]
    out = {"span": [D["st"][0], D["st"][-1]], "n15": len(D["c"]), "n60": len(D["c6"]), "n_piv": len(D["piv"]), "n_cands": len(cands),
           "tests": res, "post": post, "desc": desc, "c1_mean": float(np.mean(c1)) if c1 else None, "c1_n": len(c1),
           "c2_mean": float(np.mean([t["c2"] for t in tr])), "e1_mean": float(np.mean([t["e1"] for t in tr if t["e1"] is not None])),
           "buyhold_pts": float(D["c"][-1] - D["c"][0]),
           "med_atr15": float(np.nanmedian(D["atr15"][-4000:])), "med_atr60": float(np.nanmedian(D["atr60"][-4000:])),
           "her": her_check(),
           "trades": [{"date": t["date"], "side": t["side"], "typ": t["typ"], "line": round(t["side"] * t["S"], 1),
                       "tip": round(t["side"] * t["X"], 1), "e": round(t["e"], 1), "R": round(t["R"], 1), "pts": round(t["pts"], 1),
                       "r": round(t["r"], 6), "tag": t["tag"]} for t in tr]}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "b106.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)
    report(out)
    return out


def pc(x, d=3):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(R):
    L = [f"# B106：她的進場做法回測（刺穿再收回、尖端外停損、三口分批）\n",
         f"資料：加權 15 分 K {R['span'][0]}～{R['span'][1]}（{R['n15']} 根，只有日盤）、60 分 K {R['n60']} 根、60 分確認轉折 {R['n_piv']} 個。"
         f"ATR15 中位數約 {R['med_atr15']:.0f} 點、ATR60 約 {R['med_atr60']:.0f} 點。規則見 PLAN.md（跑之前就 commit）。\n",
         f"「刺穿再收回」訊號 {R['n_cands']} 個，一次只抱一筆之後實際做 {R['desc']['main']['n']} 筆。報酬是 %、已扣來回 0.02%；點數＝3 口平均每口。"
         f"同期間買進加權抱著：{R['buyhold_pts']:+,.0f} 點。\n",
         "## 主要假設（一起做 BH）\n", "| | 比什麼 | 筆數 | 平均差 | 95% 區間 | 前半／後半 | q | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for k, v in R["tests"].items():
        if v.get("mean") is None:
            L.append(f"| {k} | {v['name']} | {v['n']} | — | — | — | — | △ |")
            continue
        L.append(f"| {k} | {v['name']} | {v['n']} | {pc(v['mean'])} | {pc(v['lo'])}～{pc(v['hi'])} | "
                 f"{pc(v['half1'])}（{v['n1']}）／{pc(v['half2'])}（{v['n2']}） | {v['q']:.3f} | {v['verdict']} |")
    L += ["", "## 跑完才補（看到 D2 是次要做法裡最好的才加；非主要，就算顯著也只當線索）\n",
          "| | 比什麼 | 筆數 | 平均差 | 95% 區間 | 前半／後半 | q | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for k, v in R["post"].items():
        if v.get("mean") is None:
            L.append(f"| {k} | {v['name']} | {v['n']} | — | — | — | — | △ |")
            continue
        L.append(f"| {k} | {v['name']} | {v['n']} | {pc(v['mean'])} | {pc(v['lo'])}～{pc(v['hi'])} | "
                 f"{pc(v['half1'])}（{v['n1']}）／{pc(v['half2'])}（{v['n2']}） | {v['q']:.3f} | {v['verdict']} |")
    L += ["", f"對照平均：假價位 {pc(R['c1_mean'])}（{R['c1_n']} 筆有配到）、隨便挑時間 {pc(R['c2_mean'])}、同一批一次出 2R {pc(R['e1_mean'])}。", "",
          "## 各種做法（次要，只描述）\n",
          "| 做法 | 筆數 | 勝率 | 每筆 | 每筆點數 | 總點數 | 最大回落 | 最多連續沒賺 | R 中位數 | 結果 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, d in R["desc"].items():
        if not d.get("n"):
            L.append(f"| {d['name']} | 0 | | | | | | | | |")
            continue
        tg = "、".join(f"{a} {b}" for a, b in sorted(d["tags"].items(), key=lambda x: -x[1]))
        L.append(f"| {d['name']} | {d['n']} | {d['win'] * 100:.0f}% | {pc(d['mean'])} | {d['pts_mean']:+.1f} | {d['pts']:+,.0f} | "
                 f"{d['mdd']:,.0f} | {d['streak']} | {d['R_med']:.0f} | {tg} |")
    L += ["", "結果代號：stop＝3 口都停損、BE＝出 1 口後剩下守成本出場、trail＝出 2 口後最後 1 口守 T1 出場、T3＝三個目標都到、"
          "T1+time／T2+time＝到 2 天收盤出、T＝一次出到目標。", "", "## 各年（主要做法）\n", "| 年 | 筆數 | 每筆 | 總點數 |", "|---|---|---|---|"]
    for y, v in R["desc"]["main"]["per_year"].items():
        L.append(f"| {y} | {v['n']} | {pc(v['mean'])} | {v['pts']:+,.0f} |")
    if R.get("her"):
        L += ["", "## 參考：同一套規則套在網站存的台指期 15 分 K（11/2 以後，含夜盤）\n",
              "| 進場時間 | 方向 | 線 | 尖端 | 進場 | R | 每口點數 | 結果 |", "|---|---|---|---|---|---|---|---|"]
        for t in R["her"]:
            L.append(f"| {t['date']} | {'多' if t['side'] > 0 else '空'} | {t['line']:,}（{t['typ']}） | {t['tip']:,} | {t['e']:,} | {t['R']} | {t['pts']:+} | {t['tag']} |")
    L += ["", "結論（白話）見根目錄 PLAN-B106.md。"]
    with open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
