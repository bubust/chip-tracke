"""
關鍵價位結合宏爺線（B70 R1，PLAN-B70.md §2）：MA20／MA100／週線前高 能不能改進現行 price_levels 的支撐／停損／壓力／目標

用法：python research/levels/hongye_levels.py PD_CSV_GZ [最多幾檔]
- 現行＝price_levels.compute_levels(df[:t+1])（網站實際在用的程式），t 從第 250 根起每 10 根取樣
- 母體：4 碼普通股、排除 00 開頭 ETF、20 日均量 ≥300 張、股價 ≥10；只用 t 以前（含）的資料；週 K 只用 t 那週以前已走完的週
- 預先登錄 7 個版本（看完結果不加版本、不調門檻）：
  支撐  S_MA20、S_MA100、S_NEAR（MA20 與現行支撐取離現價較近者）  vs 現行支撐
        指標＝撐住率 − 同 ATR 距離洗牌基準（碰到＝低 ≤ S+0.5%；撐住＝之後 6 根收盤都沒跌破 S−1%）；門檻 ≥ +3 個百分點
  停損  X_BULL（多頭格局：max(現行停損, MA20−1ATR)）、X_BOX（多箱格局：MA100−0.5ATR）  vs 現行停損（同一個目標）
        交易模擬：t 收盤進、40 天、最高碰目標賣在目標、收盤破停損賣在當天收盤、到期賣；扣 0.585%
        門檻：每筆平均 +0.3 個百分點以上、最差 5% 那筆不變差超過 0.3 個百分點
  壓力  P_WEEK（週 K k=2 波段高、現價上方最近的）vs 現行壓力一；指標＝擋住率 − 基準（碰到＝高 ≥ R−0.5%；擋住＝之後 6 根收盤沒站上 R+1%）
  目標  T_WEEK（同上週線前高當目標）vs 現行目標（同一個停損）；交易模擬門檻同停損
- 採用：全樣本達門檻＋2025／2026 兩段都比現行好＋按月 block bootstrap 2,000 次差值 95% 下限 > 0
"""
import json, os, sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from deep_verdict import lots_volume   # noqa: E402

H, STEP, START = 40, 10, 250
COST = 0.00585
G = None


def load(path, limit=None):
    d = pd.read_csv(path, dtype={"stock_id": str, "date": str})
    d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(["stock_id", "date"])
    out = {sid: g.reset_index(drop=True) for sid, g in d.groupby("stock_id")
           if sid[:1].isdigit() and len(sid) == 4 and not sid.startswith("00") and len(g) >= START + H + 10}
    if limit:
        out = dict(list(out.items())[:limit])
    return out


def weekly_bars(df: pd.DataFrame) -> pd.DataFrame:
    """日 K → 週 K（ISO 週）：週一開、週高、週低、最後一天收；回傳含 last_idx（那週最後一根日 K 的位置）"""
    dt = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    iso = dt.dt.isocalendar()
    key = iso.year.astype(int) * 100 + iso.week.astype(int)
    rows = []
    for k, idx in df.groupby(key.values).groups.items():
        idx = sorted(idx)
        g = df.loc[idx]
        rows.append({"wk": int(k), "open": float(g.open.iloc[0]), "high": float(g.high.max()), "low": float(g.low.min()),
                     "close": float(g.close.iloc[-1]), "last_idx": int(idx[-1]), "n": len(idx)})
    return pd.DataFrame(rows).sort_values("wk").reset_index(drop=True)


def week_pivot_high_above(W: pd.DataFrame, t: int, price: float, k: int = 2):
    """t 那週以前已走完的週 K，k=2 波段高（左右各 2 週都比它低），現價上方最近的一個；沒有回 None"""
    w = W[W.last_idx < t]                     # t 那週還沒走完 → 不用（t 是那週最後一天也排除，保守）
    hs = w.high.to_numpy()
    best = None
    for i in range(k, len(hs) - k):
        if hs[i] > hs[i - k:i].max() and hs[i] >= hs[i + 1:i + k + 1].max() and hs[i] > price * 1.005:
            best = hs[i] if best is None or hs[i] < best else best
    return best


def touch_hold(arr_lo, arr_c, level, kind):
    """支撐 kind='S'：第一次 低 ≤ S×1.005 → 之後 6 根收盤都 ≥ S×0.99 ＝撐住；壓力 kind='R'：高 ≥ R×0.995 → 之後 6 根收盤都 ≤ R×1.01
    回 None（沒碰到）／1（撐住／擋住）／0"""
    if level is None:
        return None
    hit = np.where(arr_lo <= level * 1.005)[0] if kind == "S" else np.where(arr_lo >= level * 0.995)[0]
    if not len(hit):
        return None
    j = int(hit[0])
    nxt = arr_c[j + 1:j + 7]
    if len(nxt) < 6:
        return None
    return int((nxt >= level * 0.99).all()) if kind == "S" else int((nxt <= level * 1.01).all())


def trade(p, hs, cs, T, X):
    """t 收盤 p 進場；X＝停損（收盤跌破出場）、T＝目標（最高碰到出場）；回扣成本報酬"""
    for j in range(len(cs)):
        if X is not None and cs[j] < X:
            return cs[j] / p - 1 - COST
        if T is not None and hs[j] >= T:
            return T / p - 1 - COST
    return cs[-1] / p - 1 - COST


def work(sid):
    from price_levels import compute_levels, atr_series
    from deep_patterns import trend_box
    g = G[sid]
    c, h, l = (g[k].values.astype(float) for k in ("close", "high", "low"))
    v20 = lots_volume(g.volume.astype(float)).rolling(20, min_periods=15).mean().values
    ma20 = pd.Series(c).rolling(20).mean().values
    ma100 = pd.Series(c).rolling(100).mean().values
    A = atr_series(h, l, c)
    W = weekly_bars(g)
    out = []
    for t in range(START, len(g) - H - 1, STEP):
        p = c[t]
        if p < 10 or not v20[t] or np.isnan(v20[t]) or v20[t] < 300 or np.isnan(A[t]) or np.isnan(ma100[t]):
            continue
        lv = compute_levels(g.iloc[:t + 1])
        if lv.get("error"):
            continue
        S0 = (lv.get("support") or {}).get("price")
        X0 = (lv.get("stop") or {}).get("price")
        T0 = lv.get("target")
        P0 = (lv.get("pressure1") or {}).get("low")
        a = float(A[t])
        box = trend_box(p, ma20[t], ma100[t])
        below = lambda x: x if (x is not None and x < p) else None          # noqa: E731
        above = lambda x: x if (x is not None and x > p * 1.005) else None  # noqa: E731
        S0 = below(S0)
        sup = {"S0": S0, "S_MA20": below(ma20[t]), "S_MA100": below(ma100[t])}
        sup["S_NEAR"] = max([x for x in (S0, sup["S_MA20"]) if x is not None], default=None)
        wp = week_pivot_high_above(W, t, p)
        lo_f, hi_f, c_f = l[t + 1:t + H + 1], h[t + 1:t + H + 1], c[t + 1:t + H + 1]
        r = {"sid": sid, "date": str(g.date.iloc[t]), "box": box, "p": p, "atr": a}
        for k, x in sup.items():
            r[k] = x
            r["o_" + k] = touch_hold(lo_f, c_f, x, "S")
        r["P0"], r["P_WEEK"] = above(P0), wp
        r["o_P0"] = touch_hold(hi_f, c_f, r["P0"], "R")
        r["o_P_WEEK"] = touch_hold(hi_f, c_f, wp, "R")
        X0 = below(X0)
        T0 = above(T0)
        if X0 is not None and T0 is not None:
            r["ret_cur"] = trade(p, hi_f, c_f, T0, X0)
            xb = below(max(X0, ma20[t] - a)) if box == "多頭" else None
            r["ret_X_BULL"] = trade(p, hi_f, c_f, T0, xb) if xb is not None else None
            xx = below(ma100[t] - 0.5 * a) if box == "多箱" else None
            r["ret_X_BOX"] = trade(p, hi_f, c_f, T0, xx) if xx is not None else None
            r["ret_T_WEEK"] = trade(p, hi_f, c_f, wp, X0) if wp is not None else None
        out.append(r)
    return out


def init(path, limit):
    global G
    G = load(path, limit)


def main():
    path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    init(path, limit)
    with Pool(8, initializer=init, initargs=(path, limit)) as pool:
        parts = pool.map(work, list(G.keys()), chunksize=4)
    D = pd.DataFrame([r for p in parts for r in p])
    D["half"] = np.where(D.date < "20260101", "2025", "2026")
    D["month"] = D.date.str[:6]
    print("samples", len(D), "stocks", D.sid.nunique())
    rng = np.random.default_rng(11)
    res = {"n": len(D), "support": {}, "pressure": {}, "trade": {}}

    # ── 支撐／壓力：撐住率差（成對：同一批樣本裡 版本 vs 現行；基準用洗牌距離重算一次）──
    def level_outcome(key, kind):
        """每個樣本：版本價位的結果、同距離洗牌基準的結果（重算未來 K 線）"""
        d = D[D[key].notna()]
        dist = ((d[key] - d.p) / d.atr).to_numpy()
        perm = rng.permutation(dist)
        base = []
        for (i, row), dd in zip(d.iterrows(), perm):
            g = G[row.sid]
            t = int(g.index[g.date == row.date][0])
            arr = (g.low if kind == "S" else g.high).values[t + 1:t + H + 1].astype(float)
            cc = g.close.values[t + 1:t + H + 1].astype(float)
            base.append(touch_hold(arr, cc, row.p + dd * row.atr, kind))
        return pd.Series(base, index=d.index, dtype="float")

    def summarize_level(key, cur, kind):
        bv = level_outcome(key, kind)
        bc = level_outcome(cur, kind)
        D["b_" + key], D["b_" + cur] = bv, bc
        both = D[D[key].notna() & D[cur].notna()]

        def edge(sub, k):
            o, b = sub["o_" + k].dropna(), sub["b_" + k].dropna()
            return (o.mean() - b.mean()) * 100 if len(o) and len(b) else np.nan
        row = {"n": len(both), "touch%": round(both["o_" + key].notna().mean() * 100, 1)}
        row["edge"] = round(edge(both, key), 1)
        row["edge_cur"] = round(edge(both, cur), 1)
        row["diff"] = round(row["edge"] - row["edge_cur"], 1)
        for hf in ("2025", "2026"):
            sb = both[both.half == hf]
            row[f"diff_{hf}"] = round(edge(sb, key) - edge(sb, cur), 1)
        months = both.month.unique()
        boots = []
        for _ in range(2000):
            pick = rng.choice(months, len(months))
            sb = pd.concat([both[both.month == m] for m in pick])
            boots.append(edge(sb, key) - edge(sb, cur))
        row["ci"] = [round(float(np.nanpercentile(boots, 2.5)), 1), round(float(np.nanpercentile(boots, 97.5)), 1)]
        row["pass"] = bool(row["diff"] >= 3 and row["diff_2025"] > 0 and row["diff_2026"] > 0 and row["ci"][0] > 0)
        row["by_box"] = {}
        for bx in ("多頭", "多箱", "空箱", "空頭"):
            sb = both[both.box == bx]
            if len(sb) >= 300:
                row["by_box"][bx] = {"n": len(sb), "diff": round(edge(sb, key) - edge(sb, cur), 1)}
        return row

    for key in ("S_MA20", "S_MA100", "S_NEAR"):
        res["support"][key] = summarize_level(key, "S0", "S")
        print("支撐", key, res["support"][key])
    res["pressure"]["P_WEEK"] = summarize_level("P_WEEK", "P0", "R")
    print("壓力 P_WEEK", res["pressure"]["P_WEEK"])

    # ── 停損／目標：成對交易報酬差 ──
    for key in ("ret_X_BULL", "ret_X_BOX", "ret_T_WEEK"):
        if key not in D:
            continue
        d = D[D[key].notna() & D["ret_cur"].notna()]
        diff = (d[key] - d.ret_cur) * 100
        row = {"n": len(d), "avg": round(d[key].mean() * 100, 2), "avg_cur": round(d.ret_cur.mean() * 100, 2),
               "diff": round(diff.mean(), 2),
               "p5": round(d[key].quantile(.05) * 100, 2), "p5_cur": round(d.ret_cur.quantile(.05) * 100, 2)}
        for hf in ("2025", "2026"):
            row[f"diff_{hf}"] = round(diff[d.half == hf].mean(), 2)
        months = d.month.unique()
        by_m = {m: diff[d.month == m].to_numpy() for m in months}
        boots = [np.concatenate([by_m[m] for m in rng.choice(months, len(months))]).mean() for _ in range(2000)]
        row["ci"] = [round(float(np.percentile(boots, 2.5)), 2), round(float(np.percentile(boots, 97.5)), 2)]
        row["pass"] = bool(row["diff"] >= 0.3 and row["diff_2025"] > 0 and row["diff_2026"] > 0 and row["ci"][0] > 0
                           and row["p5"] >= row["p5_cur"] - 0.3)
        row["by_box"] = {bx: {"n": int((d.box == bx).sum()), "diff": round(diff[d.box == bx].mean(), 2)}
                         for bx in ("多頭", "多箱", "空箱", "空頭") if (d.box == bx).sum() >= 300}
        res["trade"][key[4:]] = row
        print("交易", key[4:], row)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hongye_levels_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
