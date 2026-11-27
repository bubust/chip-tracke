"""B132 考卷（PLAN-B132.md，2026-11-27 寫死）：引擎 v2（加換組、週線／母級／15 分轉折）＋挑重點線
python research/b131/run_b132.py [引擎版本，預設 2]（要先有 data/tx_d.csv、data/tx_5m.csv）"""
import json
import os
import sys
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R  # noqa: E402

rng = np.random.default_rng(132)
R.rng = np.random.default_rng(1321)


V = int(sys.argv[1]) if len(sys.argv) > 1 else 2                     # 引擎版本：2＝B132、3＝B136


def main():
    d, b60 = R.load()
    import pandas as pd
    r5 = pd.read_csv(os.path.join(HERE, "data", "tx_5m.csv"))
    b15 = R.FD.agg_bars([tuple(x) for x in r5[["ts", "o", "h", "l", "c", "v"]].itertuples(index=False)], "TX", 15)
    tdays = list(d.date)
    key = json.load(open(os.path.join(HERE, "key.json"), encoding="utf-8"))["posts"]
    rows = []
    for p in key:
        cut = datetime.fromisoformat(p["cut"]).replace(tzinfo=R.TW)
        h, l, c, price, bars, d60, nd = R.view_at(d, b60, tdays, cut)
        if bars is None:
            continue
        q15 = [b for b in b15 if b["time"] + 900 <= cut.timestamp()]
        out = R.SC.levels(h, l, c, price, bars, d60, b15=q15, v=V)
        lv = out["levels"]
        K = [tuple(z) for z in p["levels"]]
        allp = np.array(sorted({x["p"] for x in lv}))
        h_all = R.hits(allp, K)
        dist = np.abs(allp - price)
        sd = np.mean([R.hits(price + rng.choice([-1, 1], len(allp)) * rng.choice(dist, len(allp)), K).mean() for _ in range(R.N_RAND)])
        top = R.SC.rank(lv, price, 8)
        tp = np.array([t["p"] for t in top])
        cl = [c_["p"] for c_ in R.SC.clusters(lv) if abs(c_["p"] / price - 1) <= 0.12]
        near = np.array(sorted(cl, key=lambda x: abs(x - price))[:len(tp)])
        inK = lambda xs: np.array([any(lo * (1 - R.TOL) <= x <= hi * (1 + R.TOL) for lo, hi in K) for x in xs])   # noqa: E731
        prec_top = float(inK(tp).mean()) if len(tp) else 0.0
        prec_near = float(inK(near).mean()) if len(near) else 0.0
        cl_in = inK(np.array(cl))
        prec_rand = float(cl_in.mean()) if len(cl) else 0.0                 # 從 ±12% 的群裡隨便挑 8 條的期望精準＝群的平均
        rows.append({"id": p["id"], "label": p["label"], "week": cut.strftime("%G-%V"), "price": price, "n_key": len(K), "n_eng": int(len(allp)),
                     "recall": float(h_all.mean()), "same_dist": float(sd),
                     "prec_top": prec_top, "prec_rand8": prec_rand, "prec_near8": prec_near,
                     "recall_top": float(R.hits(tp, K).mean()), "recall_near": float(R.hits(near, K).mean()),
                     "top": [{"p": t["p"], "score": t["score"], "rules": t["rules"], "hit": bool(inK([t["p"]])[0])} for t in top],
                     "alt": bool(out.get("alt")), "missed": [list(z) for z, hh in zip(K, h_all) if not hh]})
    tests = {"v2 全部 vs 同樣距離隨便挑": R.boot_weeks(rows, "recall", "same_dist"),
             "重點線精準 vs 隨便挑 8 條": R.boot_weeks(rows, "prec_top", "prec_rand8"),
             "重點線精準 vs 最近的 8 條": R.boot_weeks(rows, "prec_top", "prec_near8")}
    for (k, v), q in zip(tests.items(), R.bh([v["p"] for v in tests.values()])):
        v["q"] = q
    mean = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in
            ("recall", "same_dist", "prec_top", "prec_rand8", "prec_near8", "recall_top", "recall_near", "n_eng")}
    res = {"n": len(rows), "mean": mean, "tests": tests, "posts": rows}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(res, open(os.path.join(HERE, "results", "b132.json" if V == 2 else f"b132_v{V}.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k != "posts"}, ensure_ascii=False, indent=1, default=float))
    for r in rows:
        print(f"{r['label']:10s} 全部 {r['recall']*100:5.1f}%（同距離 {r['same_dist']*100:5.1f}%）｜重點線 8 條中 {sum(t['hit'] for t in r['top'])} 條是她的"
              f"（最近 8 條 {r['prec_near8']*len(r['top']):.0f}）｜換組 {'有' if r['alt'] else '－'}｜漏 {r['missed'][:5]}")


if __name__ == "__main__":
    main()
