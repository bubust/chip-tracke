"""B74 §4.1：校準三個級數的 m（下限固定 3%／6%／12%），只用 2000–2015，標準＝平均波段長度（交易日）
目標：小級 ≈10（5～15）、中級 ≈35（20～60）、大級 ≈150（≥120）。不看之後漲跌。"""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from wave import engine as E

df = pd.read_csv(os.path.join(os.path.dirname(__file__), "data", "TWII.csv"))
df = df[df.date <= "2015-12-31"].reset_index(drop=True)
h, l, c = df.h.values, df.l.values, df.c.values
ap = E.atr_pct_median(h, l, c)
TARGET = {"small": 10, "mid": 35, "big": 150}
FLOOR = {"small": 0.03, "mid": 0.06, "big": 0.12}
res = {}
for deg, tgt in TARGET.items():
    rows = []
    for m in np.arange(1.0, 20.01, 0.5):
        th = np.maximum(FLOOR[deg], m * np.where(np.isnan(ap), FLOOR[deg] / m, ap))
        piv = E.zigzag(h, l, th)
        if len(piv) < 3:
            continue
        idx = [p["i"] for p in piv]
        avg = float(np.mean(np.diff(idx)))
        rows.append((round(float(m), 1), len(piv), round(avg, 1)))
    best = min(rows, key=lambda r: abs(r[2] - tgt))
    res[deg] = {"m": best[0], "floor": FLOOR[deg], "n_pivots": best[1], "avg_len": best[2], "target": tgt,
                "grid": rows}
    print(deg, "best", best, "| sample", [r for r in rows if r[0] in (2, 3, 4, 6, 8, 10, 12, 14)])
json.dump({k: {kk: vv for kk, vv in v.items() if kk != "grid"} for k, v in res.items()},
          open(os.path.join(os.path.dirname(__file__), "calibration.json"), "w"), indent=1)
