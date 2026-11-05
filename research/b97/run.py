"""B97：用 15 分 K 回測 15 分週期的劇本（規則見 PLAN.md；觸發、結果、對照沿用 research/b81/run_setups.py）
python research/b97/run.py → results/setups15.json、REPORT.md"""
import bisect
import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "b81"))
import common as C  # noqa: E402
import run_setups as RS  # noqa: E402
from wave import engine as E, intraday as I, levelmap as LM, service as S, volume as VO  # noqa: E402

DATA = os.path.join(HERE, "data")
B94 = os.path.join(ROOT, "research", "b94", "data")
OUT = os.path.join(HERE, "results")
TW = timezone(timedelta(hours=8))
WIN_N = 1080                      # 最近 1,080 根 15 分 K（約 60 個交易日）
RS.CFG["intra15"] = {"W": 15, "H": 30}
RS.CFG["intra15w"] = {"W": 60, "H": 120}          # 敏感度：跟 60 分同樣的時間長度
PERIODS = (("2023", "2024"), ("2025", "2026"))


def load15(data_dir=B94, vol_path=None):
    vol = defaultdict(float)
    vol_path = vol_path or os.path.join(DATA, "twii_5m_amt.csv")
    has_vol = os.path.exists(vol_path)
    if has_vol:
        with open(vol_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                hh, mm = (int(x) for x in r["slot"].split(":"))
                m = hh * 60 + mm
                b = 9 * 60 + ((m - 9 * 60) // 15) * 15
                vol[f"{r['date']} {b // 60:02d}:{b % 60:02d}"] += float(r["amt"])
    rows = []
    with open(os.path.join(data_dir, "twii_15m.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])))
    rows = [x for x in rows if x[2] >= x[3] > 0]
    dates = [x[0] for x in rows]
    ts = [datetime.strptime(d, "%Y-%m-%d %H:%M").replace(tzinfo=TW).timestamp() for d in dates]
    o, h, l, c = (np.array([x[k] for x in rows], float) for k in (1, 2, 3, 4))
    v = [(vol.get(d) or None) if has_vol else None for d in dates]
    return {"name": "15m", "dates": [d[:10] for d in dates], "stamp": dates, "years": np.array([int(d[:4]) for d in dates]),
            "ts": ts, "o": o, "h": h, "l": l, "c": c, "v": v, "has_vol": has_vol}


def load_daily():
    rows = []
    with open(os.path.join(B94, "twii_d.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["date"], float(r["h"]), float(r["l"]), float(r["c"])))
            except ValueError:
                continue
    return {"dates": [x[0] for x in rows], "h": np.array([x[1] for x in rows]), "l": np.array([x[2] for x in rows]),
            "c": np.array([x[3] for x in rows])}


def maps_intra15(D2, D1, win_n=WIN_N):
    """第 t 根 15 分 K 收盤：網站 15 分同一套 → (價位梯 items, 現價, 15 分 ATR, 方向)"""
    st = S.stats()
    I.set_params(st)
    bars = [{"time": D2["ts"][i], "open": float(D2["o"][i]), "high": float(D2["h"][i]), "low": float(D2["l"][i]),
             "close": float(D2["c"][i]), "volume": D2["v"][i]} for i in range(len(D2["ts"]))]
    ddates = list(D1["dates"])

    def f(t):
        bs = bars[max(0, t + 1 - win_n):t + 1]
        j = bisect.bisect_left(ddates, D2["dates"][t]) - 1                # 前一個交易日
        if j < 20:
            return None
        price = float(D2["c"][t])
        daily = {"prev_h": float(D1["h"][j]), "prev_l": float(D1["l"][j]), "prev_c": float(D1["c"][j]),
                 "ma20": float(np.mean(D1["c"][j - 19:j + 1])), "price": price}
        trend = 1 if price > daily["ma20"] else -1
        a = I.analyze_tf(15, bs, price, daily, trend)
        if not a.get("ok"):
            return None
        key = S._key_out(a["cands"], "m15", price, a["atr"], st)
        h, l, c = a["hlc"]
        zones = VO.vol_zones(h, l, c, [b["volume"] for b in bs], a["atr"], I.SHOW[15])
        an = a["an"]
        lm = LM.build({"price": price, "win": S.TF_WIN["15m"], "levels": a["levels"], "key": key, "nest": None,
                       "wave": {"primary": an.get("primary"), "alternate": an.get("alternate")}, "positioning": None,
                       "zones": zones, "leg_dir": (a["cands"].get("dir") or 0), "vol_ok": False, "hlc": (h, l, c)})
        return lm["items"], price, float(a["atr"]), RS.ladder_dir(key, an)
    return f


COST = 0.0002                     # 來回 0.02%（只用在「每筆點數」；先到目標比例跟網站一樣不扣成本）


def run(D, tfc, maps_fn, rng, log_every=1000):
    """跟 research/b81/run_setups.run 同一套（觸發、結果、不重複），多記進場、停損、目標的點數"""
    h, l, c = D["h"], D["l"], D["c"]
    n = len(c)
    W, H = RS.CFG[tfc]["W"], RS.CFG[tfc]["H"]
    ev, busy, t0 = [], {}, time.time()
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
            tr = RS.trigger(h, l, c, t, W, s, z, sd, s["t1"], n)
            if tr is None:
                continue
            k, entry, stop = tr
            if (s["side"] == 1 and entry >= s["t1"]) or (s["side"] == -1 and entry <= s["t1"]):
                continue
            res, R, both = RS.outcome(h, l, c, k, H, s["side"], entry, stop, s["t1"], n)
            if res is None:
                continue
            busy[key] = k + H
            dp = C.drift_params(c, k)
            if dp is None:
                continue
            mu, sd_ = dp
            risk = abs(entry - stop)
            ev.append({"t": t, "k": k, "id": s["id"], "side": s["side"], "trend": s["trend"] or "無", "res": res, "R": R, "both": both,
                       "p": C.p_first(entry, s["t1"], stop, s["side"], mu, sd_), "price": price, "atr": atr,
                       "dS": abs(price - s["level"]) / atr, "dT": abs(s["t1"] - price) / atr,
                       "year": int(D["years"][k]), "entry": entry, "risk": risk, "tg": abs(s["t1"] - entry),
                       "pts": R * risk - COST * entry, "rr_card": s.get("rr")})
        if log_every and t % log_every == 0:
            print(f"  {tfc} t={t}/{n} 事件 {len(ev)}（{time.time() - t0:.0f}s）", flush=True)
    return ev


def month_boot(months, stat_fn, rng, n=C.N_BOOT):
    months = np.asarray(months)
    um = np.unique(months)
    g = {m: np.where(months == m)[0] for m in um}
    out = []
    for _ in range(n):
        pk = rng.choice(um, size=len(um), replace=True)
        idx = np.concatenate([g[m] for m in pk]) if len(pk) else np.array([], int)
        v = stat_fn(idx)
        if v is not None and np.isfinite(v):
            out.append(v)
    return np.array(out)


def summarize(ev, rc, tfc, D2, rng):
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
            ok = np.isfinite(p)
            y, p, rs2 = y[ok], p[ok], [e for e, k in zip(rs, ok) if k]
            mon = np.array([D2["stamp"][e["k"]][:7] for e in rs2])
            yrs = np.array([e["year"] for e in rs2])
            boot = month_boot(mon, lambda idx: float(np.mean(y[idx] - p[idx])) if len(idx) else None, rng)
            lo, hi = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))) if len(boot) else (None, None)
            pval = float(max(2 * min((boot <= 0).mean(), (boot >= 0).mean()), 1 / C.N_BOOT)) if len(boot) else None
            rcx = [r["y"] for r in rc if r["id"] == sid and r["trend"] == tr]
            per = {}
            for a, b in PERIODS:
                m = (yrs >= int(a)) & (yrs <= int(b))
                if m.sum() >= 5:
                    per[f"{a}–{b[2:]}"] = round(float(np.mean(y[m] - p[m])) * 100, 1)
            rows[name] = {"n": len(rs2), "n_all": len(xs), "timeout": round(1 - len(rs) / len(xs), 3) if xs else None,
                          "both": int(sum(1 for e in rs2 if e["both"])),
                          "win": round(float(np.mean(y)), 4), "rw": round(float(np.mean(p)), 4),
                          "edge": round(float(np.mean(y - p)), 4), "ci": [lo, hi], "p": pval,
                          "rand_win": round(float(np.mean(rcx)), 4) if rcx else None, "n_rand": len(rcx),
                          "avgR": round(float(np.mean([e["R"] for e in xs])), 3), "periods": per,
                          "atr_med": round(float(np.median([e["atr"] for e in xs])), 1),
                          "risk_med": round(float(np.median([e["risk"] for e in xs])), 1),
                          "tg_med": round(float(np.median([e["tg"] for e in xs])), 1),
                          "pts_mean": round(float(np.mean([e["pts"] for e in xs])), 1),
                          "pts_sum": round(float(np.sum([e["pts"] for e in xs])), 0),
                          "cost_med": round(float(np.median([COST * e["entry"] for e in xs])), 1),
                          "rr_med": round(float(np.median([e["tg"] / e["risk"] for e in xs if e["risk"] > 0])), 2),
                          "rr_card": round(float(np.median([e["rr_card"] for e in xs if e.get("rr_card")])), 2)}
    return rows


def judge(rows):
    pv = {nm: r.get("p") for nm, r in rows.items()}
    q = C.bh(pv)
    for nm, r in rows.items():
        r["q"] = q.get(nm)
        per = list((r.get("periods") or {}).values())
        r["pass"] = bool(r.get("n", 0) >= RS.MIN_N and r.get("edge") is not None and r["edge"] >= RS.MIN_EDGE
                         and r["ci"][0] is not None and r["ci"][0] > 0 and r["q"] is not None and r["q"] < 0.05
                         and r.get("rand_win") is not None and r["win"] - r["rand_win"] >= RS.MIN_VS_RAND
                         and len(per) == len(PERIODS) and all(v > 0 for v in per))
        r["worse"] = bool(r.get("n", 0) >= RS.MIN_N and r.get("ci") and r["ci"][1] is not None and r["ci"][1] < 0)
    return rows


def main(data_dir=B94, vol_path=None, out_dir=OUT, which=("intra15", "intra15w")):
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(C.SEED)
    D2 = load15(data_dir, vol_path)
    D1 = load_daily()
    D2["atr"] = E.atr(D2["h"], D2["l"], D2["c"])
    print("15m", len(D2["c"]), D2["stamp"][0], D2["stamp"][-1], "量", D2["has_vol"], flush=True)
    res = {"generated": time.strftime("%Y-%m-%d %H:%M"), "period": f"{D2['stamp'][250]}～{D2['stamp'][-1]}", "has_vol": D2["has_vol"],
           "win_n": WIN_N, "cfg": {k: RS.CFG[k] for k in which}}
    fmap = maps_intra15(D2, D1)
    cache = {}

    def cached(t):                                     # 兩種 W／H 用同一份價位梯
        if t not in cache:
            m = fmap(t)
            cache[t] = None if m is None else ([{k: it.get(k) for k in ("side", "price", "name")} for it in m[0]],) + tuple(m[1:])
        return cache[t]
    for tfc in which:
        ev = run(D2, tfc, cached, rng)
        rc = RS.rand_control(D2, ev, tfc, rng)
        rows = judge(summarize(ev, rc, tfc, D2, rng))
        res[tfc] = {"rows": rows, "n_events": len(ev)}
        print(tfc, f"{time.time() - t0:.0f}s", json.dumps({k: (v.get("n"), v.get("win"), v.get("rw"), v.get("q")) for k, v in rows.items()},
                                                         ensure_ascii=False), flush=True)
    try:
        b81 = json.load(open(os.path.join(ROOT, "research", "b81", "results", "setups.json"), encoding="utf-8")).get("intra")
        res["b81_60m"] = {k.replace("intra:", ""): {x: v.get(x) for x in ("n", "win", "rw", "edge", "pass")}
                          for k, v in (b81 or {}).get("rows", {}).items()}
    except (OSError, ValueError):
        res["b81_60m"] = None
    with open(os.path.join(out_dir, "setups15.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    report(res, HERE if out_dir == OUT else out_dir)
    print("done", f"{time.time() - t0:.0f}s")
    return res


def pc(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%"


def report(res, out_dir=HERE):
    NAME = {"L": "回測支撐試多", "S": "反彈壓力試空", "B": "站上回測追多"}
    L = ["# B97：15 分 K 的劇本回測", "",
         f"資料：加權 15 分 K（證交所每 5 秒指數）{res['period']}；成交量 {'有（MI_5MINS）' if res['has_vol'] else '沒有'}；每根用最近 {res['win_n']} 根算價位梯。規則見 PLAN.md。", ""]
    for tfc in ("intra15", "intra15w"):
        x = res.get(tfc)
        if not x:
            continue
        cfg = res["cfg"][tfc]
        L += [f"## {'主要' if tfc == 'intra15' else '敏感度'}：觸發 {cfg['W']} 根內、結果看 {cfg['H']} 根（事件 {x['n_events']}）", "",
              "| 劇本 | 順逆 | 筆數（有結果／全部） | 先到目標 | 隨機漫步 | 差 | 95% 區間 | q | 隨機價位 | 平均 R | 停損／目標（點，中位數） | 賠率：卡片／實際 | 每筆點數（扣成本） | 2023–24／2025–26 | 60 分（B81）先到目標／隨機 | 判定 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for nm, r in x["rows"].items():
            _, sid, tr = nm.split(":")
            b = ((res.get("b81_60m") or {}).get(f"{sid}:{tr}") or {})
            if not r.get("n"):
                L.append(f"| {NAME[sid]} | {tr} | 0／{r.get('n_all', 0)} | | | | | | | | | | | | | |")
                continue
            per = "／".join(f"{v:+.1f}" for v in (r.get("periods") or {}).values())
            verdict = "✅" if r["pass"] else ("✗ 比隨機差" if r["worse"] else "△")
            L.append(f"| {NAME[sid]} | {tr} | {r['n']}／{r['n_all']} | {pc(r['win'])} | {pc(r['rw'])} | {r['edge'] * 100:+.1f} | "
                     f"[{r['ci'][0] * 100:+.1f}, {r['ci'][1] * 100:+.1f}] | {r['q']:.3f} | {pc(r['rand_win'])} | {r['avgR']:+.2f} | "
                     f"{r['risk_med']:.0f}／{r['tg_med']:.0f} | 1：{r['rr_card']:.1f}／1：{r['rr_med']:.1f} | {r['pts_mean']:+.1f}（成本約 {r['cost_med']:.0f}） | {per} | "
                     f"{pc(b.get('win'))}／{pc(b.get('rw'))}（{b.get('n', '—')} 筆） | {verdict} |")
        L.append("")
    with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
