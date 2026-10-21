"""B75 R-F（PLAN-B75 §6.1）：期貨＋籌碼對加權的預測力。判準事先寫在計畫，這裡只照做。
樣本內 2017-05-16～2021-12-31、樣本外 2022-01-01 起；月份 block bootstrap 2,000 次；全部檢定一起 BH（q < 0.10）
- 迴歸型（夜盤、費半 → 加權當天 gap／r1）：樣本內 OLS β → 樣本外 R²（bootstrap CI 下限 > 0）、樣本內外 β 同號、
  樣本外每年 β 至少 3/5 年同號、樣本外 R² ≥ 0.02
- 收盤後公布的（a 隔天殘差、b 隔天開盤起 5／20 天）：樣本內三分位切點，最高組−最低組；樣本外 CI 不含 0、同號、每年 ≥3/5 同號
- 網站用的 β：2022 以後重估；polarity＝樣本內組差（或 β）的正負號
輸出 results/futures.json、wave/stats.json 的 futures 區塊（另外 keylevel、intraday 也併進去）、REPORT.md"""
import json
import os
import sys

import numpy as np
import pandas as pd

from common import FD, F, OUT, STATS, WDATA, DATA, bh, block_boot_events, load_twii_daily, r4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from wave import composite as C  # noqa: E402

IS0, IS1, OOS0 = "2017-05-16", "2021-12-31", "2022-01-01"
YEARS = ("2022", "2023", "2024", "2025", "2026")


def load():
    tw = load_twii_daily()
    fd = FD.select_continuous(pd.read_csv(os.path.join(DATA, "fut_tx_daily.csv"), dtype={"contract_date": str}))
    inst = pd.read_csv(os.path.join(WDATA, "fm_inst.csv"))
    fut = pd.read_csv(os.path.join(WDATA, "fm_fut.csv"))
    mg = pd.read_csv(os.path.join(WDATA, "fm_margin.csv"))
    chips = F.chips_from_finmind(inst, fut, mg)
    fch = FD.fut_chips_from_finmind(pd.read_csv(os.path.join(DATA, "fut_mtx_daily.csv"), dtype={"contract_date": str}),
                                    pd.read_csv(os.path.join(DATA, "fm_fut_mtx.csv")), pd.read_csv(os.path.join(WDATA, "fm_opt.csv")))
    sox = pd.read_csv(os.path.join(WDATA, "SOX.csv"))
    return C.build(tw, fd, chips, fch, sox), fd


def ols(x, y):
    b = np.cov(x, y, ddof=0)[0, 1] / np.var(x)
    return float(y.mean() - b * x.mean()), float(b)


def reg_test(df, xcols, ycol):
    """樣本內 OLS（可多變數）→ 樣本外 R²＋月份 bootstrap；每年 β 同號比例"""
    d = df.dropna(subset=list(xcols) + [ycol])
    isd, oos = d[(d.date >= IS0) & (d.date <= IS1)], d[d.date >= OOS0]
    if len(isd) < 200 or len(oos) < 200:
        return {"n_is": len(isd), "n_oos": len(oos), "pass": False, "note": "樣本不夠"}
    Xi = np.c_[np.ones(len(isd)), isd[list(xcols)].values]
    bi = np.linalg.lstsq(Xi, isd[ycol].values, rcond=None)[0]
    Xo = np.c_[np.ones(len(oos)), oos[list(xcols)].values]
    yo = oos[ycol].values
    pred = Xo @ bi
    months = oos.date.str[:7].values

    def r2(ii):
        if len(ii) < 30:
            return None
        e = yo[ii] - pred[ii]
        return 1 - np.sum(e ** 2) / np.sum((yo[ii] - yo[ii].mean()) ** 2)
    est, lo, hi, p = block_boot_events(months, r2)
    bo = np.linalg.lstsq(Xo, yo, rcond=None)[0]
    yrs = []
    for y in YEARS:
        s = oos[oos.date.str[:4] == y]
        if len(s) > 30:
            by = np.linalg.lstsq(np.c_[np.ones(len(s)), s[list(xcols)].values], s[ycol].values, rcond=None)[0]
            yrs.append(bool(np.sign(by[1]) == np.sign(bi[1])))
    resid = yo - Xo @ bo
    out = {"n_is": len(isd), "n_oos": len(oos), "is_beta": [r4(v) for v in bi], "oos_beta": [r4(v) for v in bo],
           "oos_r2": r4(est), "ci": [r4(lo), r4(hi)], "p": r4(p), "years_same": f"{sum(yrs)}/{len(yrs)}",
           "same_sign": bool(np.sign(bi[1]) == np.sign(bo[1])), "alpha": r4(bo[0]), "beta": r4(bo[1]),
           "resid_sd": r4(float(np.std(resid))), "polarity": int(np.sign(bi[1]) or 1), "kind": "reg"}
    out["crit"] = bool(est is not None and est >= 0.02 and lo is not None and lo > 0 and out["same_sign"] and sum(yrs) >= 3)
    return out


def tercile_test(df, xcol, ycol):
    d = df.dropna(subset=[xcol, ycol])
    isd, oos = d[(d.date >= IS0) & (d.date <= IS1)], d[d.date >= OOS0]
    if len(isd) < 200 or len(oos) < 150:
        return {"n_is": len(isd), "n_oos": len(oos), "pass": False, "note": "樣本不夠", "kind": "terc"}
    e0, e1 = np.quantile(isd[xcol].values, [1 / 3, 2 / 3])

    def diff_of(s):
        hi, lo = s[s[xcol] > e1][ycol], s[s[xcol] <= e0][ycol]
        return (hi.mean() - lo.mean()) if len(hi) > 10 and len(lo) > 10 else None
    is_diff = diff_of(isd)
    x, y = oos[xcol].values, oos[ycol].values
    grp = np.where(x > e1, 1, np.where(x <= e0, -1, 0))
    months = oos.date.str[:7].values

    def stat(ii):
        g, yy = grp[ii], y[ii]
        if (g == 1).sum() < 10 or (g == -1).sum() < 10:
            return None
        return yy[g == 1].mean() - yy[g == -1].mean()
    est, lo, hi, p = block_boot_events(months, stat)
    yrs = []
    for yv in YEARS:
        s = oos[oos.date.str[:4] == yv]
        dv = diff_of(s) if len(s) > 60 else None
        if dv is not None and is_diff is not None:
            yrs.append(bool(np.sign(dv) == np.sign(is_diff)))
    out = {"n_is": len(isd), "n_oos": len(oos), "edges": [r4(e0), r4(e1)], "is_diff": r4(is_diff), "oos_diff": r4(est),
           "ci": [r4(lo), r4(hi)], "p": r4(p), "years_same": f"{sum(yrs)}/{len(yrs)}",
           "same_sign": bool(is_diff is not None and est is not None and np.sign(is_diff) == np.sign(est)),
           "polarity": int(np.sign(is_diff) or 1) if is_diff is not None else 1, "kind": "terc"}
    out["crit"] = bool(lo is not None and (lo > 0 or hi < 0) and out["same_sign"] and sum(yrs) >= 3)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    df, fd = load()
    # (a) 隔天殘差：樣本內 r1 對夜盤迴歸 → r1_next 扣掉 night_ret_next 解釋的部分
    d0 = df.dropna(subset=["night_ret", "r1"])
    a0, b0 = ols(d0[(d0.date >= IS0) & (d0.date <= IS1)].night_ret.values, d0[(d0.date >= IS0) & (d0.date <= IS1)].r1.values)
    df["res_next"] = df["r1_next"] - (a0 + b0 * df["night_ret_next"])
    T = {}
    T["night_ret:gap"] = reg_test(df, ["night_ret"], "gap")
    T["night_ret:r1"] = reg_test(df, ["night_ret"], "r1")
    T["sox_ret1:r1"] = reg_test(df, ["sox_ret1"], "r1")
    T["sox_ret1:gap"] = reg_test(df, ["sox_ret1"], "gap")
    # 增量：費半＋夜盤 vs 只有費半（樣本外 R² 差）
    inc = {}
    for y in ("gap", "r1"):
        a = reg_test(df, ["sox_ret1", "night_ret"], y)
        b = reg_test(df, ["sox_ret1"], y)
        inc[y] = {"both_r2": a.get("oos_r2"), "sox_r2": b.get("oos_r2"),
                  "incr_r2": r4((a.get("oos_r2") or 0) - (b.get("oos_r2") or 0))}
    for k in ("fut_chg1", "opt_chg1", "retail_chg1", "f_net"):
        T[f"{k}:res_next"] = tercile_test(df, k, "res_next")
    for k in ("basis_z", "basis_d5", "opt_z", "retail", "margin_chg5"):
        for y in ("fwdo5", "fwdo20"):
            T[f"{k}:{y}"] = tercile_test(df, k, y)
    q = bh({k: v.get("p") for k, v in T.items()})
    for k, v in T.items():
        v["q"] = r4(q.get(k))
        v["pass"] = bool(v.get("crit") and v["q"] is not None and v["q"] < 0.10)
    res = {"generated": pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y-%m-%d %H:%M"), "is": f"{IS0}～{IS1}",
           "oos": f"{OOS0}～{df.date.iloc[-1]}", "tests": T, "incremental": inc, "night_r1_is": {"alpha": r4(a0), "beta": r4(b0)},
           "n_tests": len(T)}
    json.dump(res, open(os.path.join(OUT, "futures.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in T.items():
        print(f"{k:22s} {'✅' if v['pass'] else '△'} oos={v.get('oos_r2', v.get('oos_diff'))} ci={v.get('ci')} q={v.get('q')} yrs={v.get('years_same')} n={v.get('n_oos')}")
    print("增量", inc)
    return res


def site_block(res: dict) -> dict:
    """網站讀的 stats.futures：每個指標的回測結果（pass、polarity、edges／β）、每個時間用哪個檢定"""
    T = res["tests"]
    fac = {}
    pick = {"night_ret": {"next": "night_ret:r1", "open": "night_ret:gap"}, "sox_ret1": {"next": "sox_ret1:r1", "open": "sox_ret1:gap"},
            "fut_chg1": {"next": "fut_chg1:res_next"}, "opt_chg1": {"next": "opt_chg1:res_next"},
            "retail_chg1": {"next": "retail_chg1:res_next"}, "f_net": {"next": "f_net:res_next"},
            "basis_z": {"w2": "basis_z:fwdo5", "m3": "basis_z:fwdo20"}, "basis_d5": {"w2": "basis_d5:fwdo5", "m3": "basis_d5:fwdo20"},
            "opt_z": {"w2": "opt_z:fwdo5", "m3": "opt_z:fwdo20"}, "retail": {"w2": "retail:fwdo5", "m3": "retail:fwdo20"},
            "margin_chg5": {"w2": "margin_chg5:fwdo5", "m3": "margin_chg5:fwdo20"}}
    keep = ("pass", "polarity", "edges", "kind", "alpha", "beta", "resid_sd", "oos_r2", "oos_diff", "ci", "q", "years_same", "n_oos")
    for k, hz in pick.items():
        fac[k] = {h: {kk: T[t].get(kk) for kk in keep if kk in T[t]} for h, t in hz.items() if t in T}
    return {"generated": res["generated"], "is": res["is"], "oos": res["oos"], "factors": fac, "incremental": res["incremental"],
            "n_tests": res["n_tests"]}


if __name__ == "__main__":
    r = main()
    st = json.load(open(STATS, encoding="utf-8")) if os.path.exists(STATS) else {}
    st["futures"] = site_block(r)
    for nm, key in (("keylevel.json", "keylevel"), ("intraday_calibration.json", "intraday")):
        p = os.path.join(OUT, nm)
        if os.path.exists(p):
            x = json.load(open(p, encoding="utf-8"))
            if key == "intraday":
                x = {k: x[k] for k in ("m", "floor", "target_days", "cal_period") if k in x} | {"grid": x.get("grid")}
            st[key] = x
    json.dump(st, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("stats.json 已更新")
