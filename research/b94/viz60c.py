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
import run60d as W  # noqa: E402
from wave import engine as E, intraday as I, levels as LV  # noqa: E402

FROM_TRADE = "2026-08-04"      # 最近 3 個月（交易進場日）
FROM_BAR = "2023-12-01"        # 依波浪（B94d）的交易要看 3 年，K 棒從這裡開始


def wave_text(p, x, close):
    """依波浪那一筆：用白話寫出主要劇本怎麼決定進場價、停損、目標"""
    f = lambda v: f"{v:,.0f}"  # noqa: E731
    L = [q["p"] for q in p["labels"]]
    side, kind, info = x["side"], x["kind"], x["info"]
    up = side > 0
    out = [f"主要劇本：{p['text']}。"]
    if kind == "W2":
        r = info["ratio"]
        out.append(f"第 1 浪 {f(L[0])} → {f(L[1])}（{f(info['len'])} 點）。第 2 浪通常{'回' if up else '反彈'} 0.5～0.618："
                   + "、".join(f"{rr:g}＝{f(v)}" for rr, v in info["lv"]) + "。")
        out.append(f"這根收盤 {f(close)}，" + ("還沒到 0.5 → 掛 0.5。" if r == 0.5 else "已經過了 0.5 → 掛 0.618。"))
        out.append(f"停損 {f(x['stop'])}：第 2 浪不能{'跌破' if up else '漲過'}第 1 浪起點，{'跌破' if up else '漲過'}就代表這個數法錯了。")
        out.append(f"目標 {f(x['tg'])}：進場價 {'＋' if up else '－'} 1.618 × 第 1 浪（第 3 浪常是第 1 浪的 1.618 倍）。")
    elif kind == "W4":
        r = info["ratio"]
        out.append(f"第 1 浪 {f(L[0])} → {f(L[1])}（{f(info['len'])} 點）；第 3 浪 {f(L[2])} → {f(L[3])}（{f(info['len3'])} 點）。"
                   f"第 4 浪通常{'回' if up else '反彈'}第 3 浪的 0.382～0.5：" + "、".join(f"{rr:g}＝{f(v)}" for rr, v in info["lv"]) + "。")
        out.append(f"這根收盤 {f(close)}，" + ("還沒到 0.382 → 掛 0.382。" if r == 0.382 else "已經過了 0.382 → 掛 0.5。"))
        out.append(f"停損 {f(x['stop'])}＝第 1 浪{'高點' if up else '低點'}：第 4 浪不能{'跌進' if up else '漲進'}第 1 浪的範圍。")
        out.append(f"目標 {f(x['tg'])}：進場價 {'＋' if up else '－'} 1 × 第 1 浪（第 5 浪常跟第 1 浪差不多長）。")
    else:
        if p["kind"] == "impulse":
            a0, a1, b = L[5], L[6], L[7]
        else:
            a0, a1, b = L[0], L[1], L[2]
        out.append(f"A 浪 {f(a0)} → {f(a1)}（{f(info['lenA'])} 點），B 浪到 {f(b)}，C 浪正在{'下跌' if up else '上漲'}。"
                   f"C 浪常跟 A 浪等長：C＝A 在 {f(info['lv'][0][1])}，C＝1.618 倍 A 在 {f(info['lv'][1][1])}。")
        out.append(f"這根收盤 {f(close)}，還沒到 C＝A → 掛 C＝A。")
        out.append(f"停損 {f(x['stop'])}：C 浪走過 1.618 倍 A 還沒停，就不是這個數法。")
        out.append(f"目標 {f(x['tg'])}：B 浪{'高點' if up else '低點'}（C 浪的起點）。")
    return out


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
    lab = lambda i: f"{dates[i][:4]}/{dates[i][5:7]}/{dates[i][8:10]} {dates[i][11:16]}"  # noqa: E731
    lab_s = lambda i: f"{dates[i][5:7]}/{dates[i][8:10]} {dates[i][11:16]}"  # noqa: E731
    snaps = {}

    def snap(t):
        if t in snaps:
            return
        k = bisect.bisect_left(ddate, dates[t][:10]) - 1
        prev = dd.iloc[k]
        daily = {"prev_h": float(prev.h), "prev_l": float(prev.l), "prev_c": float(prev.c), "ma20": float(prev.ma20)}
        tr = 1 if c[t] > daily["ma20"] else -1
        an = E.analyze(o, h, l, c, "intra", t=t, trend=tr, piv=piv)
        b = LV.build_ultra(h, l, c, t, an, float(atr[t]), float(c[t]), label=lab_s, daily=daily)
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
    prim, wtrend = W.counts(m, d)
    for side, sname in ((1, "long"), (-1, "short")):
        for vk, v in W.V.items():
            rows = []
            for x in W.book(o, h, l, c, prim, wtrend, dates, side, v):
                if x["t"] < i0:
                    continue
                snap(x["t"])
                rows.append({"t": x["t"] - i0, "e": x["e"] - i0, "k": x["k"] - i0, "side": side,
                             "fill": round(x["fill"], 1), "exit": round(x["exit"], 1), "tg": round(x["tg"], 0),
                             "stop": round(x["stop"], 1), "be_k": None, "why": x["why"], "both": x["both"],
                             "pts": round(x["pts"], 0), "bars": x["bars"], "near": round(x["ent"], 0), "far": None,
                             "wk": x["kind"], "lv": [[r, round(p_, 0)] for r, p_ in x["info"]["lv"]],
                             "setup": wave_text(prim[x["t"]], x, c[x["t"]])})
            books[f"{sname}|W{vk}"] = rows
    snap(len(c) - 1)                                                     # 最後一根的數法（圖的總覽用）
    res = {"bars": [[lab(i), round(o[i], 0), round(h[i], 0), round(l[i], 0), round(c[i], 0)] for i in range(i0, len(c))],
           "from_trade": FROM_TRADE, "variants": {**{k: v["name"] for k, v in C.V.items()}, **{"W" + k: v["name"] for k, v in W.V.items()}},
           "books": books,
           "snaps": {str(k - i0): v for k, v in snaps.items()}, "last": len(c) - 1 - i0,
           "stop_pts": C.STOP_PTS, "rr": C.RR, "buf_atr": C.BUF_ATR, "cost": C.COST}
    with open(out_path, "w") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"), default=lambda x: x.item() if hasattr(x, "item") else str(x))
    print(out_path, os.path.getsize(out_path), {k: len(v) for k, v in books.items()})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(C.OUT, "b94_viz.json"))
