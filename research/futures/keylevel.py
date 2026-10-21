"""B75 R-K（PLAN-B75 §2.3）：轉折點候選 K1 波浪失效點／K2 這段起點／K3 最近反向小轉折，三個模式比較。
- 短線＝加權日 K 小級、波段＝加權日 K 中級（2005～2026）；超短線＝加權 60 分 K（Yahoo 2 年，m 用 R-I 結果）＋台指期 60 分 K（30 天，只報告）
- 記：距離（ATR 倍數、%）、H 內碰到的比例、確認穿過後「延續」比例 vs 同距離對照價位（距離 ×U(0.7,1.3)，5 個）
- 實用範圍（硬條件）：距離中位數 超短線 0.5～3、短線 0.7～3.5、波段 1.5～8 ATR，且 90 百分位 ≤ 3%／6%／15%
- 選法：符合實用範圍者取「延續率−對照」最高；都不符合 → 距離中位數最接近範圍中點；9 個（候選×模式）延續檢定一起 BH
判準事先寫在計畫，這裡只照做。"""
import json
import os

import numpy as np

from common import E, FD, OUT, RNG, STATS, arrays, bh, block_boot_events, load_intraday, load_twii_daily, r4
from wave import keylevel as KL

MODES = {
    "ultra": {"band": (0.5, 3.0), "win": 0.03, "H": 15, "k3_look": 100},
    "m30": {"band": (0.5, 3.0), "win": 0.02, "H": 18, "k3_look": 120},          # B76（r30.py 用）
    "short": {"band": (0.7, 3.5), "win": 0.06, "H": 10, "k3_look": 60, "deg": "small"},
    "swing": {"band": (1.5, 8.0), "win": 0.15, "H": 40, "k3_look": 120, "deg": "mid"},
}
N_PLAC = 5


def trend_at(c, t):
    if t + 1 < 240:
        return 0
    return 1 if c[t] > float(np.mean(c[t - 239:t + 1])) else -1


def run_series(o, h, l, c, months, deg, mode, piv, start, trend_fn, step=1):
    cfg = MODES[mode]
    atr = E.atr(h, l, c)
    rec = {r: {"dist_atr": [], "dist_pct": [], "hit": [], "ft": [], "ft_m": [], "pl": [], "pl_m": []} for r in KL.RULES}
    n = len(c)
    for t in range(start, n - 1, step):
        A = atr[t]
        if not np.isfinite(A) or A <= 0:
            continue
        an = E.analyze(o, h, l, c, deg, t=t, trend=trend_fn(c, t), piv=piv)
        cands = KL.candidates(an, h, l, c, t, A, k=3, look=cfg["k3_look"])
        for r in KL.RULES:
            x = cands.get(r)
            if not x:
                continue
            X, side = x["price"], x["side"]
            if (side == "below" and X >= c[t]) or (side == "above" and X <= c[t]):
                continue                                   # 已經在錯的一邊（例：K1 已被穿過）→ 不算
            R = rec[r]
            R["dist_atr"].append(abs(X - c[t]) / A)
            R["dist_pct"].append(abs(X / c[t] - 1))
            seg = l[t + 1:t + 1 + cfg["H"]] <= X if side == "below" else h[t + 1:t + 1 + cfg["H"]] >= X
            R["hit"].append(bool(seg.any()))
            f = KL.follow_through(h, l, c, atr, X, side, t, cfg["H"])
            if f is not None:
                R["ft"].append(f)
                R["ft_m"].append(months[t])
            for _ in range(N_PLAC):
                Xp = c[t] + (X - c[t]) * RNG.uniform(0.7, 1.3)
                fp = KL.follow_through(h, l, c, atr, Xp, side, t, cfg["H"])
                if fp is not None:
                    R["pl"].append(fp)
                    R["pl_m"].append(months[t])
    return rec


def summarize(rec, mode):
    cfg = MODES[mode]
    out = {}
    for r, R in rec.items():
        if not R["dist_atr"]:
            out[r] = {"n": 0}
            continue
        da, dp = np.array(R["dist_atr"]), np.array(R["dist_pct"])
        ft, pl = np.array(R["ft"], float), np.array(R["pl"], float)
        fm, pm = np.array(R["ft_m"]), np.array(R["pl_m"])
        allm = np.concatenate([fm, pm])
        is_real = np.r_[np.ones(len(fm), bool), np.zeros(len(pm), bool)]
        vals = np.r_[ft, pl]

        def stat(ii):
            if len(ii) == 0:
                return None
            rr, vv = is_real[ii], vals[ii]
            if rr.sum() < 5 or (~rr).sum() < 5:
                return None
            return vv[rr].mean() - vv[~rr].mean()
        est, lo, hi, p = block_boot_events(allm, stat) if len(ft) >= 10 and len(pl) >= 10 else (None, None, None, None)
        med = float(np.median(da))
        out[r] = {"n": int(len(da)), "dist_atr_med": r4(med), "dist_atr_p90": r4(np.quantile(da, 0.9)),
                  "dist_pct_med": r4(np.median(dp)), "dist_pct_p90": r4(np.quantile(dp, 0.9)),
                  "hit_rate": r4(np.mean(R["hit"])), "n_break": int(len(ft)), "ft_rate": r4(ft.mean()) if len(ft) else None,
                  "placebo_rate": r4(pl.mean()) if len(pl) else None, "diff": r4(est), "ci": [r4(lo), r4(hi)], "p": r4(p),
                  "practical": bool(cfg["band"][0] <= med <= cfg["band"][1] and np.quantile(dp, 0.9) <= cfg["win"])}
    return out


def choose(summ, mode):
    cfg = MODES[mode]
    ok = [r for r, s in summ.items() if s.get("practical")]
    if ok:
        return max(ok, key=lambda r: (summ[r]["diff"] if summ[r].get("diff") is not None else -9)), "practical"
    mid = sum(cfg["band"]) / 2
    have = [r for r, s in summ.items() if s.get("n")]
    return min(have, key=lambda r: abs(summ[r]["dist_atr_med"] - mid)), "closest_to_band"


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    st = json.load(open(STATS, encoding="utf-8")) if os.path.exists(STATS) else {}
    cal = json.load(open(os.path.join(OUT, "intraday_calibration.json"), encoding="utf-8"))
    E.INTRA["m"] = cal["m"]
    res = {"modes": {}, "intra_m": cal["m"]}
    # 日 K：短線、波段
    tw = load_twii_daily()
    o, h, l, c = (tw[k].values.astype(float) for k in ("o", "h", "l", "c"))
    months = tw.date.str[:7].values
    start = int(np.searchsorted(tw.date.values, "2005-01-01"))
    for mode in ("short", "swing"):
        deg = MODES[mode]["deg"]
        piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
        rec = run_series(o, h, l, c, months, deg, mode, piv, start, trend_at)
        res["modes"][mode] = {"data": "加權日 K 2005～", "cands": summarize(rec, mode)}
        print(mode, json.dumps(res["modes"][mode]["cands"], ensure_ascii=False))
    # 60 分 K：超短線
    for sym in ("TWII", "TX"):
        try:
            bars = load_intraday(sym, 60)
        except FileNotFoundError:
            continue
        o, h, l, c, ts = arrays(bars)
        months = np.array([FD.tw_dt(x).strftime("%Y-%m-%d") if sym == "TX" else FD.tw_dt(x).strftime("%Y-%m") for x in ts])
        th = np.maximum(E.INTRA["floor"], E.INTRA["m"] * np.nan_to_num(E.atr_pct_median(h, l, c), nan=E.INTRA["floor"]))
        piv = E.zigzag(h, l, th)
        rec = run_series(o, h, l, c, months, "intra", "ultra", piv, 60, lambda c_, t_: 0)
        key = "ultra" if sym == "TWII" else "ultra_tx"
        res["modes"][key] = {"data": "加權 60 分 K（Yahoo 2 年）" if sym == "TWII" else "台指期 60 分 K（期交所 30 天，只報告；bootstrap 用日分組）",
                             "cands": summarize(rec, "ultra")}
        print(key, json.dumps(res["modes"][key]["cands"], ensure_ascii=False))
    pv = {f"{m}:{r}": s.get("p") for m in ("ultra", "short", "swing") if m in res["modes"] for r, s in res["modes"][m]["cands"].items()}
    q = bh(pv)
    for m in ("ultra", "short", "swing"):
        if m not in res["modes"]:
            continue
        cs = res["modes"][m]["cands"]
        for r in cs:
            cs[r]["q"] = r4(q.get(f"{m}:{r}"))
            cs[r]["sig"] = bool(cs[r].get("q") is not None and cs[r]["q"] < 0.10 and (cs[r]["ci"][0] or 0) > 0)
        rule, how = choose(cs, m)
        res["modes"][m]["rule"], res["modes"][m]["how"] = rule, how
        res["modes"][m]["sig"] = cs[rule]["sig"]
        print(m, "→", rule, how, "顯著" if cs[rule]["sig"] else "不顯著")
    json.dump(res, open(os.path.join(OUT, "keylevel.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
