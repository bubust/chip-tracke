"""B78 複雜結構（複合修正、三角形、楔形）的複雜度加分校準（PLAN-B78 §3）。
資料：research/wave/data/TWII.csv（fetch.py 下載）。不看之後漲跌：只看「各結構當主要劇本的天數比例」。
基準：同一份日報酬打亂順序（隨機漫步、沒有任何波浪結構）5 次。選法事先定好：
  e（擴散型再加）＝最小的值使擴散型 ≤ 收斂型（三角形、楔形各自，三個級數都成立；p 先用 0.10）
  p（複雜度加分）＝最小的值使複雜結構當主要劇本 ≤ 15%（三個級數都成立）
結果寫 research/wave/b78_calibration.json；引擎的 KIND_PRIOR／SUB_PRIOR 手動照抄。
用法：python research/wave/b78_calibrate.py"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
from wave import engine as E   # noqa: E402

KS = ["impulse", "correction", "combo", "tri_c", "tri_x", "dia_c", "dia_x"]
PS, ES = (0.06, 0.08, 0.10, 0.12, 0.15), (0.0, 0.03, 0.06, 0.09, 0.12, 0.15)
DEGS = ("small", "mid", "big")


def kk(x):
    if x["kind"] in ("triangle", "diagonal"):
        return x["kind"][:3] + ("_x" if x["corr_kind"] == "expanding" else "_c")
    return x["kind"]


def trend(c, t):
    return 0 if t + 1 < 240 else (1 if c[t] > np.mean(c[t - 239:t + 1]) else -1)


def collect(h, l, c, deg):
    """每天各結構（不含複雜度加分）的最佳分數"""
    kp, sp = dict(E.KIND_PRIOR), dict(E.SUB_PRIOR)
    E.KIND_PRIOR, E.SUB_PRIOR = {k: 0.0 for k in kp}, {k: 0.0 for k in sp}
    try:
        piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
        rows = []
        for t in range(260, len(c)):
            conf, tent = E.state_at(piv, h, l, t)
            best = {k: 9.0 for k in KS}
            for x in E.count_waves(conf + ([tent] if tent else []), trend=trend(c, t)):
                best[kk(x)] = min(best[kk(x)], x["score"])
            rows.append([best[k] for k in KS])
    finally:
        E.KIND_PRIOR, E.SUB_PRIOR = kp, sp
    return np.array(rows)


def shares(a, p, e):
    a = a + np.array([0, 0, p, p, p + e, p, p + e])
    v = a.min(1) < 9
    w = a[v].argmin(1)
    return [float(np.mean(w == i)) for i in range(len(KS))]


def shuffled(h, l, c, seed):
    rng = np.random.default_rng(seed)
    lr = np.diff(np.log(c))
    idx = rng.permutation(len(lr))
    cc = c[0] * np.exp(np.concatenate([[0], np.cumsum(lr[idx])]))
    hh = np.concatenate([[h[0]], (h[1:] / c[1:])[idx]]) * cc
    ll = np.concatenate([[l[0]], (l[1:] / c[1:])[idx]]) * cc
    return hh, ll, cc


def main():
    df = pd.read_csv(os.path.join(HERE, "data", "TWII.csv")).dropna(subset=["o", "h", "l", "c"])
    df = df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)
    h, l, c = (df[k].values.astype(float) for k in ("h", "l", "c"))
    real = {d: collect(h, l, c, d) for d in DEGS}
    null = {d: np.vstack([collect(*shuffled(h, l, c, s), d) for s in (1, 2, 3, 4, 5)]) for d in DEGS}
    grid = {f"p={p:.2f},e={e:.2f}": {nm: {d: dict(zip(KS, shares(D[d], p, e))) for d in DEGS}
                                     for nm, D in (("real", real), ("null", null))} for p in PS for e in ES}

    def ok_e(e, p=0.10):
        return all(shares(null[d], p, e)[4] <= shares(null[d], p, e)[3] + 1e-9
                   and shares(null[d], p, e)[6] <= shares(null[d], p, e)[5] + 1e-9 for d in DEGS)
    e_pick = next((e for e in ES if ok_e(e)), ES[-1])
    p_pick = next((p for p in PS if all(sum(shares(null[d], p, e_pick)[2:]) <= 0.15 for d in DEGS)), PS[-1])
    pick = grid[f"p={p_pick:.2f},e={e_pick:.2f}"]
    out = {"data": [str(df.date.iloc[0]), str(df.date.iloc[-1])], "p": p_pick, "e": e_pick,
           "complex_share": {nm: {d: round(1 - v[d]["impulse"] - v[d]["correction"], 4) for d in DEGS} for nm, v in pick.items()},
           "pick": pick, "grid": grid}
    with open(os.path.join(HERE, "b78_calibration.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("p", p_pick, "e", e_pick, "複雜結構當主要劇本的比例", out["complex_share"])


if __name__ == "__main__":
    main()
