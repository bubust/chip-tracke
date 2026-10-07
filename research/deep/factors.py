"""
哪些技術因子對未來 20 日超額報酬有用（PLAN-DEEP2 §3；決定 deep_verdict 技術分要放哪些因子）

用法：python research/deep/factors.py PD_CSV_GZ
母體：20 日均量 ≥300 張、股價 ≥10（量已用 deep_verdict.lots_volume 換算成張）；每 5 天取樣；
x20＝未來 20 日報酬 − 同一天所有樣本平均。二元因子印「有 vs 沒有」，連續因子印五分位。
"""
import os, sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep_verdict import tech_series   # noqa: E402
from backtest import load              # noqa: E402


def rows_of(item):
    sid, g = item
    ts = tech_series(g)
    c = g.close.values.astype(float)
    s = pd.Series(c)
    dif = (s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()).values
    osc = dif - pd.Series(dif).ewm(span=9, adjust=False).mean().values
    v = ts["vol20"].values
    vol = pd.Series(g.volume.values.astype(float))
    out = []
    for t in range(130, len(g) - 21, 5):
        r = ts.iloc[t]
        if c[t] < 10 or not v[t] or np.isnan(v[t]) or v[t] < 300:
            continue
        out.append({"date": g.date.iloc[t], "f20": c[t + 20] / c[t] - 1,
                    "bull": bool(r["bull"]), "above60": bool(r["above60"]), "ma60_up": bool(r["ma60_up"]),
                    "dif_pos": bool(r["dif_pos"]), "osc_pos": osc[t] > 0, "osc_rise": osc[t] > osc[t - 1],
                    "pos52": r["pos52"], "r20": r["r20"], "r60": r["r60"], "r120": r["r120"], "bias20": r["bias20"],
                    "vr": vol.iloc[t] / v[t - 1] if v[t - 1] else np.nan})
    return out


if __name__ == "__main__":
    G = load(sys.argv[1])
    with Pool(8) as pool:
        S = pd.DataFrame([r for part in pool.map(rows_of, list(G.items()), chunksize=16) for r in part])
    S["x20"] = S.f20 - S.groupby("date").f20.transform("mean")
    print("samples", len(S))
    for k in ("bull", "above60", "ma60_up", "dif_pos", "osc_pos", "osc_rise"):
        m = S[k].astype(bool)
        print(f"{k:9s} 有 {S[m].x20.mean() * 100:+.2f}%  沒有 {S[~m].x20.mean() * 100:+.2f}%  ({m.mean() * 100:.0f}% 樣本)")
    for k in ("pos52", "r20", "r60", "r120", "bias20", "vr"):
        q = pd.qcut(S[k], 5, labels=False, duplicates="drop")
        print(f"{k:9s} 五分位 x20:", [round(S[q == i].x20.mean() * 100, 2) for i in range(5)])
