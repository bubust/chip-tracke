"""B131 研究：推演引擎（wave/scenario.py）的兩個考卷（PLAN.md，2026-11-27 寫死）
- 考卷 A：她 34 篇貼文的 230 個價位，引擎用「她發文當時看得到的資料」自己算，命中幾成；對照 隨機、只用轉折＋均線＋整數
- 考卷 B：2018～2026 每天收盤用 R1～R3 判方向，接下來 10 個交易日 × 方向，比隨機
python research/b131/run.py（要先有 data/tx_d.csv、data/tx_5m.csv）"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from wave import engine as E  # noqa: E402
from wave import futdata as FD  # noqa: E402
from wave import scenario as SC  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TW = timezone(timedelta(hours=8))
TOL = 0.001
N_RAND, N_BOOT, SEED = 2000, 2000, 131
rng = np.random.default_rng(SEED)


def load():
    d = pd.read_csv(os.path.join(HERE, "data", "tx_d.csv"))
    d["date"] = d.date.astype(str).str[:10]
    r5 = pd.read_csv(os.path.join(HERE, "data", "tx_5m.csv"))
    rows = [tuple(x) for x in r5[["ts", "o", "h", "l", "c", "v"]].itertuples(index=False)]
    b60 = FD.agg_bars(rows, "TX", 60)
    return d, b60


def trade_date_of(ts: float, tdays: list) -> str:
    """60 分 K 屬於哪個交易日：15:00 以後的夜盤算下一個交易日（期交所的算法）"""
    dt = datetime.fromtimestamp(ts, TW)
    base = dt.date() + timedelta(days=1) if dt.hour >= 15 else dt.date()
    s = base.isoformat()
    return next((x for x in tdays if x >= s), s)


def view_at(d: pd.DataFrame, b60: list, tdays: list, cut: datetime):
    """cut 當下看得到的：收完的日 K＋進行中那根（60 分 K 拼）、收完的 60 分 K、現價"""
    cts = cut.timestamp()
    done = d[[datetime.fromisoformat(x + "T13:45").replace(tzinfo=TW).timestamp() <= cts for x in d.date]]
    h, l, c = done.h.values.astype(float), done.l.values.astype(float), done.c.values.astype(float)
    dates = list(done.date)
    bars = [b for b in b60 if b["time"] + 3600 <= cts]
    last_done = dates[-1]
    part = [b for b in bars if trade_date_of(b["time"], tdays) > last_done]
    price = float(c[-1])
    if part:
        h = np.r_[h, max(b["high"] for b in part)]
        l = np.r_[l, min(b["low"] for b in part)]
        c = np.r_[c, part[-1]["close"]]
        dates.append(trade_date_of(part[-1]["time"], tdays))
        price = float(part[-1]["close"])
    elif bars:
        price = float(bars[-1]["close"])
    idx = {x: i for i, x in enumerate(dates)}
    d60 = [idx.get(trade_date_of(b["time"], tdays), len(dates) - 1) for b in bars]
    n_days60 = len(set(d60))
    return h, l, c, price, (bars if n_days60 >= 10 else None), (d60 if n_days60 >= 10 else None), n_days60


def hits(levels: np.ndarray, key: list) -> np.ndarray:
    """她每個價位有沒有被命中（區間兩端各放寬 TOL）"""
    out = np.zeros(len(key), bool)
    if len(levels) == 0:
        return out
    for j, (lo, hi) in enumerate(key):
        out[j] = bool(np.any((levels >= lo * (1 - TOL)) & (levels <= hi * (1 + TOL))))
    return out


def exam_a(d, b60):
    key = json.load(open(os.path.join(HERE, "key.json"), encoding="utf-8"))["posts"]
    tdays = list(d.date)
    rows = []
    for p in key:
        cut = datetime.fromisoformat(p["cut"]).replace(tzinfo=TW)
        h, l, c, price, bars, d60, nd = view_at(d, b60, tdays, cut)
        out = SC.levels(h, l, c, price, bars, d60, v=1)
        lv = out["levels"]
        K = [tuple(z) for z in p["levels"]]
        allp = np.array(sorted({x["p"] for x in lv}))
        der = np.array(sorted({x["p"] for x in lv if x["rule"] not in ("R0", "R5")}))
        lo_r, hi_r = float(allp.min()), float(allp.max())
        rnd_round = np.arange(np.ceil(lo_r / 500) * 500, hi_r + 1, 500.0)
        naive = np.array(sorted({x["p"] for x in lv if x["rule"] in ("R0", "R5")} | set(rnd_round)))
        h_all, h_der, h_naive = hits(allp, K), hits(der, K), hits(naive, K)
        inc = h_der & ~h_naive
        r_all = np.empty(N_RAND)
        r_der = np.empty(N_RAND)
        r_inc = np.empty(N_RAND)
        for k in range(N_RAND):
            ra = rng.uniform(lo_r, hi_r, len(allp))
            rd = rng.uniform(lo_r, hi_r, max(1, len(der)))
            r_all[k] = hits(ra, K).mean()
            hr = hits(rd, K)
            r_der[k] = hr.mean()
            r_inc[k] = (hr & ~h_naive).mean()
        prec = float(np.mean([any(lo * (1 - TOL) <= v <= hi * (1 + TOL) for lo, hi in K) for v in allp]))
        by_rule = {}
        for j, (lo, hi) in enumerate(K):
            rs = sorted({x["rule"] for x in lv if lo * (1 - TOL) <= x["p"] <= hi * (1 + TOL)})
            for r in rs:
                by_rule[r] = by_rule.get(r, 0) + 1
        st = out["st"]
        rows.append({"id": p["id"], "label": p["label"], "cut": p["cut"], "has60": bars is not None, "days60": nd, "price": price,
                     "n_key": len(K), "n_eng": int(len(allp)), "n_der": int(len(der)),
                     "recall": float(h_all.mean()), "recall_rand": float(r_all.mean()),
                     "recall_der": float(h_der.mean()), "recall_der_rand": float(r_der.mean()),
                     "inc": float(inc.mean()), "inc_rand": float(r_inc.mean()), "precision": prec, "by_rule": by_rule,
                     "missed": [list(z) for z, hh in zip(K, h_all) if not hh],
                     "struct": None if not st else {k: st[k]["p"] for k in ("T", "L1", "H2", "X")} | {"rb": st["rb"], "d": st["d"]},
                     "week": cut.strftime("%G-%V")})
    return rows


def boot_weeks(rows, fld_a, fld_b):
    """同一週的貼文綁在一起 bootstrap：平均（a − b）≤ 0 的比例＝p 值"""
    wk = sorted({r["week"] for r in rows})
    g = {w: [r[fld_a] - r[fld_b] for r in rows if r["week"] == w] for w in wk}
    obs = float(np.mean([x for w in wk for x in g[w]]))
    bs = []
    for _ in range(N_BOOT):
        pick = rng.choice(wk, len(wk))
        xs = [x for w in pick for x in g[w]]
        bs.append(np.mean(xs))
    bs = np.array(bs)
    return {"diff": obs, "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "p": float(np.mean(bs <= 0))}


def bh(ps):
    ps = np.asarray(ps, float)
    o = np.argsort(ps)
    q = np.empty(len(ps))
    prev = 1.0
    for rank, i in reversed(list(enumerate(o, 1))):
        prev = min(prev, ps[i] * len(ps) / rank)
        q[i] = prev
    return q.tolist()


def exam_b(d):
    h, l, c = d.h.values.astype(float), d.l.values.astype(float), d.c.values.astype(float)
    dates = list(d.date)
    piv = E.zigzag(h, l, E.thresholds(h, l, c, "small"))              # 因果：ci ≤ t 的轉折跟只跑到 t 一模一樣
    H = 10
    recs = []
    t0 = next(i for i, x in enumerate(dates) if x >= "2018-01-01")
    for t in range(t0, len(c) - H):
        conf, tent = E.state_at(piv, h, l, t)
        seq = (conf + ([tent] if tent else []))[-40:]
        m = SC.merge_all(seq)
        cl = SC.call(m, h[:t + 1], l[:t + 1], c[t])
        fwd = c[t + H] / c[t] - 1
        recs.append({"date": dates[t], "s": cl["s"], "call": cl["call"], "fwd": fwd})
    df = pd.DataFrame(recs)
    df["month"] = df.date.str[:7]
    act = df[df.call != 0].copy()
    act["pnl"] = act.call * act.fwd - 0.0002
    rs = rng.choice([-1, 1], size=(len(act), 5))
    act["rand"] = (rs * act.fwd.values[:, None]).mean(axis=1) - 0.0002

    def test(sub):
        if len(sub) < 30:
            return None
        mo = sorted(sub.month.unique())
        g = {m_: sub[sub.month == m_] for m_ in mo}
        bs = []
        for _ in range(N_BOOT):
            pick = rng.choice(mo, len(mo))
            x = pd.concat([g[m_] for m_ in pick])
            bs.append(x.pnl.mean() - x.rand.mean())
        bs = np.array(bs)
        return {"n": int(len(sub)), "pnl_pct": round(sub.pnl.mean() * 100, 3), "rand_pct": round(sub.rand.mean() * 100, 3),
                "long_pct": round(sub.fwd.mean() * 100, 3), "win": round(float((sub.pnl > 0).mean()) * 100, 1),
                "diff_pct": round((sub.pnl.mean() - sub.rand.mean()) * 100, 3),
                "ci_pct": [round(float(np.percentile(bs, 2.5)) * 100, 3), round(float(np.percentile(bs, 97.5)) * 100, 3)],
                "p": float(np.mean(bs <= 0))}

    out = {"all": test(act), "is": test(act[act.date < "2023-01-01"]), "oos": test(act[act.date >= "2023-01-01"])}
    for s in ("S1", "S2", "S4"):
        out[s] = test(act[act.s == s])
    out["share"] = {k: round(float(v), 3) for k, v in df.s.fillna("無").value_counts(normalize=True).items()}
    return out


if __name__ == "__main__":
    d, b60 = load()
    A = exam_a(d, b60)
    main = [r for r in A if r["has60"]]
    tests = {"引擎 vs 隨機": boot_weeks(main, "recall", "recall_rand"),
             "R2～R8 vs 同個數隨機": boot_weeks(main, "recall_der", "recall_der_rand"),
             "R2～R8 多抓到的 vs 隨機": boot_weeks(main, "inc", "inc_rand")}
    q = bh([v["p"] for v in tests.values()])
    for (k, v), qq in zip(tests.items(), q):
        v["q"] = qq
    early = [r for r in A if not r["has60"]]
    B = exam_b(d)
    qb = bh([B[k]["p"] for k in ("all", "is", "oos") if B[k]])
    for k, qq in zip([k for k in ("all", "is", "oos") if B[k]], qb):
        B[k]["q"] = qq
    res = {"A": {"posts": A, "tests": tests,
                 "main": {k: round(float(np.mean([r[k] for r in main])), 4) for k in ("recall", "recall_rand", "recall_der", "recall_der_rand", "inc", "inc_rand", "precision")},
                 "early": {k: round(float(np.mean([r[k] for r in early])), 4) for k in ("recall", "recall_rand", "precision")} if early else None,
                 "n_main": len(main), "n_early": len(early)},
           "B": B}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "results", "b131.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print(json.dumps({"A": {k: v for k, v in res["A"].items() if k != "posts"}, "B": B}, ensure_ascii=False, indent=1, default=float))
