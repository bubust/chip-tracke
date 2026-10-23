"""B81 R-A 建議持股規則回測（PLAN-B81 §3；門檻事先定好）
- 加權日 K 2000-01-04～；訊號在 t 收盤算（只用 ci≤t 的轉折），套用 t→t+1 收盤報酬；現金 0；不含股利
- S0 現行：日 K（小級）＋週 K（中級）方向（service._ladder：轉折點方向，沒有就用暫定轉折）；都上＝100%、都下＝0%、其他＝50%
- 候選：S1 收盤 > 200 日均線、S2 月線（MA20）今天 > 昨天、S3 收盤 > 60 日均線（100%／0%）
- 網站實際版（基準 30～50%：上 45、不一致 40、下 35）另報
- 成本：部位每變動 1 單位扣 0.1%；對照＝同平均部位的固定持股
- 檢定：Sharpe 差，平穩區塊 bootstrap（平均區塊 20、60 天各 2,000 次，取保守的）；4 個一起 BH
- ✅：Sharpe 差 ≥ +0.15、區間下限 > 0、q < 0.05、最大回撤 ≤ 對照 0.8 倍、四個時期 ≥3 個 Sharpe 差為正
用法：python research/b81/run_advice.py"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C  # noqa: E402
import pit  # noqa: E402
from run_setups import ladder_dir  # noqa: E402
from wave import keylevel as KL  # noqa: E402
from wave import service as S  # noqa: E402

COST = 0.001
MIN_DIFF = 0.15
DD_RATIO = 0.8
OUT = os.path.join(HERE, "results")


def dirs_series(D):
    st = S.stats()
    h, l, c = D["h"], D["l"], D["c"]
    n = len(c)
    d1, dw = np.zeros(n, int), np.zeros(n, int)
    for t in range(250, n):
        an = pit.an_at(D, t)
        a = float(D["atr"][t])
        for mode, deg, arr in (("short", "small", d1), ("swing", "mid", dw)):
            cands = KL.candidates(an[deg], h, l, c, t, a, price=float(c[t]), k=3, look=S.KEY_LOOK[mode])
            key = S._key_out(cands, mode, float(c[t]), a, st)
            arr[t] = ladder_dir(key, an[deg])
    return d1, dw


def ma(c, n):
    out = np.full(len(c), np.nan)
    cs = np.cumsum(np.r_[0.0, c])
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def strat_returns(c, w):
    r = np.r_[c[1:] / c[:-1] - 1, np.nan]                    # r[t]＝t→t+1
    dw = np.abs(np.diff(np.r_[w[0], w]))
    ret = w * r - COST * dw
    return ret[:-1]


def metrics(ret):
    ret = ret[np.isfinite(ret)]
    eq = np.cumprod(1 + ret)
    yrs = len(ret) / 252
    cagr = eq[-1] ** (1 / yrs) - 1 if yrs > 0 else float("nan")
    vol = float(np.std(ret, ddof=1) * math.sqrt(252))
    sh = float(np.mean(ret) / np.std(ret, ddof=1) * math.sqrt(252)) if np.std(ret) > 0 else float("nan")
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1))
    return {"cagr": round(cagr, 4), "vol": round(vol, 4), "sharpe": round(sh, 3), "mdd": round(mdd, 4),
            "calmar": round(cagr / abs(mdd), 3) if mdd < 0 else None}


def sharpe(x):
    sd = np.std(x, ddof=1)
    return float(np.mean(x) / sd * math.sqrt(252)) if sd > 0 else float("nan")


def stat_boot(a, b, L, rng, n=C.N_BOOT):
    """平穩區塊 bootstrap（Politis–Romano，平均區塊 L）：Sharpe(a) − Sharpe(b)"""
    T = len(a)
    p = 1.0 / L
    ar = np.arange(T)
    out = np.empty(n)
    for i in range(n):
        new = rng.random(T) < p
        new[0] = True
        start = rng.integers(T, size=T)
        k0 = np.maximum.accumulate(np.where(new, ar, 0))     # 每一根所在區塊的起點位置
        idx = (start[k0] + ar - k0) % T
        out[i] = sharpe(a[idx]) - sharpe(b[idx])
    return out


def main():
    rng = np.random.default_rng(C.SEED)
    D = pit.prep_daily(pit.load_twii_daily())
    c = D["c"]
    n = len(c)
    print("算日 K／週 K 方向…", flush=True)
    d1, dw = dirs_series(D)
    t0 = 250
    m200, m60, m20 = ma(c, 200), ma(c, 60), ma(c, 20)
    sig = {}
    both_up = (d1 == 1) & (dw == 1)
    both_dn = (d1 == -1) & (dw == -1)
    sig["S0"] = np.where(both_up, 1.0, np.where(both_dn, 0.0, 0.5))
    sig["S1"] = np.where(c > m200, 1.0, 0.0)
    sig["S2"] = np.where(np.r_[False, m20[1:] > m20[:-1]], 1.0, 0.0)
    sig["S3"] = np.where(c > m60, 1.0, 0.0)
    site = np.where(both_up, 0.45, np.where(both_dn, 0.35, 0.40))
    years = D["years"][t0:n - 1]
    res = {"period": f"{D['dates'][t0]}～{D['dates'][-1]}", "n_days": int(n - 1 - t0), "cost": COST, "rows": {}}
    pv = {}
    for k, w in sig.items():
        w = w[t0:]
        ret = strat_returns(c[t0:], w)
        wbar = float(np.mean(w[:-1]))
        ctrl = strat_returns(c[t0:], np.full(len(w), wbar))
        m_s, m_c = metrics(ret), metrics(ctrl)
        diff = m_s["sharpe"] - m_c["sharpe"]
        cis = {}
        for L in (20, 60):
            bt = stat_boot(ret, ctrl, L, rng)
            cis[L] = {"lo": float(np.percentile(bt, 2.5)), "hi": float(np.percentile(bt, 97.5)), "p": float((np.sum(bt <= 0) + 1) / (len(bt) + 1))}
        cons = min(cis.values(), key=lambda x: x["lo"])
        per = {}
        for a, b in C.PERIODS_D1:
            msk = (years >= int(a)) & (years <= int(b))
            if msk.sum() > 100:
                per[f"{a}–{b[2:]}"] = round(sharpe(ret[msk]) - sharpe(ctrl[msk]), 3)
        pv[k] = cons["p"]
        res["rows"][k] = {"avg_w": round(wbar, 3), "strat": m_s, "ctrl": m_c, "diff": round(diff, 3), "ci20": cis[20], "ci60": cis[60],
                          "ci": [cons["lo"], cons["hi"]], "p": cons["p"], "periods": per,
                          "dist": {"up": round(float(np.mean(w == 1.0)), 3), "down": round(float(np.mean(w == 0.0)), 3)}}
        print(k, json.dumps(res["rows"][k], ensure_ascii=False), flush=True)
    q = C.bh(pv)
    for k, r in res["rows"].items():
        r["q"] = q.get(k)
        per = list(r["periods"].values())
        r["pass"] = bool(r["diff"] >= MIN_DIFF and r["ci"][0] > 0 and r["q"] is not None and r["q"] < 0.05
                         and r["strat"]["mdd"] >= DD_RATIO * r["ctrl"]["mdd"] and sum(1 for v in per if v > 0) >= 3)
    # 網站實際版（只報告）
    w = site[t0:]
    ret = strat_returns(c[t0:], w)
    ctrl = strat_returns(c[t0:], np.full(len(w), float(np.mean(w[:-1]))))
    res["site"] = {"strat": metrics(ret), "ctrl": metrics(ctrl)}
    # 各方向之後 20 天報酬與波動（描述）
    fwd = np.full(n, np.nan)
    fwd[:-20] = c[20:] / c[:-20] - 1
    desc = {}
    for nm, msk in (("都上", both_up), ("都下", both_dn), ("不一致", ~(both_up | both_dn))):
        mm = msk.copy()
        mm[:t0] = False
        x = fwd[mm]
        x = x[np.isfinite(x)]
        desc[nm] = {"days": int(mm.sum()), "fwd20_mean": round(float(np.mean(x)), 4), "fwd20_sd": round(float(np.std(x)), 4)}
    res["desc_S0"] = desc
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, "advice.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, r in res["rows"].items():
        print(k, "pass", r["pass"], "diff", r["diff"], "ci", [round(x, 3) for x in r["ci"]], "q", r["q"], "mdd", r["strat"]["mdd"], r["ctrl"]["mdd"])
    print("網站版", res["site"])
    print("S0 描述", desc)


if __name__ == "__main__":
    main()
