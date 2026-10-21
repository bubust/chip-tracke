"""B75 R-I（PLAN-B75 §4.2）：超短線 60 分 K 級數。θ＝max(0.5%, m × 60 分 K ATR% 近 60 根中位數)
校準期 2024-10～2025-12（加權 60 分 K），m ∈ {1.5, 2, 2.5, 3, 3.5, 4, 5}，選平均波段長度最接近 1.5 個交易日；
2026 只報告不調；台指期用同一個 m（報告台指期 60 分 K 30 天的平均長度）。不看之後漲跌。"""
import json
import os

import numpy as np

from common import E, FD, OUT, arrays, load_intraday, r4

GRID = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0)
FLOOR = 0.005
TARGET_DAYS = 1.5


def avg_leg_days(h, l, c, t, m, sym):
    ap = E.atr_pct_median(h, l, c)
    th = np.maximum(FLOOR, m * np.where(np.isnan(ap), FLOOR / m, ap))
    piv = E.zigzag(h, l, th)
    if len(piv) < 3:
        return None, len(piv)
    # 交易日數：兩個轉折之間經過幾個不同的「盤」日（用日曆日數近似；台指期夜盤跨日 → 用 K 棒數 ÷ 每天根數）
    per_day = 5 if sym == "TWII" else 19
    idx = [p["i"] for p in piv]
    return float(np.mean(np.diff(idx)) / per_day), len(piv)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    tw = load_intraday("TWII", 60)
    o, h, l, c, ts = arrays(tw)
    day = np.array([FD.tw_dt(x).strftime("%Y-%m") for x in ts])
    cal = (day >= "2024-10") & (day <= "2025-12")
    rep = day >= "2026-01"
    res = {"grid": {}, "report_2026": {}, "tx": {}}
    for m in GRID:
        a, n = avg_leg_days(h[cal], l[cal], c[cal], ts[cal], m, "TWII")
        res["grid"][str(m)] = {"avg_days": r4(a), "n_pivots": n}
        a2, n2 = avg_leg_days(h[rep], l[rep], c[rep], ts[rep], m, "TWII")
        res["report_2026"][str(m)] = {"avg_days": r4(a2), "n_pivots": n2}
    best = min((m for m in GRID if res["grid"][str(m)]["avg_days"] is not None),
               key=lambda m: abs(res["grid"][str(m)]["avg_days"] - TARGET_DAYS))
    res["m"], res["floor"], res["target_days"] = best, FLOOR, TARGET_DAYS
    res["n_bars_cal"], res["cal_period"] = int(cal.sum()), "2024-10～2025-12"
    try:
        tx = load_intraday("TX", 60)
        _, hx, lx, cx, tsx = arrays(tx)
        for m in GRID:
            a, n = avg_leg_days(hx, lx, cx, tsx, m, "TX")
            res["tx"][str(m)] = {"avg_days": r4(a), "n_pivots": n}
        res["tx_bars"] = len(tx)
    except FileNotFoundError:
        res["tx"] = None
    json.dump(res, open(os.path.join(OUT, "intraday_calibration.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items()}, ensure_ascii=False, indent=1))
