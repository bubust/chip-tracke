"""B79 研究：她的「轉浪關卡」在加權 60 分 K 上有沒有比隨機好（PLAN-B79 §5）。
資料：Yahoo ^TWII 60 分 K（近 730 天）＋日 K（2000 起，給「日 K 這一浪的起點」）。逐根 K 棒、只用當時以前的資料跑 wave/nest.build。
事件（每個「起點＋極值」只算第一次）：
  E1 第二關：逆著大段走時，收盤第一次站上（跌破）整段的 0.382 → 之後先到 0.5（確認轉浪）還是先回到極值（還有第 5 段）
  E2 第三關：第一次碰到 0.5 → 之後先回到極值（她：逃命波、開始下一段主跌）還是先過 0.786（不是逃命波）
  E3 主要數法：「大段還在走」vs「大段走完」→ 之後 20 根 K 棒順著大段方向的比例
比較：① 隨機漫步的理論機率（只看距離：到目標的距離 ÷ 兩邊距離和）② 同一份 60 分 K 報酬打亂順序（沒有任何波浪結構）跑同一套程式
用法：python research/wave/b79_nest_research.py（會下載資料；結果寫 research/wave/b79_nest_results.json）"""
import json
import os
import sys
import time

import httpx
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from wave import engine as E, futdata as FD, intraday as I, nest as N  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
H1, H2, H3 = 50, 80, 20      # E1／E2 往後看幾根、E3 往後幾根


def yahoo_60m() -> pd.DataFrame:
    j = httpx.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII", params={"interval": "60m", "range": "730d"},
                  headers=UA, timeout=60).json()
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": r["timestamp"], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"]}).dropna()
    return df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)


def daily_counts(dd: pd.DataFrame, since: str = "") -> dict:
    """每個交易日收盤後的小級主要劇本（給隔天的分 K 用；只算 since 以後）"""
    o, h, l, c = (dd[k].values.astype(float) for k in ("o", "h", "l", "c"))
    piv = E.zigzag(h, l, E.thresholds(h, l, c, "small"))
    out = {}
    for t in range(260, len(c)):
        if str(dd.date.iloc[t]) < since:
            continue
        tr = 1 if c[t] > np.mean(c[max(0, t - 239):t + 1]) else -1
        out[str(dd.date.iloc[t])] = E.analyze(o, h, l, c, "small", t=t, trend=tr, piv=piv).get("primary")
    return out


def run(df: pd.DataFrame, dcnt: dict, ddates: list, use_daily: bool = True) -> dict:
    h, l, c = (df[k].values.astype(float) for k in ("h", "l", "c"))
    ts = df.ts.values.astype(int)
    th = I.theta(h, l, c, E.INTRA)
    piv = E.zigzag(h, l, th)
    days = [FD.tw_dt(int(x)).date() for x in ts]
    dstr = [d.isoformat() for d in days]
    dkeys = sorted(dcnt)
    e1, e2, e3 = [], [], []
    seen1, seen2 = set(), set()
    import bisect
    for t in range(120, len(c) - 1):
        conf, tent = E.state_at(piv, h, l, t)
        an = {"pivots": conf, "tentative": tent}
        k = bisect.bisect_left(dkeys, dstr[t]) - 1           # 前一個交易日收盤的日 K 劇本（不偷看今天）
        dc = dcnt[dkeys[k]] if (use_daily and k >= 0) else None
        try:
            out = N.build(an, list(ts[:t + 1]), float(c[t]), "60 分", daily_cnt=dc, daily_dates=ddates,
                          tdate=lambda i: days[i], tlabel=lambda i: dstr[i])
        except Exception as ex:  # noqa: BLE001
            print("build 失敗", t, ex)
            continue
        if not out.get("ok"):
            continue
        d0, ep = out["dir"], out["extreme"]["p"]
        f = {float(k_): v for k_, v in out["fib"].items()}
        key = (out["anchor"]["i"], round(ep, 2))
        span = abs(out["anchor"]["p"] - ep)
        lvl = lambda r: ep - d0 * r * span                    # noqa: E731
        fut_h, fut_l = h[t + 1:], l[t + 1:]
        hit_up = lambda lv, n: next((j for j in range(min(n, len(fut_h))) if (fut_h[j] >= lv if d0 < 0 else fut_l[j] <= lv)), None)  # noqa: E731
        hit_ext = lambda n: next((j for j in range(min(n, len(fut_h))) if (fut_l[j] < ep if d0 < 0 else fut_h[j] > ep)), None)  # noqa: E731
        counter = out["cur_dir"] != d0
        # E1：逆著大段、收盤第一次越過 0.382
        if counter and out["evidence"]["f382"] and key not in seen1:
            seen1.add(key)
            a, b = hit_up(lvl(0.5), H1), hit_ext(H1)
            res = None if a is None and b is None else ("target" if b is None or (a is not None and a < b) else "ext")
            p_rw = abs(c[t] - ep) / max(abs(lvl(0.5) - ep), 1e-9)
            e1.append({"t": int(ts[t]), "res": res, "p_rw": float(min(1.0, p_rw)), "trend": bool(out["evidence"]["trend"]),
                       "prim_trend": bool((out["primary"] or {}).get("with_trend"))})
        # E2：逆著大段、第一次碰到 0.5
        if counter and key not in seen2 and ((h[t] >= f[0.5]) if d0 < 0 else (l[t] <= f[0.5])):
            seen2.add(key)
            a, b = hit_ext(H2), hit_up(lvl(0.786), H2)
            res = None if a is None and b is None else ("ext" if b is None or (a is not None and a < b) else "deep")
            p_rw = abs(lvl(0.786) - c[t]) / max(abs(lvl(0.786) - ep), 1e-9)
            e2.append({"t": int(ts[t]), "res": res, "p_rw": float(min(1.0, max(0.0, p_rw)))})
        # E3：主要數法說「大段還在走」或「走完了」 → 之後 H3 根順著大段方向的比例（每 5 根取一次，減少重疊）
        if t % 5 == 0 and out["primary"] and t + H3 < len(c):
            e3.append({"with": bool(out["primary"]["with_trend"]), "cont": bool((c[t + H3] - c[t]) * d0 > 0)})
    return {"e1": e1, "e2": e2, "e3": e3, "n_bars": len(c), "n_piv": len(piv)}


def summary(r: dict) -> dict:
    def rate(lst, ok):
        x = [e for e in lst if e["res"] is not None]
        if not x:
            return {"n": 0}
        k = sum(1 for e in x if e["res"] == ok)
        return {"n": len(x), "rate": round(k / len(x), 4), "rw": round(float(np.mean([e["p_rw"] for e in x])), 4),
                "none": sum(1 for e in lst if e["res"] is None)}
    s = {"E1_站上0382後先到0.5": rate(r["e1"], "target"),
         "E1_同時越過趨勢線": rate([e for e in r["e1"] if e["trend"]], "target"),
         "E1_沒越過趨勢線": rate([e for e in r["e1"] if not e["trend"]], "target"),
         "E2_碰0.5後先回極值": rate(r["e2"], "ext")}
    for w in (True, False):
        x = [e for e in r["e3"] if e["with"] == w]
        s[f"E3_主要數法{'大段還在走' if w else '大段走完'}_之後順大段比例"] = {"n": len(x), "rate": round(np.mean([e["cont"] for e in x]), 4) if x else None}
    return s


def shuffled(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = df.c.values.astype(float)
    lr = np.diff(np.log(c))
    idx = rng.permutation(len(lr))
    cc = c[0] * np.exp(np.concatenate([[0], np.cumsum(lr[idx])]))
    hr = np.concatenate([[df.h.iloc[0] / c[0]], (df.h.values[1:] / c[1:])[idx]])
    lr_ = np.concatenate([[df.l.iloc[0] / c[0]], (df.l.values[1:] / c[1:])[idx]])
    return pd.DataFrame({"ts": df.ts.values, "o": cc, "h": cc * hr, "l": cc * lr_, "c": cc})


def main():
    import fetch as FE
    t0 = time.time()
    df = yahoo_60m()
    dd = FE.yahoo("^TWII").dropna(subset=["o", "h", "l", "c"])
    dd = dd[(dd.h >= dd.l) & (dd.c > 0)].reset_index(drop=True)
    print("60m", len(df), FD.tw_dt(int(df.ts.iloc[0])), FD.tw_dt(int(df.ts.iloc[-1])), "daily", len(dd))
    dcnt = daily_counts(dd, since=(FD.tw_dt(int(df.ts.iloc[0])) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))
    ddates = list(dd.date.astype(str))
    res = {"real": run(df, dcnt, ddates), "real_nodaily": run(df, dcnt, ddates, use_daily=False)}
    for s in (1, 2, 3):
        res[f"null{s}"] = run(shuffled(df, s), dcnt, ddates, use_daily=False)
    out = {k: summary(v) for k, v in res.items()}
    out["meta"] = {"bars": len(df), "from": str(FD.tw_dt(int(df.ts.iloc[0]))), "to": str(FD.tw_dt(int(df.ts.iloc[-1]))),
                   "secs": round(time.time() - t0)}
    with open(os.path.join(HERE, "b79_nest_results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ex = [e for e in res["real"]["e1"]][-8:]
    print("最近的 E1 事件", [(str(FD.tw_dt(e["t"]))[:16], e["res"], e["trend"]) for e in ex])


if __name__ == "__main__":
    main()
