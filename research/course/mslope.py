"""
權證小哥「月線斜率」有沒有用（B70 R3，PLAN-B70.md §2；預先登錄 2 個組合，看完結果不加版本）

用法：python research/course/mslope.py PD_CSV_GZ
月線斜率＝(今天 MA20 − 昨天 MA20) ÷ 昨天 MA20（%）；>1% 強勢、>3% 妖股（商周財富網 Smart 月刊）
母體：4 碼普通股、排除 00 開頭 ETF、20 日均量 ≥300 張、股價 ≥10；每天取樣；x＝未來報酬 − 同一天所有樣本平均
組合（預先登錄）：C3＝斜率 >1% 且 0 ≤ 月線乖離 ≤ 3%；C5＝斜率 >1% 且 0 ≤ 月線乖離 ≤ 5%
採用規則（PLAN §2）：兩個半段 x20 都 > 0、全樣本 x20 ≥ 0.5%、按月 block bootstrap 2,000 次 95% 下限 > 0 → 標「回測有效」
"""
import json, os, sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from deep_verdict import lots_volume   # noqa: E402


def load(path):
    d = pd.read_csv(path, dtype={"stock_id": str, "date": str})
    d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(["stock_id", "date"])
    return {sid: g.reset_index(drop=True) for sid, g in d.groupby("stock_id")
            if sid[:1].isdigit() and len(sid) == 4 and not sid.startswith("00") and len(g) >= 150}


def month_slope(c: pd.Series) -> pd.Series:
    ma20 = c.rolling(20).mean()
    return (ma20 / ma20.shift(1) - 1) * 100


def rows_of(item):
    sid, g = item
    c = g.close.astype(float).reset_index(drop=True)
    v = lots_volume(g.volume.astype(float).reset_index(drop=True)).rolling(20, min_periods=15).mean()
    ma20 = c.rolling(20).mean()
    sl = month_slope(c)
    bias = (c / ma20 - 1) * 100
    out = []
    for t in range(60, len(g) - 21):
        if c[t] < 10 or not v[t] or np.isnan(v[t]) or v[t] < 300 or np.isnan(sl[t]):
            continue
        out.append({"date": g.date.iloc[t], "f5": c[t + 5] / c[t] - 1, "f20": c[t + 20] / c[t] - 1,
                    "slope": sl[t], "bias": bias[t]})
    return out


def boot_ci(S, mask, n=2000, seed=7):
    """按月分組重抽樣：每次抽同樣多個月（可重複），算組內 x20 平均；回 (2.5%, 97.5%)"""
    rng = np.random.default_rng(seed)
    d = S[mask]
    months = d.date.str[:6]
    groups = [g.x20.to_numpy() for _, g in d.groupby(months)]
    if len(groups) < 3:
        return (None, None)
    means = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        arr = np.concatenate([groups[i] for i in pick])
        means.append(arr.mean())
    return (round(float(np.percentile(means, 2.5)) * 100, 2), round(float(np.percentile(means, 97.5)) * 100, 2))


def st(S, m):
    d = S[m]
    a, b = d[d.date < "20260101"], d[d.date >= "20260101"]
    return {"x5": round(d.x5.mean() * 100, 2), "x20": round(d.x20.mean() * 100, 2), "up": round((d.f20 > 0).mean() * 100),
            "n": int(m.sum()), "x20_2025": round(a.x20.mean() * 100, 2), "x20_2026": round(b.x20.mean() * 100, 2)}


if __name__ == "__main__":
    G = load(sys.argv[1])
    with Pool(8) as pool:
        S = pd.DataFrame([r for part in pool.map(rows_of, list(G.items()), chunksize=16) for r in part])
    S["x5"] = S.f5 - S.groupby("date").f5.transform("mean")
    S["x20"] = S.f20 - S.groupby("date").f20.transform("mean")
    print("samples", len(S))
    out = {"buckets": {}, "combos": {}}
    for name, m in [("<0", S.slope < 0), ("0~0.4", (S.slope >= 0) & (S.slope < 0.4)), ("0.4~1", (S.slope >= 0.4) & (S.slope < 1)),
                    ("1~3", (S.slope >= 1) & (S.slope < 3)), (">3", S.slope >= 3)]:
        out["buckets"][name] = st(S, m)
        print(f"斜率 {name:6s}", out["buckets"][name])
    for name, lim in (("C3", 3), ("C5", 5)):
        m = (S.slope > 1) & (S.bias >= 0) & (S.bias <= lim)
        r = st(S, m)
        r["ci"] = boot_ci(S, m)
        r["pass"] = bool(r["x20_2025"] > 0 and r["x20_2026"] > 0 and r["x20"] >= 0.5 and r["ci"][0] is not None and r["ci"][0] > 0)
        out["combos"][name] = r
        print(f"組合 {name}（斜率>1%、乖離 0～{lim}%）", r)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "mslope_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
