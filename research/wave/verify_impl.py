"""B74 防偷看驗證（PLAN-B74 §5）：隨機 50 天，網站引擎「只給 t 以前資料」重算 vs 研究「全部資料跑一次、取第 t 天狀態」
兩者的轉折點、主要劇本（結構、方向、浪別、各點）、失效價、目標必須完全一樣；門檻 θ 也必須一樣。"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from wave import engine as E   # noqa: E402

df = pd.read_csv(os.path.join(os.path.dirname(__file__), "data", "TWII.csv")).dropna(subset=["o", "h", "l", "c"])
df = df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)
o, h, l, c = (df[k].values.astype(float) for k in ("o", "h", "l", "c"))
rng = np.random.default_rng(74)
days = sorted(rng.choice(np.arange(400, len(c)), size=50, replace=False))
bad = 0
for deg in ("small", "mid", "big"):
    full_th = E.thresholds(h, l, c, deg)
    piv_full = E.zigzag(h, l, full_th)
    for t in days:
        tr = 0 if t + 1 < 240 else (1 if c[t] > np.mean(c[t - 239:t + 1]) else -1)
        a = E.analyze(o[: t + 1], h[: t + 1], l[: t + 1], c[: t + 1], deg, trend=tr)
        th_t = E.thresholds(h[: t + 1], l[: t + 1], c[: t + 1], deg)
        conf, tent = E.state_at(piv_full, h, l, t)
        p, _ = E.primary_alternate(E.count_waves(conf + ([tent] if tent else []), trend=tr))
        same = (np.allclose(th_t, full_th[: t + 1]) and a["pivots"] == conf and a["tentative"] == tent
                and (a["primary"] or {}).get("labels") == (p or {}).get("labels")
                and (a["primary"] or {}).get("invalid") == (p or {}).get("invalid")
                and (a["primary"] or {}).get("targets") == (p or {}).get("targets"))
        if not same:
            bad += 1
            print("不一致", deg, df.date[t])
print(f"抽 {len(days)} 天 × 3 級數：不一致 {bad} 筆")
sys.exit(1 if bad else 0)
