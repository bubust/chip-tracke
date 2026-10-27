"""B80 R-I15（PLAN-B80 §4，事先判準）：15 分 K 自己的級數
- 資料：加權 Yahoo 5 分 K 60 天（research/b80/data/twii_5m.csv）→ 15 分 K（futdata.agg_bars，跟網站同一套）
- θ＝max(0.3%, m × 15 分 K ATR% 近 60 根中位數)，m ∈ {1.5, 2, 2.5, 3, 3.5, 4}
- 前 40 個交易日校準：選平均波段長度最接近 0.5 個交易日（加權每天 18 根）；後面只報告
- 台指期 15 分 K（本機 wave.db bars5，約 45 天）只報告
輸出 results/r15.json"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
from wave import engine as E, futdata as FD  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
GRID = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
FLOOR = 0.003
TARGET_DAYS = 0.5
PER_DAY = {"TWII": 18, "TX": 76}      # 加權 09:00～13:30＝18 根；台指期日盤 20＋夜盤 56


def r4(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def arrays(bars):
    return tuple(np.array([b[k] for b in bars], float) for k in ("open", "high", "low", "close")) + \
        (np.array([b["time"] for b in bars], int),)


def theta(h, l, c, m):
    ap = E.atr_pct_median(h, l, c)
    return np.maximum(FLOOR, m * np.where(np.isnan(ap), FLOOR / m, ap))


def avg_days(h, l, c, m, sym):
    piv = E.zigzag(h, l, theta(h, l, c, m))
    if len(piv) < 3:
        return None, len(piv)
    return float(np.mean(np.diff([p["i"] for p in piv])) / PER_DAY[sym]), len(piv)


def tx_bars():
    try:
        rows = FD.load_bars5("TX", 0)
    except Exception:     # noqa: BLE001
        return []
    return FD.agg_bars(rows, "TX", 15)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    df = pd.read_csv(os.path.join(DATA, "twii_5m.csv"))
    rows = [(int(r.ts), r.o, r.h, r.l, r.c, 0.0) for r in df.itertuples()]
    tw = FD.agg_bars(rows, "TWII", 15)
    o, h, l, c, ts = arrays(tw)
    days = np.array([FD.tw_dt(x).strftime("%Y-%m-%d") for x in ts])
    ud = sorted(set(days))
    cut = ud[39] if len(ud) > 40 else ud[-1]
    cal, rep = days <= cut, days > cut
    res = {"cal": {}, "report": {}, "tx": {}}
    for m in GRID:
        a, n = avg_days(h[cal], l[cal], c[cal], m, "TWII")
        res["cal"][str(m)] = {"avg_days": r4(a) if a is not None else None, "n_pivots": n}
        a2, n2 = avg_days(h[rep], l[rep], c[rep], m, "TWII") if rep.sum() > 40 else (None, 0)
        res["report"][str(m)] = {"avg_days": r4(a2) if a2 is not None else None, "n_pivots": n2}
    best = min((m for m in GRID if res["cal"][str(m)]["avg_days"] is not None),
               key=lambda m: abs(res["cal"][str(m)]["avg_days"] - TARGET_DAYS))
    tx = tx_bars()
    if len(tx) > 100:
        _, hx, lx, cx, _ = arrays(tx)
        for m in GRID:
            a, n = avg_days(hx, lx, cx, m, "TX")
            res["tx"][str(m)] = {"avg_days": r4(a) if a is not None else None, "n_pivots": n}
    res.update(m=best, floor=FLOOR, target_days=TARGET_DAYS, cal_period=f"{ud[0]}～{cut}", n_days=len(ud), n_bars=len(c),
               data="加權 15 分 K（Yahoo 5 分 K 60 天彙總；樣本短只當參考）")
    print("R-I15 cal", {k: v["avg_days"] for k, v in res["cal"].items()}, "→ m", best)
    print("report", {k: v["avg_days"] for k, v in res["report"].items()})
    print("tx", {k: v["avg_days"] for k, v in res["tx"].items()})
    with open(os.path.join(OUT, "r15.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
