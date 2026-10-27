"""B81 R-C 試單回測（PLAN-B81 §5、§5b；門檻事先定好）
- 每根 K 棒 t 用「當時」的價位梯（research/b81/pit.py＝網站同一套函式），用 wave.levelmap.setups 算三種試單（L 回測支撐試多、S 反彈壓力試空、B 站上回測追多）
- 之後 W 根內觸發才算一筆；進場＝觸發那根收盤；停損＝價位外 0.25 ATR（L／B：min(最低, 價位)−；S：max(最高, 價位)＋）；目標＝t 時的 T1
- 結果：進場後 H 根內先碰目標（贏）／停損（輸）／都沒碰（到期）；同一根兩邊都碰 → 輸
- 對照①有漂移隨機漫步（μ、σ＝進場根含以前 250 根；公式）②隨機價位（同一批 t、從別筆事件抽距離組合，固定種子）
- 主要比較只用有結果的筆數；到期另列
資料：1d＝加權日 K 2000～（小級價位梯）、1wk＝中級價位梯（日 K 棒判斷）、intra＝加權 60 分 2023-10～（Yahoo＋MI_5MINS；沒有多層浪名的價位）
用法：python research/b81/run_setups.py [1d 1wk intra]"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C  # noqa: E402
import pit  # noqa: E402
from wave import engine as E, intraday as I, keylevel as KL, levelmap as LM, volume as VO  # noqa: E402
from wave import service as S  # noqa: E402

OUT = os.path.join(HERE, "results")
CFG = {"1d": {"W": 10, "H": 20}, "1wk": {"W": 20, "H": 60}, "intra": {"W": 15, "H": 30}}
MIN_N = 50
MIN_EDGE = 0.05
MIN_VS_RAND = 0.03
TW = timezone(timedelta(hours=8))


def ladder_dir(key, an_deg):
    d = (key or {}).get("dir")
    if d in (1, -1):
        return d
    tent = an_deg.get("tentative")
    return (1 if tent["t"] == "H" else -1) if tent else 0


def trigger(h, l, c, t, W, s, z, sd, t1, n):
    """→ (k, entry, stop) 或 None。s：setup dict（id, level, side）"""
    lv = s["level"]
    if s["id"] == "L":
        for k in range(t + 1, min(n, t + 1 + W)):
            if h[k] >= t1:
                return None                                   # 還沒碰到支撐就先到目標 → 這筆沒機會進場
            if l[k] <= lv + z and c[k] > lv:
                return k, c[k], min(l[k], lv) - sd
            if c[k] < lv - sd:
                return None
        return None
    if s["id"] == "S":
        for k in range(t + 1, min(n, t + 1 + W)):
            if l[k] <= t1:
                return None
            if h[k] >= lv - z and c[k] < lv:
                return k, c[k], max(h[k], lv) + sd
            if c[k] > lv + sd:
                return None
        return None
    # B：先收盤站上，再回測不破
    j = None
    for k in range(t + 1, min(n, t + 1 + W)):
        if c[k] > lv:
            j = k
            break
    if j is None:
        return None
    for k in range(j + 1, min(n, j + 1 + W)):
        if h[k] >= t1:
            return None                                       # 直接拉開沒回測 → 沒進場
        if l[k] <= lv + z and c[k] > lv:
            return k, c[k], min(l[k], lv) - sd
        if c[k] < lv - sd:
            return None
    return None


def outcome(h, l, c, k, H, side, entry, stop, t1, n):
    """→ (結果 'win'／'loss'／'to'／None, R, both)"""
    risk = abs(entry - stop)
    if risk <= 0:
        return None, None, False
    last = min(n - 1, k + H)
    if last <= k:
        return None, None, False
    for j in range(k + 1, last + 1):
        hit_t = h[j] >= t1 if side == 1 else l[j] <= t1
        hit_s = l[j] <= stop if side == 1 else h[j] >= stop
        if hit_t and hit_s:
            return "loss", -1.0, True
        if hit_s:
            return "loss", -1.0, False
        if hit_t:
            return "win", abs(t1 - entry) / risk, False
    if k + H > n - 1:
        return None, None, False                              # 資料結尾不夠 H 根 → 不算
    return "to", (c[last] - entry) * side / risk, False


def run(D, tfc, maps_fn, rng, log_every=500):
    """maps_fn(t) → (items, price, atr, dir) 或 None；回傳事件清單"""
    h, l, c = D["h"], D["l"], D["c"]
    n = len(c)
    W, H = CFG[tfc]["W"], CFG[tfc]["H"]
    ev = []
    busy = {}
    t0 = time.time()
    for t in range(250, n - 2):
        m = maps_fn(t)
        if m is None:
            continue
        items, price, atr, d = m
        st = LM.setups(items, price, atr, d)
        if not st.get("ok"):
            continue
        z, sd = LM.SETUP_ZONE * atr, LM.SETUP_STOP * atr
        for s in st["list"]:
            key = (s["id"], round(s["level"] / (price * 0.001)))
            if busy.get(key, -1) >= t:
                continue
            tr = trigger(h, l, c, t, W, s, z, sd, s["t1"], n)
            if tr is None:
                continue
            k, entry, stop = tr
            if (s["side"] == 1 and entry >= s["t1"]) or (s["side"] == -1 and entry <= s["t1"]):
                continue
            res, R, both = outcome(h, l, c, k, H, s["side"], entry, stop, s["t1"], n)
            if res is None:
                continue
            busy[key] = k + H
            dp = C.drift_params(c, k)
            if dp is None:
                continue
            mu, sd_ = dp
            mu_x = float(np.mean(np.diff(np.log(c[:k + 1]))))     # 敏感度：全部歷史平均漂移
            ev.append({"t": t, "k": k, "id": s["id"], "side": s["side"], "trend": s["trend"] or "無", "res": res, "R": R, "both": both,
                       "p": C.p_first(entry, s["t1"], stop, s["side"], mu, sd_),
                       "p_x": C.p_first(entry, s["t1"], stop, s["side"], mu_x, sd_),
                       "dS": abs(price - s["level"]) / atr, "dT": abs(s["t1"] - price) / atr, "price": price, "atr": atr,
                       "year": int(D["years"][k])})
        if log_every and t % log_every == 0:
            print(f"  {tfc} t={t}/{n} 事件 {len(ev)}（{time.time() - t0:.0f}s）", flush=True)
    return ev


def rand_control(D, ev, tfc, rng):
    """隨機價位：同一批 t，從同一種試單的其他事件抽（dS, dT）組合 → 假價位、假目標，觸發／停損／結果規則一樣"""
    h, l, c = D["h"], D["l"], D["c"]
    n = len(c)
    W, H = CFG[tfc]["W"], CFG[tfc]["H"]
    out = []
    by = {}
    for e in ev:
        by.setdefault(e["id"], []).append(e)
    for sid, xs in by.items():
        pool = [(x["dS"], x["dT"]) for x in xs]
        for e in xs:
            dS, dT = pool[rng.integers(len(pool))]
            price, atr, t = e["price"], e["atr"], e["t"]
            z, sd = LM.SETUP_ZONE * atr, LM.SETUP_STOP * atr
            if sid == "L":
                s = {"id": "L", "level": price - dS * atr, "side": 1}
                t1 = price + dT * atr
            elif sid == "S":
                s = {"id": "S", "level": price + dS * atr, "side": -1}
                t1 = price - dT * atr
            else:
                s = {"id": "B", "level": price + dS * atr, "side": 1}
                t1 = s["level"] + max(dT - dS, 0.3) * atr
            tr = trigger(h, l, c, t, W, s, z, sd, t1, n)
            if tr is None:
                continue
            k, entry, stop = tr
            if (s["side"] == 1 and entry >= t1) or (s["side"] == -1 and entry <= t1):
                continue
            res, R, both = outcome(h, l, c, k, H, s["side"], entry, stop, t1, n)
            if res in ("win", "loss"):
                out.append({"id": sid, "trend": e["trend"], "y": res == "win"})
    return out


def summarize(ev, rc, tfc, periods, rng):
    rows = {}
    for sid in ("L", "S", "B"):
        for tr in ("順勢", "逆勢"):
            xs = [e for e in ev if e["id"] == sid and e["trend"] == tr]
            rs = [e for e in xs if e["res"] in ("win", "loss")]
            name = f"{tfc}:{sid}:{tr}"
            if not rs:
                rows[name] = {"n": 0, "n_all": len(xs)}
                continue
            y = np.array([e["res"] == "win" for e in rs], float)
            p = np.array([e["p"] for e in rs], float)
            px = np.array([e["p_x"] for e in rs], float)
            yrs = np.array([e["year"] for e in rs])
            edge = float(np.mean(y - p))
            boot = C.year_boot(yrs, lambda idx: float(np.mean(y[idx] - p[idx])) if len(idx) else None, rng)
            lo, hi = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))) if len(boot) else (None, None)
            pval = float((np.sum(boot <= 0) + 1) / (len(boot) + 1)) if len(boot) else None
            rcx = [r["y"] for r in rc if r["id"] == sid and r["trend"] == tr]
            per = {}
            for a, b in periods:
                m = (yrs >= int(a)) & (yrs <= int(b))
                if m.sum() >= 5:
                    per[f"{a}–{b[2:]}"] = round(float(np.mean(y[m] - p[m])) * 100, 1)
            rows[name] = {"n": len(rs), "n_all": len(xs), "timeout": round(1 - len(rs) / len(xs), 3) if xs else None,
                          "both": int(sum(1 for e in rs if e["both"])),
                          "win": round(float(np.mean(y)), 4), "rw": round(float(np.mean(p)), 4), "rw_x": round(float(np.mean(px)), 4),
                          "edge": round(edge, 4), "edge_x": round(float(np.mean(y - px)), 4), "ci": [lo, hi], "p": pval,
                          "rand_win": round(float(np.mean(rcx)), 4) if rcx else None, "n_rand": len(rcx),
                          "avgR": round(float(np.mean([e["R"] for e in xs])), 3), "periods": per}
    return rows


def maps_daily(D, tfc):
    st = S.stats()
    deg = "small" if tfc == "1d" else "mid"

    def f(t):
        a = float(D["atr"][t])
        if not np.isfinite(a) or a <= 0:
            return None
        lm, key, an = pit.map_at(D, t, "1d" if tfc == "1d" else "1wk", st=st)
        return lm["items"], float(D["c"][t]), a, ladder_dir(key, an[deg])
    return f


def load_intra():
    sys.path.insert(0, os.path.join(pit.ROOT, "research", "b80"))
    import run_vol as RV
    D2 = RV.load_d2()
    D1 = pit.load_twii_daily()
    return D2, D1


def maps_intra(D2, D1, win_n=300):
    st = S.stats()
    I.set_params(st)
    ts = D2["ts"]
    bars = [{"time": ts[i], "open": float(D2["o"][i]), "high": float(D2["h"][i]), "low": float(D2["l"][i]), "close": float(D2["c"][i]),
             "volume": D2["v"][i]} for i in range(len(ts))]
    ddates = list(D1["dates"])
    import bisect

    def f(t):
        a0 = max(0, t + 1 - win_n)
        bs = bars[a0:t + 1]
        day = datetime.fromtimestamp(ts[t], TW).strftime("%Y-%m-%d")
        j = bisect.bisect_left(ddates, day) - 1                       # 前一個交易日（不含當天）
        if j < 20:
            return None
        price = float(D2["c"][t])
        daily = {"prev_h": float(D1["h"][j]), "prev_l": float(D1["l"][j]), "prev_c": float(D1["c"][j]),
                 "ma20": float(np.mean(D1["c"][j - 19:j + 1])), "price": price}
        trend = 1 if price > daily["ma20"] else -1
        a = I.analyze_tf(60, bs, price, daily, trend)
        if not a.get("ok"):
            return None
        key = S._key_out(a["cands"], "ultra", price, a["atr"], st)
        h, l, c = a["hlc"]
        zones = VO.vol_zones(h, l, c, [b["volume"] for b in bs], a["atr"], I.SHOW[60])
        an = a["an"]
        lm = LM.build({"price": price, "win": S.TF_WIN["60m"], "levels": a["levels"], "key": key, "nest": None,
                       "wave": {"primary": an.get("primary"), "alternate": an.get("alternate")}, "positioning": None,
                       "zones": zones, "leg_dir": (a["cands"].get("dir") or 0), "vol_ok": False, "hlc": (h, l, c)})
        return lm["items"], price, float(a["atr"]), ladder_dir(key, an)
    return f


def main(which):
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(C.SEED)
    res = {}
    if "1d" in which or "1wk" in which:
        D = pit.prep_daily(pit.load_twii_daily())
        for tfc in [x for x in ("1d", "1wk") if x in which]:
            ev = run(D, tfc, maps_daily(D, tfc), rng)
            rc = rand_control(D, ev, tfc, rng)
            res[tfc] = {"rows": summarize(ev, rc, tfc, C.PERIODS_D1, rng), "n_events": len(ev),
                        "period": f"{D['dates'][250]}～{D['dates'][-1]}"}
            print(tfc, json.dumps(res[tfc]["rows"], ensure_ascii=False)[:1500], flush=True)
    if "intra" in which:
        D2, D1 = load_intra()
        D2["atr"] = E.atr(D2["h"], D2["l"], D2["c"])
        yrs = D2["years"]
        half = int(np.median(yrs))
        ev = run(D2, "intra", maps_intra(D2, D1), rng, log_every=300)
        rc = rand_control(D2, ev, "intra", rng)
        per = ((str(yrs.min()), str(half - 1 if half > yrs.min() else half)), (str(half), str(yrs.max())))
        res["intra"] = {"rows": summarize(ev, rc, "intra", per, rng), "n_events": len(ev),
                        "period": f"{D2['dates'][250]}～{D2['dates'][-1]}"}
        print("intra", json.dumps(res["intra"]["rows"], ensure_ascii=False)[:1500], flush=True)
    path = os.path.join(OUT, "setups.json")
    old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    old.update(res)
    # BH：全部試單 × 週期類別 × 順逆勢一起（18 個）
    pv = {nm: r.get("p") for tfc, x in old.items() if isinstance(x, dict) and "rows" in x for nm, r in x["rows"].items()}
    q = C.bh(pv)
    for tfc, x in old.items():
        if not (isinstance(x, dict) and "rows" in x):
            continue
        for nm, r in x["rows"].items():
            r["q"] = q.get(nm)
            per = list((r.get("periods") or {}).values())
            r["pass"] = bool(r.get("n", 0) >= MIN_N and r.get("edge") is not None and r["edge"] >= MIN_EDGE
                             and r["ci"][0] is not None and r["ci"][0] > 0 and r["q"] is not None and r["q"] < 0.05
                             and r.get("rand_win") is not None and r["win"] - r["rand_win"] >= MIN_VS_RAND
                             and per and all(v > 0 for v in per))
    json.dump(old, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("寫入", path)


if __name__ == "__main__":
    main(sys.argv[1:] or ["1d", "1wk", "intra"])
