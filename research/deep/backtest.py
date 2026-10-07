"""
深度分析綜合評價的回測（PLAN-DEEP2 §3；產生 deep_verdict.py 的 BUCKET_STATS／ODDS 常數）

用法：python research/deep/backtest.py PD_CSV_GZ [OUT_JSON]
  PD_CSV_GZ：date,stock_id,open,high,low,close,volume（正式站 cache.db price_daily 匯出，volume 單位：張）

方法：
- 每檔從第 130 根起每 5 天取樣（4 碼普通股、至少 300 根），只用 t 以前（含）的資料算因子（deep_verdict.tech_series）
- 母體：main＝20 日均量 ≥300 張且股價 ≥10；low＝20 日均量 30～300 張且股價 ≥10
- x20＝未來 20 日報酬 − 同一天同母體所有樣本的平均（去掉大盤方向）；mdd＝之後 20 天最低價相對 t 收盤的跌幅
- 穩定度：前後兩段（2025／2026）分開算、逐月 強勢−弱勢 差
- 機率表：每個母體隨機 8,000 筆，用 price_levels.compute_levels（只給 t 以前資料）算目標與停損，
  40 天內先碰到目標（最高 ≥ 目標）或先收盤跌破停損，依 技術分類 × 風險報酬比（<0.5／0.5～<1／≥1）統計；
  另算平均每筆結果（先到目標賣在目標、先破停損賣在那天收盤、都沒有賣在第 40 天收盤；未扣成本）
"""
import json, os, sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from deep_verdict import tech_series, tech_raw, bucket_of   # noqa: E402

G = None


def load(path):
    d = pd.read_csv(path, dtype={"stock_id": str, "date": str})
    d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(["stock_id", "date"])
    return {sid: g.reset_index(drop=True) for sid, g in d.groupby("stock_id")
            if sid[:1].isdigit() and len(sid) == 4 and len(g) >= 300}


def samples_of(item):
    sid, g = item
    ts = tech_series(g)
    c, lo = g.close.values.astype(float), g.low.values.astype(float)
    out = []
    for t in range(130, len(g) - 21, 5):
        row = ts.iloc[t]
        v20, px = row["vol20"], c[t]
        if px < 10 or not v20 or np.isnan(v20) or v20 < 30:
            continue
        raw, _ = tech_raw(row)
        out.append({"sid": sid, "t": t, "date": g.date.iloc[t], "pop": "main" if v20 >= 300 else "low",
                    "raw": raw, "bucket": bucket_of(raw), "f20": c[t + 20] / px - 1,
                    "mdd": lo[t + 1:t + 21].min() / px - 1})
    return out


def init(path):
    global G
    G = load(path)


def odds_work(rows):
    from price_levels import compute_levels
    out = []
    for sid, t, bucket in rows:
        g = G[sid]
        lv = compute_levels(g.iloc[:t + 1])
        if lv.get("error"):
            continue
        p, st, tg = lv.get("price"), (lv.get("stop") or {}).get("price"), lv.get("target")
        if not (p and st and tg) or st >= p or tg <= p:
            continue
        h, c = g.high.values[t + 1:t + 41], g.close.values[t + 1:t + 41]
        ht = int(np.argmax(h >= tg)) if (h >= tg).any() else 999
        hs = int(np.argmax(c < st)) if (c < st).any() else 999
        # 這筆的實際結果：先到目標＝賣在目標價；先跌破停損＝賣在跌破那天收盤；都沒有＝第 40 天收盤
        ret = tg / p - 1 if ht < hs else (c[hs] / p - 1 if hs < ht else c[len(c) - 1] / p - 1)
        out.append({"bucket": bucket, "rr": (tg - p) / (p - st), "win": ht < hs, "lose": hs < ht, "ret": ret})
    return out


def stats(a):
    return {"x20": round(a.x20.mean() * 100, 2), "med": round(a.x20.median() * 100, 2),
            "up": round((a.f20 > 0).mean() * 100, 1), "mdd": round(a.mdd.mean() * 100, 1), "n": int(len(a))}


if __name__ == "__main__":
    path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "backtest_result.json")
    with Pool(8, initializer=init, initargs=(path,)) as pool:
        groups = list(load(path).items())
        S = pd.DataFrame([r for part in pool.map(samples_of, groups, chunksize=16) for r in part])
        S["x20"] = S.f20 - S.groupby(["pop", "date"]).f20.transform("mean")
        res = {"period": f"{S.date.min()}～{S.date.max()}", "stocks": int(S.sid.nunique()), "buckets": {}, "halves": {},
               "monthly_spread": {}, "odds": {}}
        for pop in ("main", "low"):
            P = S[S["pop"] == pop]
            res["buckets"][pop] = {b: stats(P[P.bucket == b]) for b in ("strong", "neutral", "weak")}
            res["halves"][pop] = {h: {b: stats(Q[Q.bucket == b]) for b in ("strong", "neutral", "weak")}
                                  for h, Q in (("2025", P[P.date < "20260101"]), ("2026", P[P.date >= "20260101"]))}
            m = P.assign(ym=P.date.str[:6]).groupby(["ym", "bucket"]).x20.mean().unstack()
            sp = (m["strong"] - m["weak"]) * 100
            res["monthly_spread"][pop] = {"months": int(sp.notna().sum()), "strong_beats_weak": int((sp > 0).sum()),
                                          "by_month": {k: round(v, 2) for k, v in sp.dropna().items()}}
            smp = P.sample(min(8000, len(P)), random_state=7)
            rows = list(zip(smp.sid, smp.t, smp.bucket))
            R = pd.DataFrame([r for part in pool.map(odds_work, [rows[i::16] for i in range(16)]) for r in part])
            R["band"] = pd.cut(R.rr, [0, .5, 1, 1e9], labels=["lo", "mid", "hi"], right=False)
            tab = {}
            for b in ("weak", "neutral", "strong"):
                tab[b] = {}
                for band in ("lo", "mid", "hi"):
                    a = R[(R.bucket == b) & (R.band == band)]
                    tab[b][band] = ([round(a.win.mean() * 100), round(a.lose.mean() * 100), int(len(a)),
                                     round(a.ret.mean() * 100, 2)] if len(a) else [0, 0, 0, 0.0])
            res["odds"][pop] = tab
    json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("period", "stocks", "buckets", "odds")}, ensure_ascii=False, indent=1))
    for pop in ("main", "low"):
        print(pop, "halves", json.dumps(res["halves"][pop], ensure_ascii=False))
        ms = res["monthly_spread"][pop]
        print(pop, f"strong beats weak {ms['strong_beats_weak']}/{ms['months']} months")
