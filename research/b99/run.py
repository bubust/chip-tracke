"""B99：她的進單規矩回測——「空間到達」之後，等止穩訊號會不會比直接接好？
規則（事先寫死、跑完不改）見 research/b99/PLAN.md。資料在 research/b94/data（15 分、60 分）、research/b97/data（5 分成交金額），不連網。
python research/b99/run.py → results/b99.json、REPORT.md"""
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
B97 = os.path.join(ROOT, "research", "b97", "data")
OUT = os.path.join(HERE, "results")
COST = 0.0002            # 來回 0.02%
WATCH = 36               # 碰到之後 36 根 15 分 K（2 天）內等訊號
HOLD = 180               # 最多抱 180 根
R_LIFE, X_LIFE = 90, 180
N_PLACEBO = 5
N_BOOT = 2000
SPLIT = "2025-05-01"
VARS = {"V0": "接刀（碰到就掛單）", "V1": "第一根壓下來不破前低", "V2": "站回 5 均", "V3": "帶量實體紅 K",
        "V4": "跨級數雙重底背離（15 分＋60 分）", "V5": "長下影線（她說不算）"}
EXITS = {"E1": "一次出（T1）", "E2": "走一口留一口（T1 出一半、剩下守成本）"}


# ── 資料 ─────────────────────────────────────────────────────────────────
def _read(path):
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]
    rows = [r for r in rows if r["o"] and float(r["h"]) >= float(r["l"]) > 0]
    return [r["date"] for r in rows], *(np.array([float(r[k]) for r in rows]) for k in ("o", "h", "l", "c"))


def load():
    st, o, h, l, c = _read(os.path.join(B94, "twii_15m.csv"))
    st6, o6, h6, l6, c6 = _read(os.path.join(B94, "twii_60m_twse.csv"))
    vol = defaultdict(float)
    vp = os.path.join(B97, "twii_5m_amt.csv")
    if os.path.exists(vp):
        with open(vp, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                hh, mm = (int(x) for x in r["slot"].split(":"))
                m = hh * 60 + mm
                b = 9 * 60 + ((m - 9 * 60) // 15) * 15
                vol[f"{r['date']} {b // 60:02d}:{b % 60:02d}"] += float(r["amt"])
    v = np.array([vol.get(s, np.nan) or np.nan for s in st])
    k60 = {s[:13]: i for i, s in enumerate(st6)}                     # "YYYY-MM-DD HH" → 60 分 index
    i60 = np.array([k60.get(s[:13], -1) for s in st])
    last15 = {}
    for j, M in enumerate(i60):
        if M >= 0:
            last15[int(M)] = j
    return {"st": st, "o": o, "h": h, "l": l, "c": c, "v": v, "i60": i60, "last15": last15,
            "o6": o6, "h6": h6, "l6": l6, "c6": c6, "st6": st6}


def ema(x, n):
    a = 2 / (n + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def slot_avg(st, v, days=20, need=10):
    """每根 15 分 K：過去 20 個交易日同一個時段的平均量（不含今天）"""
    by = defaultdict(list)                                            # 時段 → [(日期, 量)]
    out = np.full(len(st), np.nan)
    for j, s in enumerate(st):
        d, sl = s[:10], s[11:16]
        hist = [x for dd, x in by[sl][-days:] if dd < d and np.isfinite(x)]
        if len(hist) >= need:
            out[j] = float(np.mean(hist))
        by[sl].append((d, v[j]))
    return out


def prep(D):
    o, h, l, c = D["o"], D["h"], D["l"], D["c"]
    D["atr15"] = E.atr(h, l, c, 14)
    D["atr60"] = E.atr(D["h6"], D["l6"], D["c6"], 14)
    D["dif15"] = ema(c, 12) - ema(c, 26)
    D["dif60"] = ema(D["c6"], 12) - ema(D["c6"], 26)
    D["ma5"] = np.r_[np.full(4, np.nan), np.convolve(c, np.ones(5) / 5, mode="valid")]
    D["vavg"] = slot_avg(D["st"], D["v"])
    D["piv"] = E.zigzag(D["h6"], D["l6"], I.theta(D["h6"], D["l6"], D["c6"]))
    return D


def yspace(D, side):
    """多空對稱：side＝-1 時價格取負號（高低對調），往有利方向一律是變大"""
    if side > 0:
        return {k: D[k] for k in ("o", "h", "l", "c")} | {"dif15": D["dif15"], "ma5": D["ma5"], "l6": D["l6"], "dif60": D["dif60"]}
    return {"o": -D["o"], "h": -D["l"], "l": -D["h"], "c": -D["c"], "dif15": -D["dif15"], "ma5": -D["ma5"],
            "l6": -D["h6"], "dif60": -D["dif60"]}


# ── 事件：60 分確認轉折畫的區，15 分第一次碰到 ────────────────────────────
def events(D):
    piv, last15, n = D["piv"], D["last15"], len(D["c"])
    out = []
    for k in range(1, len(piv)):
        ci = piv[k]["ci"]
        if ci not in last15:
            continue
        s = last15[ci] + 1
        side = 1 if piv[k]["t"] == "H" else -1
        Y = yspace(D, side)
        nxt = last15.get(piv[k + 1]["ci"], n - 1) if k + 1 < len(piv) else n - 1
        cands = []
        ya, yb = side * piv[k - 1]["p"], side * piv[k]["p"]
        leg = yb - ya
        if leg > 0:
            cands.append({"fam": "R", "near": yb - 0.5 * leg, "far": yb - 0.618 * leg, "cap": yb, "life": R_LIFE,
                          "T1": yb, "T2": yb + 0.618 * leg, "ref": [piv[k - 1]["p"], piv[k]["p"]]})
        if k >= 2:
            y0, y1, y2 = side * piv[k - 2]["p"], side * piv[k - 1]["p"], side * piv[k]["p"]
            lg = y0 - y1
            if lg > 0 and y2 < y0:
                near, far = y2 - 1.618 * lg, y2 - 2 * lg
                if near < y1:
                    cands.append({"fam": "X", "near": near, "far": far, "cap": y2, "life": X_LIFE, "top": y2,
                                  "ref": [piv[k - 2]["p"], piv[k - 1]["p"], piv[k]["p"]]})
        for z in cands:
            if s >= n or Y["c"][s - 1] <= z["near"]:
                continue                                              # 生效時已經在區裡／區外＝不是新碰到
            end = min(s + z["life"], nxt, n - 1)
            t0 = None
            for j in range(s, end + 1):
                if Y["l"][j] <= z["near"]:
                    t0 = j
                    break
                if Y["h"][j] > z["cap"]:
                    break                                             # 碰到之前就越過起點＝取消
            if t0 is None:
                continue
            out.append(z | {"side": side, "t0": t0, "M": ci, "date": D["st"][t0]})
    return out


# ── 進場訊號 ─────────────────────────────────────────────────────────────
def signals(D, Y, z):
    """回 {V: (進場 K 的 index, 進場價, 停損, 是否收盤進場, 進場時的 L)}，沒出現就不放"""
    o, h, l, c = Y["o"], Y["h"], Y["l"], Y["c"]
    t0, n = z["t0"], len(c)
    last = min(t0 + WATCH - 1, n - 2)
    a15 = D["atr15"]
    out = {}
    fill = min(o[t0], z["near"])
    a60 = D["atr60"][z["M"]]
    if np.isfinite(a60):
        out["V0"] = (t0, fill, z["far"] - 0.25 * a60, False, fill)
    # V1、V4：L 之後彈起來（收盤站上 L 那根的最高）→ V1 等第一根黑 K 不破 L；V4 在彈起來那根檢查雙重底背離
    Lm, m, stt = np.inf, None, 0
    for j in range(t0, last + 1):
        if l[j] < Lm:
            Lm, m, stt = l[j], j, 1
            continue
        if stt == 1 and c[j] > h[m]:
            stt = 2
            if "V4" not in out and div_ok(D, Y, m, j, Lm):
                out["V4"] = (j, c[j], Lm - 0.1 * a15[j], True, Lm)
            continue
        if stt == 2 and "V1" not in out and c[j] < o[j] and l[j] > Lm and c[j] > Lm:
            out["V1"] = (j, c[j], Lm - 0.1 * a15[j], True, Lm)
    # V2：L 之後第一根由下往上站上 5 均的紅 K
    Lm, m = np.inf, None
    for j in range(t0, last + 1):
        if l[j] < Lm:
            Lm, m = l[j], j
        if j > m and j > 0 and c[j] > Y["ma5"][j] and c[j - 1] <= Y["ma5"][j - 1] and c[j] > o[j]:
            out["V2"] = (j, c[j], Lm - 0.1 * a15[j], True, Lm)
            break
    # V3：帶量實體紅 K；V5：長下影線
    Lm = np.inf
    for j in range(t0, last + 1):
        Lm = min(Lm, l[j])
        rng = h[j] - l[j]
        if rng <= 0 or not np.isfinite(a15[j]):
            continue
        body = abs(c[j] - o[j])
        if ("V3" not in out and c[j] > o[j] and body >= 0.6 * rng and rng >= 0.6 * a15[j]
                and np.isfinite(D["v"][j]) and np.isfinite(D["vavg"][j]) and D["v"][j] >= 1.5 * D["vavg"][j]):
            out["V3"] = (j, c[j], Lm - 0.1 * a15[j], True, Lm)
        ls = min(o[j], c[j]) - l[j]
        if "V5" not in out and ls >= 2 * body and ls >= 0.5 * rng and (c[j] - l[j]) / rng >= 0.67 and rng >= 0.5 * a15[j]:
            out["V5"] = (j, c[j], Lm - 0.1 * a15[j], True, Lm)
    return out


def div_ok(D, Y, m, b, Lm):
    """跨級數雙重底背離：15 分（L 比前 8～72 根的最低還低、DIF 比較高）＋60 分（只用收完的 60 分 K）"""
    lo, hi = max(0, m - 72), m - 8
    if hi <= lo:
        return False
    q = lo + int(np.argmin(Y["l"][lo:hi + 1]))
    if not (Lm < Y["l"][q] and Y["dif15"][m] > Y["dif15"][q]):
        return False
    M = int(D["i60"][b])
    if M < 0:
        return False
    Mc = M if D["last15"].get(M) == b else M - 1                      # 彈起來那根收盤時已經收完的 60 分 K
    if Mc < 46:
        return False
    l6, d6 = Y["l6"], Y["dif60"]
    r = Mc - 3 + int(np.argmin(l6[Mc - 3:Mc + 1]))
    q6 = Mc - 40 + int(np.argmin(l6[Mc - 40:Mc - 5]))
    return bool(l6[r] < l6[q6] and d6[r] > d6[q6])


# ── 出場 ─────────────────────────────────────────────────────────────────
def targets(z, Lx):
    if z["fam"] == "R":
        return z["T1"], z["T2"]
    S = z["top"] - Lx
    return Lx + 0.5 * S, Lx + 0.618 * S


def sim(Y, j, e, stop, at_close, T1, T2, mode):
    """回 (報酬 %（扣成本）, 點數, 結果)；mode＝E1／E2"""
    o, h, l, c = Y["o"], Y["h"], Y["l"], Y["c"]
    n = len(c)
    px = abs(e)
    if e <= stop:
        return -COST, 0.0, "stop"
    k0 = j + 1                                                        # 掛單成交那根：只看停損、目標不算
    if not at_close and l[j] <= stop:                                 # 掛單成交那根就碰到停損＝算停損
        return (stop - e) / px - COST, stop - e, "stop"
    halves = [None, None]                                             # 每一半的出場價
    tag = "time"
    hit1 = None
    for k in range(k0, min(j + HOLD, n - 1) + 1):
        if halves[0] is None:
            if o[k] <= stop:
                halves = [o[k], o[k]]
                tag = "stop"
                break
            if l[k] <= stop:
                halves = [stop, stop]
                tag = "stop"
                break
            if h[k] >= T1:
                x = max(T1, o[k])
                if mode == "E1":
                    halves = [x, x]
                    tag = "T1"
                    break
                halves[0], hit1 = x, k
                continue
        else:                                                         # E2 剩下一半：停損拉到成本
            if o[k] <= e:
                halves[1], tag = o[k], "BE"
                break
            if l[k] <= e:
                halves[1], tag = e, "BE"
                break
            if h[k] >= T2:
                halves[1], tag = max(T2, o[k]), "T2"
                break
    kend = min(j + HOLD, n - 1)
    halves = [c[kend] if x is None else x for x in halves]
    if tag == "time" and hit1 is not None:
        tag = "T1+time"
    pts = (halves[0] + halves[1]) / 2 - e
    return pts / px - COST, pts, tag


def trade(D, Y, z, sig, mode):
    j, e, stop, at_close, Lx = sig
    T1, T2 = targets(z, Lx)
    if e >= T1:
        return None                                                   # 進場價已經過了 T1＝沒有肉
    r, pts, tag = sim(Y, j, e, stop, at_close, T1, T2, mode)
    return {"r": r, "pts": pts, "tag": tag, "j": j, "e": e, "stop": stop, "T1": T1, "T2": T2}


def placebo(D, Y, z, rng):
    """同一區、t0+1～t0+35 隨便挑時間收盤進場（同樣停損算法、目標、E2），要湊到 5 筆有做的"""
    t0, n = z["t0"], len(Y["c"])
    hi = min(t0 + WATCH - 1, n - 2)
    if hi <= t0:
        return None
    got = []
    for _ in range(60):
        r = int(rng.integers(t0 + 1, hi + 1))
        Lm = float(np.min(Y["l"][t0:r + 1]))
        a = D["atr15"][r]
        if not np.isfinite(a):
            continue
        t = trade(D, Y, z, (r, Y["c"][r], Lm - 0.1 * a, True, Lm), "E2")
        if t:
            got.append(t["r"])
        if len(got) >= N_PLACEBO:
            break
    return float(np.mean(got)) if len(got) >= N_PLACEBO else None


# ── 統計 ─────────────────────────────────────────────────────────────────
def boot(months, vals, rng):
    months, vals = np.asarray(months), np.asarray(vals, float)
    um = np.unique(months)
    g = {m: np.where(months == m)[0] for m in um}
    out = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pk = rng.choice(um, size=len(um), replace=True)
        idx = np.concatenate([g[m] for m in pk])
        out[b] = vals[idx].mean()
    return out


def bh(p):
    ks = sorted(p, key=lambda k: p[k])
    m, q, prev = len(ks), {}, 1.0
    for rank in range(m, 0, -1):
        k = ks[rank - 1]
        prev = min(prev, p[k] * m / rank)
        q[k] = prev
    return q


def test(rows, key_fn, rng):
    """rows：每個事件一列；key_fn(row) → 差（None＝不列入）"""
    xs = [(r["date"], key_fn(r)) for r in rows]
    xs = [(d, v) for d, v in xs if v is not None]
    if len(xs) < 10:
        return {"n": len(xs), "mean": None, "p": None}
    months = [d[:7] for d, _ in xs]
    vals = np.array([v for _, v in xs])
    bs = boot(months, vals, rng)
    h1 = [v for d, v in xs if d < SPLIT]
    h2 = [v for d, v in xs if d >= SPLIT]
    return {"n": len(xs), "mean": float(vals.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
            "p": float((bs <= 0).mean()), "half1": float(np.mean(h1)) if h1 else None, "half2": float(np.mean(h2)) if h2 else None,
            "n1": len(h1), "n2": len(h2)}


def mdd(pts):
    cum = np.cumsum(pts)
    return float(np.max(np.maximum.accumulate(np.r_[0, cum])[1:] - cum)) if len(pts) else 0.0


def main():
    rng = np.random.default_rng(20261106)
    D = prep(load())
    ev = events(D)
    rows = []
    for z in ev:
        Y = yspace(D, z["side"])
        sg = signals(D, Y, z)
        row = {"date": z["date"], "fam": z["fam"], "side": z["side"], "t0": z["t0"], "near": z["side"] * z["near"],
               "far": z["side"] * z["far"], "ref": z["ref"], "tr": {}}
        for v in VARS:
            for mde in EXITS:
                t = trade(D, Y, z, sg[v], mde) if v in sg else None
                row["tr"][f"{v}{mde}"] = t
        row["plc"] = placebo(D, Y, z, rng) if row["tr"]["V1E2"] else None
        rows.append(row)

    zr = lambda r, k: (r["tr"][k] or {}).get("r", 0.0)              # noqa: E731  每區報酬（沒做＝0）
    H = {
        "H1": ("V1-E2 每區 − V0-E2 每區（第一根壓下來不破前低 vs 接刀）", lambda r: zr(r, "V1E2") - zr(r, "V0E2")),
        "H2": ("V4-E2 每區 − V0-E2 每區（雙重底背離 vs 接刀）", lambda r: zr(r, "V4E2") - zr(r, "V0E2")),
        "H3": ("V1 有做的區：E2 − E1（走一口留一口 vs 一次出）",
               lambda r: (r["tr"]["V1E2"]["r"] - r["tr"]["V1E1"]["r"]) if r["tr"]["V1E2"] else None),
        "H4": ("V1-E2 每區 − V5-E2 每區（第一根壓下來 vs 長下影線）", lambda r: zr(r, "V1E2") - zr(r, "V5E2")),
        "H5": ("V1-E2 每筆 − 同一區隨便挑時間進場", lambda r: (r["tr"]["V1E2"]["r"] - r["plc"]) if r["tr"]["V1E2"] and r["plc"] is not None else None),
    }
    res = {k: {"name": nm} | test(rows, fn, rng) for k, (nm, fn) in H.items()}
    q = bh({k: v["p"] for k, v in res.items() if v.get("p") is not None})
    for k, v in res.items():
        v["q"] = q.get(k)
        if v.get("p") is None:
            v["verdict"] = "△"
        elif v["q"] < 0.05 and v["lo"] > 0 and (v["half1"] or 0) > 0 and (v["half2"] or 0) > 0:
            v["verdict"] = "✅"
        elif v["hi"] < 0:
            v["verdict"] = "✗"
        else:
            v["verdict"] = "△"
    # 跑完才補（看到 V2 站回 5 均的每區平均最好才加）：五種訊號各自 vs 接刀一起做 BH，再加 V2 vs 隨便挑時間
    rng2 = np.random.default_rng(20261107)
    for r, z in zip(rows, ev):
        r["plc2"] = placebo(D, yspace(D, z["side"]), z, rng2)
    PH = {f"P{v}": (f"{v}-E2 每區 − V0-E2 每區（{VARS[v]} vs 接刀）", (lambda v: lambda r: zr(r, f"{v}E2") - zr(r, "V0E2"))(v))
          for v in ("V1", "V2", "V3", "V4", "V5")}
    PH["PV2plc"] = ("V2-E2 每筆 − 同一區隨便挑時間進場", lambda r: (r["tr"]["V2E2"]["r"] - r["plc2"]) if r["tr"]["V2E2"] and r["plc2"] is not None else None)
    post = {k: {"name": nm} | test(rows, fn, rng2) for k, (nm, fn) in PH.items()}
    q2 = bh({k: v["p"] for k, v in post.items() if v.get("p") is not None})
    for k, v in post.items():
        v["q"] = q2.get(k)
        v["verdict"] = ("△" if v.get("p") is None else "✅" if (v["q"] < 0.05 and v["lo"] > 0 and (v["half1"] or 0) > 0 and (v["half2"] or 0) > 0)
                        else "✗" if v["hi"] < 0 else "△")
    # 次要：每個做法的描述
    desc = []
    for v in VARS:
        for mde in EXITS:
            k = f"{v}{mde}"
            for side in (0, 1, -1):
                for fam in ("all", "R", "X"):
                    rr = [r for r in rows if (side == 0 or r["side"] == side) and (fam == "all" or r["fam"] == fam)]
                    tt = sorted([r["tr"][k] | {"date": r["date"]} for r in rr if r["tr"][k]], key=lambda t: t["j"])
                    if not rr:
                        continue
                    rs = np.array([t["r"] for t in tt]) if tt else np.array([])
                    desc.append({"k": k, "side": side, "fam": fam, "events": len(rr), "n": len(tt),
                                 "win": float((rs > 0).mean()) if len(tt) else None,
                                 "mean": float(rs.mean()) if len(tt) else None,
                                 "zone_mean": float(np.mean([zr(r, k) for r in rr])),
                                 "pts": float(sum(t["pts"] for t in tt)), "mdd": mdd([t["pts"] for t in tt]),
                                 "tags": {g: sum(1 for t in tt if t["tag"] == g) for g in ("stop", "T1", "T2", "BE", "T1+time", "time")}})
    # 分批 V6＝一半 V0、一半 V1
    v6 = [0.5 * zr(r, "V0E2") + 0.5 * zr(r, "V1E2") for r in rows]
    years = sorted({r["date"][:4] for r in rows})
    by_year = {y: {k: float(np.mean([zr(r, k) for r in rows if r["date"][:4] == y])) for k in ("V0E2", "V1E2", "V4E2", "V5E2")}
               | {"n": sum(1 for r in rows if r["date"][:4] == y)} for y in years}
    plc = [r["plc"] for r in rows if r["plc"] is not None]
    out = {"n_events": len(rows), "n_long": sum(1 for r in rows if r["side"] > 0), "n_R": sum(1 for r in rows if r["fam"] == "R"),
           "span": [D["st"][0], D["st"][-1]], "n15": len(D["c"]), "n60": len(D["c6"]), "n_piv": len(D["piv"]),
           "vol_cov": float(np.isfinite(D["v"]).mean()),
           "tests": res, "post": post, "desc": desc, "v6_zone_mean": float(np.mean(v6)), "by_year": by_year,
           "placebo_mean": float(np.mean(plc)) if plc else None,
           "signal_rate": {v: float(np.mean([r["tr"][f"{v}E2"] is not None for r in rows])) for v in VARS},
           "buyhold_pts": float(D["c"][-1] - D["c"][0]),
           "events": [{k: r[k] for k in ("date", "fam", "side", "near", "far", "ref")}
                      | {"tr": {k: (None if t is None else {kk: (round(t[kk], 5) if isinstance(t[kk], float) else t[kk]) for kk in ("r", "pts", "tag")})
                                for k, t in r["tr"].items()}} for r in rows]}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "b99.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)
    report(out)
    return out


def pc(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def report(R):
    L = [f"# B99：她的進單規矩回測（空間到達之後，等止穩訊號 vs 直接接）\n",
         f"資料：加權 15 分 K {R['span'][0]}～{R['span'][1]}（{R['n15']} 根）、60 分 K {R['n60']} 根、60 分確認轉折 {R['n_piv']} 個；"
         f"15 分量資料涵蓋 {R['vol_cov'] * 100:.0f}% 的 K 棒。規則見 PLAN.md（跑之前就 commit）。\n",
         f"碰到的區：{R['n_events']} 個（做多 {R['n_long']}、做空 {R['n_events'] - R['n_long']}；R 回檔區 {R['n_R']}、X 煞車區 {R['n_events'] - R['n_R']}）。"
         "「每區報酬」＝有做就是那筆報酬、等不到訊號＝0；報酬是 % 、已扣來回 0.02%。同期間買進加權抱著："
         f"{R['buyhold_pts']:+,.0f} 點。\n",
         "## 主要假設（一起做 BH）\n", "| | 比什麼 | 區數 | 平均差 | 95% 區間 | 前半／後半 | q | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for k, v in R["tests"].items():
        if v.get("mean") is None:
            L.append(f"| {k} | {v['name']} | {v['n']} | — | — | — | — | △ |")
            continue
        L.append(f"| {k} | {v['name']} | {v['n']} | {pc(v['mean'], 3)} | {pc(v['lo'], 3)}～{pc(v['hi'], 3)} | "
                 f"{pc(v['half1'], 3)}（{v['n1']}）／{pc(v['half2'], 3)}（{v['n2']}） | {v['q']:.3f} | {v['verdict']} |")
    L += ["", "## 跑完才補（看到「站回 5 均」每區平均最好才加；五種訊號 vs 接刀一起做 BH，另加 V2 vs 隨便挑時間）\n",
          "| | 比什麼 | 區數 | 平均差 | 95% 區間 | 前半／後半 | q | 判定 |", "|---|---|---|---|---|---|---|---|"]
    for k, v in R["post"].items():
        if v.get("mean") is None:
            L.append(f"| {k} | {v['name']} | {v['n']} | — | — | — | — | △ |")
            continue
        L.append(f"| {k} | {v['name']} | {v['n']} | {pc(v['mean'], 3)} | {pc(v['lo'], 3)}～{pc(v['hi'], 3)} | "
                 f"{pc(v['half1'], 3)}（{v['n1']}）／{pc(v['half2'], 3)}（{v['n2']}） | {v['q']:.3f} | {v['verdict']} |")
    L += ["", "## 每種進場（多空、兩種區合計）\n",
          "| 做法 | 出場 | 出現比例 | 筆數 | 勝率 | 每筆平均 | 每區平均 | 點數加總 | 最大回落 | 停損／T1／T2／成本／時間 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for d in R["desc"]:
        if d["side"] != 0 or d["fam"] != "all":
            continue
        v, mde = d["k"][:2], d["k"][2:]
        tg = d["tags"]
        win = "—" if d["win"] is None else f"{d['win'] * 100:.0f}%"
        L.append(f"| {v} {VARS[v]} | {EXITS[mde]} | {R['signal_rate'][v] * 100:.0f}% | {d['n']} | "
                 f"{win} | {pc(d['mean'])} | {pc(d['zone_mean'], 3)} | "
                 f"{d['pts']:+,.0f} | {d['mdd']:,.0f} | {tg['stop']}／{tg['T1']}／{tg['T2']}／{tg['BE']}／{tg['time'] + tg['T1+time']} |")
    L += ["", f"分批（一半接刀、一半等第一根壓下來）每區平均：{pc(R['v6_zone_mean'], 3)}；隨便挑時間進場（H5 的對照）每筆平均：{pc(R['placebo_mean'])}。", "",
          "## 分多空、分區種（E2 走一口留一口；每區平均／筆數）\n", "| 做法 | 做多 R | 做多 X | 做空 R | 做空 X |", "|---|---|---|---|---|"]
    for v in VARS:
        cells = []
        for side in (1, -1):
            for fam in ("R", "X"):
                d = next((x for x in R["desc"] if x["k"] == f"{v}E2" and x["side"] == side and x["fam"] == fam), None)
                cells.append("—" if not d else f"{pc(d['zone_mean'], 3)}（{d['n']}/{d['events']}）")
        L.append(f"| {v} {VARS[v]} | " + " | ".join(cells) + " |")
    L += ["", "## 各年（每區平均，E2）\n", "| 年 | 區數 | V0 接刀 | V1 第一根壓下來 | V4 雙重底背離 | V5 長下影線 |", "|---|---|---|---|---|---|"]
    for y, v in R["by_year"].items():
        L.append(f"| {y} | {v['n']} | {pc(v['V0E2'], 3)} | {pc(v['V1E2'], 3)} | {pc(v['V4E2'], 3)} | {pc(v['V5E2'], 3)} |")
    L += ["", "結論（白話）見根目錄 PLAN-B99.md。"]
    with open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
