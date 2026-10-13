"""
宏爺 AI 戰情室的判斷有沒有用（B67，2026-10-13；決定 deep_patterns 在畫面上標「已回測」還是「參考」）

用法：python research/deep/hongye.py PD_CSV_GZ
母體：20 日均量 ≥300 張、股價 ≥10（同 factors.py）；每天取樣（K 線型態有些很少見）
x5／x20＝未來 5／20 日報酬 − 同一天所有樣本平均（超額）；穩定度：2025／2026 分開
測三件事：
  1. 趨勢格局 多頭／空頭／多箱／空箱（MA20／MA100），以及在我們的技術分類（強勢／中性／弱勢）裡面還有沒有額外資訊
  2. 當天 K 線型態（16 種）；宏爺說的「高檔墓碑／倒T＝見頂」「低檔鎚子／T字＝止跌」用 52 週位置分高低檔
  3. 100 日線乖離五分位
"""
import os, sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep_verdict import tech_series, tech_raw, bucket_of   # noqa: E402
from deep_patterns import kbar_type, trend_box               # noqa: E402
from backtest import load                                    # noqa: E402


def rows_of(item):
    sid, g = item
    ts = tech_series(g)
    o, h, lo, c = (g[k].values.astype(float) for k in ("open", "high", "low", "close"))
    ma100 = pd.Series(c).rolling(100).mean().values
    v = ts["vol20"].values
    out = []
    for t in range(130, len(g) - 21):
        if c[t] < 10 or not v[t] or np.isnan(v[t]) or v[t] < 300:
            continue
        r = ts.iloc[t]
        raw, _ = tech_raw(r)
        out.append({"date": g.date.iloc[t], "f5": c[t + 5] / c[t] - 1, "f20": c[t + 20] / c[t] - 1,
                    "box": trend_box(c[t], r["ma20"], ma100[t]), "kbar": kbar_type(o[t], h[t], lo[t], c[t]),
                    "bucket": bucket_of(raw), "pos52": r["pos52"], "bias100": c[t] / ma100[t] - 1,
                    "s5": t % 5 == 0})
    return out


def show(S, key, cats, min_n=200):
    for k in cats:
        m = S[key] == k
        n = int(m.sum())
        if n < min_n:
            print(f"  {k:16s} n={n}（太少）")
            continue
        a = S[m & (S.date < "2026")]
        b = S[m & (S.date >= "2026")]
        print(f"  {k:16s} x5 {S[m].x5.mean() * 100:+.2f}%  x20 {S[m].x20.mean() * 100:+.2f}%  "
              f"20日上漲 {(S[m].f20 > 0).mean() * 100:.0f}%  n={n:,}  "
              f"| 2025 x20 {a.x20.mean() * 100:+.2f}% / 2026 x20 {b.x20.mean() * 100:+.2f}%")


def weekly_rows_of(item):
    """B70 R2：只用已走完的週（資料最後一週不用）；那週最後一個交易日 t 取樣，看未來 20 個交易日"""
    from deep_patterns import weekly_bars
    sid, g = item
    if sid.startswith("00"):
        return []
    ts = tech_series(g)
    c = g.close.values.astype(float)
    v = ts["vol20"].values
    ws = weekly_bars(g, today=__import__("datetime").date(2100, 1, 1))[:-1]
    pos = {d: i for i, d in enumerate(g.date.astype(str).str.replace("-", ""))}
    out = []
    for w in ws:
        t = pos.get(w["end"])
        if t is None or t < 130 or t + 20 >= len(g):
            continue
        if c[t] < 10 or not v[t] or np.isnan(v[t]) or v[t] < 300:
            continue
        out.append({"date": g.date.iloc[t], "f5": c[t + 5] / c[t] - 1, "f20": c[t + 20] / c[t] - 1,
                    "kbar": kbar_type(w["open"], w["high"], w["low"], w["close"]), "pos52": ts["pos52"].iloc[t]})
    return out


def weekly_main(path):
    G = load(path)
    with Pool(8) as pool:
        S = pd.DataFrame([r for part in pool.map(weekly_rows_of, list(G.items()), chunksize=16) for r in part])
    S["x5"] = S.f5 - S.groupby("date").f5.transform("mean")
    S["x20"] = S.f20 - S.groupby("date").f20.transform("mean")
    print("週 K samples", len(S))

    def st(d):
        return (round(d.x5.mean() * 100, 2), round(d.x20.mean() * 100, 2), round((d.f20 > 0).mean() * 100), len(d))
    band = np.where(S.pos52 >= 0.7, "hi", np.where(S.pos52 <= 0.3, "lo", "mid"))
    band = pd.Series(band, index=S.index).where(S.pos52.notna(), "na")
    out = {"band_base": {b: st(S[band == b]) for b in ("hi", "mid", "lo")}, "kbar": {}}
    for k in S.kbar.value_counts().index:
        m = S.kbar == k
        if m.sum() < 150:
            continue
        e = {"all": st(S[m])}
        for b in ("hi", "mid", "lo"):
            if (m & (band == b)).sum() >= 150:
                e[b] = st(S[m & (band == b)])
        out["kbar"][k] = e
        a, b2 = S[m & (S.date < "2026")], S[m & (S.date >= "2026")]
        print(f"  週 {k:16s} x20 {e['all'][1]:+.2f}% n={e['all'][3]:,}  2025 {a.x20.mean() * 100:+.2f}% / 2026 {b2.x20.mean() * 100:+.2f}%",
              {b: e[b][1] for b in ("hi", "mid", "lo") if b in e})
    print("  位置基準", out["band_base"])
    import json
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hongye_weekly_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[2] == "--weekly":
    weekly_main(sys.argv[1])
    sys.exit(0)

if __name__ == "__main__":
    G = load(sys.argv[1])
    with Pool(8) as pool:
        S = pd.DataFrame([r for part in pool.map(rows_of, list(G.items()), chunksize=16) for r in part])
    S["x5"] = S.f5 - S.groupby("date").f5.transform("mean")
    S["x20"] = S.f20 - S.groupby("date").f20.transform("mean")
    print("samples", len(S), "（每天）；每 5 天取樣", int(S.s5.sum()))

    print("\n1. 趨勢格局（全部樣本）")
    show(S, "box", ["多頭", "多箱", "空箱", "空頭"])
    for bk in ("strong", "neutral", "weak"):
        print(f"   技術{ {'strong': '強勢', 'neutral': '中性', 'weak': '弱勢'}[bk]}裡面：")
        show(S[S.bucket == bk], "box", ["多頭", "多箱", "空箱", "空頭"])

    print("\n2. K 線型態（全部樣本）")
    order = S.kbar.value_counts().index.tolist()
    show(S, "kbar", order)
    hi, lo_ = S[S.pos52 >= 0.7], S[S.pos52 <= 0.3]
    print("   高檔（52 週位置 ≥70%）：")
    show(hi, "kbar", ["倒鎚紅K(墓碑線-上漲)", "倒鎚黑K(墓碑線-下跌)", "倒T線", "十字線", "大黑K", "中黑K"], 100)
    print("   低檔（52 週位置 ≤30%）：")
    show(lo_, "kbar", ["紅K鎚子(吊人線-上漲)", "黑K鎚子(吊人線-下跌)", "T字線", "十字線", "大紅K", "中紅K"], 100)

    print("\n3. 100 日線乖離五分位")
    q = pd.qcut(S.bias100, 5, labels=False, duplicates="drop")
    edges = S.bias100.quantile([0, .2, .4, .6, .8, 1]).round(3).tolist()
    print("  邊界", edges)
    print("  x20", [round(S[q == i].x20.mean() * 100, 2) for i in range(5)])
    print("  x5 ", [round(S[q == i].x5.mean() * 100, 2) for i in range(5)])

    # ── deep_patterns 常數：(x5, x20, 20 日上漲%, 筆數)；位置 hi＝52 週 ≥70%、lo＝≤30%、mid＝中間 ──
    def st(d):
        return (round(d.x5.mean() * 100, 2), round(d.x20.mean() * 100, 2), round((d.f20 > 0).mean() * 100), len(d))

    band = np.where(S.pos52 >= 0.7, "hi", np.where(S.pos52 <= 0.3, "lo", "mid"))
    band = pd.Series(band, index=S.index).where(S.pos52.notna(), "na")
    out = {"box": {k: st(S[S.box == k]) for k in ("多頭", "多箱", "空箱", "空頭")},
           "box_in_bucket": {bk: {k: st(S[(S.bucket == bk) & (S.box == k)]) for k in ("多頭", "多箱", "空箱", "空頭")
                                  if ((S.bucket == bk) & (S.box == k)).sum() >= 300}
                             for bk in ("strong", "neutral", "weak")},
           "band_base": {b: st(S[band == b]) for b in ("hi", "mid", "lo")},
           "kbar": {}}
    for k in order:
        m = S.kbar == k
        e = {"all": st(S[m])}
        for b in ("hi", "mid", "lo"):
            mb = m & (band == b)
            if mb.sum() >= 150:
                e[b] = st(S[mb])
        out["kbar"][k] = e
    print("\n4. 常數（貼到 deep_patterns.py）")
    print("  位置基準", out["band_base"])
    import json
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hongye_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
