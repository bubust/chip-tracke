"""B94c 圖解：最近 3 個月的每一筆回測交易（進出點、當時的支撐區／壓力區、停損、目標）＋進場前那根收盤時網站 60 分數浪。
python research/b94/viz60c.py [輸出.json] → 給圖解頁面用的資料（只用 run60c 的規則，不改任何規則）"""
import bisect
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run60c as C  # noqa: E402
from wave import engine as E, intraday as I, levels as LV  # noqa: E402

FROM_TRADE = "2026-08-04"      # 最近 3 個月（交易進場日）
FROM_BAR = "2026-06-01"        # 圖上多放一段前面的 K 棒，數浪的起點才看得到


def main(out_path):
    m = pd.read_csv(os.path.join(C.DATA, "twii_60m.csv")).dropna(subset=["o", "h", "l", "c"])
    m = m[(m.h >= m.l) & (m.c > 0)].reset_index(drop=True)
    d = pd.read_csv(os.path.join(C.DATA, "twii_d.csv")).dropna(subset=["o", "h", "l", "c"])
    d = d[(d.h >= d.l) & (d.c > 0)].reset_index(drop=True)
    o, h, l, c = (m[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    dates = m.date.astype(str).to_numpy()
    Z, atr, trend = C.zones3(m, d)
    piv = E.zigzag(h, l, I.theta(h, l, c))
    dd = d.copy()
    dd["ma20"] = dd.c.rolling(20).mean()
    ddate = dd.date.tolist()
    i0 = int(np.searchsorted(dates, FROM_BAR))
    lab = lambda i: f"{dates[i][5:7]}/{dates[i][8:10]} {dates[i][11:16]}"  # noqa: E731
    snaps = {}

    def snap(t):
        if t in snaps:
            return
        k = bisect.bisect_left(ddate, dates[t][:10]) - 1
        prev = dd.iloc[k]
        daily = {"prev_h": float(prev.h), "prev_l": float(prev.l), "prev_c": float(prev.c), "ma20": float(prev.ma20)}
        tr = 1 if c[t] > daily["ma20"] else -1
        an = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv)
        b = LV.build_ultra(h, l, c, t, an, float(atr[t]), float(c[t]), label=lab, daily=daily)
        zf = lambda z: {"lo": z["lo"], "hi": z["hi"], "src": [x["label"] for x in z["sources"]]}  # noqa: E731

        def cnt(x):
            if not x:
                return None
            return {"text": x["text"], "kind": x["kind"], "cur": x["current"],
                    "labels": [{"i": y["i"] - i0, "p": round(y["p"], 0), "s": y["disp"], "tent": y["tentative"]} for y in x["labels"]],
                    "invalid": x["invalid"], "invalid_side": x["invalid_side"],
                    "targets": [{"label": y["label"], "p": round(y["price"], 0)} for y in x["targets"][:4]]}
        f = an.get("fib")
        pts = an["pivots"][-14:] + ([an["tentative"]] if an.get("tentative") else [])
        snaps[t] = {"t": t - i0, "time": lab(t), "close": round(c[t], 0), "atr": round(float(atr[t]), 0),
                    "prev_c": round(daily["prev_c"], 0), "ma20": round(daily["ma20"], 0), "trend": int(trend[t]),
                    "sup": [zf(z) for z in b["support"]], "res": [zf(z) for z in b["resistance"]],
                    "zig": [{"i": p["i"] - i0, "p": round(p["p"], 0), "tent": p.get("ci") is None} for p in pts],
                    "primary": cnt(an.get("primary")), "alternate": cnt(an.get("alternate")),
                    "fib": None if not f else {"from": round(f["from"]["p"], 0), "to": round(f["to"]["p"], 0),
                                               "lv": [{"r": x["ratio"], "p": round(x["price"], 0)} for x in f["levels"]]}}

    books = {}
    for side, sname in ((1, "long"), (-1, "short")):
        for vk, v in C.V.items():
            trs = [x for x in C.book(o, h, l, c, Z, atr, trend, dates, side, v) if x["date"] >= FROM_TRADE]
            rows = []
            for x in trs:
                snap(x["t"])
                rows.append({"t": x["t"] - i0, "e": x["e"] - i0, "k": x["k"] - i0, "side": side,
                             "fill": round(x["fill"], 1), "exit": round(x["exit"], 1), "tg": round(x["tg"], 0),
                             "stop": round(x["stop0"], 1), "be_k": None if x["be_k"] is None else x["be_k"] - i0,
                             "why": x["why"], "both": x["both"], "pts": round(x["pts"], 0), "bars": x["bars"],
                             "near": round(float(Z["s_hi" if side > 0 else "r_lo"][x["t"], 0]), 0),
                             "far": round(float(Z["s_lo" if side > 0 else "r_hi"][x["t"], 0]), 0)})
            books[f"{sname}|{vk}"] = rows
    snap(len(c) - 1)                                                     # 最後一根的數法（圖的總覽用）
    res = {"bars": [[lab(i), round(o[i], 0), round(h[i], 0), round(l[i], 0), round(c[i], 0)] for i in range(i0, len(c))],
           "from_trade": FROM_TRADE, "variants": {k: v["name"] for k, v in C.V.items()}, "books": books,
           "snaps": {str(k - i0): v for k, v in snaps.items()}, "last": len(c) - 1 - i0,
           "stop_pts": C.STOP_PTS, "rr": C.RR, "buf_atr": C.BUF_ATR, "cost": C.COST}
    with open(out_path, "w") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"), default=lambda x: x.item() if hasattr(x, "item") else str(x))
    print(out_path, os.path.getsize(out_path), {k: len(v) for k, v in books.items()})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(C.OUT, "b94_viz.json"))
