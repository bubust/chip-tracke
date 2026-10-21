"""B76 R-I30／R-K30（PLAN-B76 §3，事先判準）：30 分 K 自己的級數＋轉折點規則
- 資料：加權 30 分 K＝Yahoo 5 分 K 60 天彙總；台指期 30 分 K＝期交所逐筆檔 30 天（只報告）
- R-I30：θ＝max(0.4%, m × 30 分 K ATR% 近 60 根中位數)，m ∈ {1.5, 2, 2.5, 3, 3.5, 4}；前 40 個交易日校準，
  選平均波段長度最接近 1.0 個交易日（加權每天 9 根）；後面只報告
- R-K30：K1／K2／K3（同 B75），H＝18 根；實用範圍 距離中位數 0.5～3 ATR30、90 百分位 ≤ 2%；3 個延續檢定自己一族 BH
樣本很短，統計力很低，結果只當參考。輸出 results/r30.json；run.py 併進 stats.json（intraday30、keylevel.modes.m30）"""
import json
import os

import numpy as np

from common import E, FD, OUT, arrays, bh, load_intraday, r4
import keylevel as KR

GRID = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
FLOOR = 0.004
TARGET_DAYS = 1.0
PER_DAY = {"TWII": 9, "TX": 38}


def theta(h, l, c, m):
    ap = E.atr_pct_median(h, l, c)
    return np.maximum(FLOOR, m * np.where(np.isnan(ap), FLOOR / m, ap))


def avg_days(h, l, c, m, sym):
    piv = E.zigzag(h, l, theta(h, l, c, m))
    if len(piv) < 3:
        return None, len(piv)
    return float(np.mean(np.diff([p["i"] for p in piv])) / PER_DAY[sym]), len(piv)


if __name__ == "__main__":
    res = {"cal": {}, "report": {}, "tx": {}}
    tw = load_intraday("TWII", 30)
    o, h, l, c, ts = arrays(tw)
    days = np.array([FD.tw_dt(x).strftime("%Y-%m-%d") for x in ts])
    ud = sorted(set(days))
    cut = ud[39] if len(ud) > 40 else ud[-1]
    cal, rep = days <= cut, days > cut
    for m in GRID:
        a, n = avg_days(h[cal], l[cal], c[cal], m, "TWII")
        res["cal"][str(m)] = {"avg_days": r4(a), "n_pivots": n}
        a2, n2 = avg_days(h[rep], l[rep], c[rep], m, "TWII")
        res["report"][str(m)] = {"avg_days": r4(a2), "n_pivots": n2}
    best = min((m for m in GRID if res["cal"][str(m)]["avg_days"] is not None),
               key=lambda m: abs(res["cal"][str(m)]["avg_days"] - TARGET_DAYS))
    res.update(m=best, floor=FLOOR, target_days=TARGET_DAYS, cal_period=f"{ud[0]}～{cut}", n_days=len(ud), n_bars=len(c))
    tx = load_intraday("TX", 30)
    _, hx, lx, cx, tsx = arrays(tx)
    for m in GRID:
        a, n = avg_days(hx, lx, cx, m, "TX")
        res["tx"][str(m)] = {"avg_days": r4(a), "n_pivots": n}
    print("R-I30", {k: v["avg_days"] for k, v in res["cal"].items()}, "→ m", best)
    # R-K30
    E.INTRA30.update(m=best, floor=FLOOR)
    res["keylevel"] = {}
    for sym, bars in (("TWII", tw), ("TX", tx)):
        o, h, l, c, ts = arrays(bars)
        months = np.array([FD.tw_dt(x).strftime("%Y-%m-%d") for x in ts])     # 樣本短 → 用「日」分組 bootstrap
        piv = E.zigzag(h, l, theta(h, l, c, best))
        rec = KR.run_series(o, h, l, c, months, "intra30", "m30", piv, 60, lambda c_, t_: 0)
        res["keylevel"][sym] = KR.summarize(rec, "m30")
    cs = res["keylevel"]["TWII"]
    q = bh({r: s.get("p") for r, s in cs.items()})
    for r in cs:
        cs[r]["q"] = r4(q.get(r))
        cs[r]["sig"] = bool(cs[r].get("q") is not None and cs[r]["q"] < 0.10 and (cs[r]["ci"][0] or 0) > 0)
    rule, how = KR.choose(cs, "m30")
    res["rule"], res["how"], res["sig"] = rule, how, cs[rule]["sig"]
    for sym in ("TWII", "TX"):
        for r, s in res["keylevel"][sym].items():
            print(sym, r, {k: s.get(k) for k in ("dist_atr_med", "dist_pct_med", "dist_pct_p90", "hit_rate", "n_break", "ft_rate", "placebo_rate", "diff", "q", "practical")})
    print("R-K30 →", rule, how, "顯著" if res["sig"] else "不顯著")
    json.dump(res, open(os.path.join(OUT, "r30.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
