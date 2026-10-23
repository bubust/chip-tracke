"""B81 研究共用：只用 t 當時看得到的資料（轉折確認時間 ci ≤ t）重算日 K 的價位梯（跟網站 service.compute 同一套函式）"""
import csv
import os
import sqlite3
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
from wave import engine as E, keylevel as KL, levelmap as LM, levels as LV, nest as NE, volume as VO  # noqa: E402
from wave import service as S  # noqa: E402

B80_DATA = os.path.join(ROOT, "research", "b80", "data")


def load_twii_daily():
    con = sqlite3.connect(os.path.join(ROOT, "chip_data", "wave.db"))
    rows = con.execute("SELECT date,o,h,l,c FROM idx_daily WHERE sym='TWII' AND date>='2000-01-01' ORDER BY date").fetchall()
    to = {}
    with open(os.path.join(B80_DATA, "turnover.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            to[r["date"]] = float(r["amt"])
    d = [r[0] for r in rows]
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in (1, 2, 3, 4))
    return {"name": "D1", "dates": np.array(d), "o": o, "h": h, "l": l, "c": c, "v": [to.get(x) for x in d],
            "years": np.array([int(x[:4]) for x in d])}


def prep_daily(D):
    o, h, l, c = D["o"], D["h"], D["l"], D["c"]
    D["atr"] = E.atr(h, l, c)
    D["piv"] = {deg: E.zigzag(h, l, E.thresholds(h, l, c, deg)) for deg in ("small", "mid", "big")}
    return D


def an_at(D, t):
    o, h, l, c = D["o"], D["h"], D["l"], D["c"]
    trend = S._trend(c, t)
    return {deg: E.analyze(o, h, l, c, deg, t=t, trend=trend, piv=D["piv"][deg]) for deg in ("small", "mid")}


def map_at(D, t, tf="1d", an=None, st=None):
    """t 當天收盤時的網站價位梯（1d＝小級、1wk＝中級）；回傳 (levelmap, key, an)"""
    st = st or S.stats()
    o, h, l, c = D["o"], D["h"], D["l"], D["c"]
    an = an or an_at(D, t)
    a = float(D["atr"][t])
    price = float(c[t])
    lv = LV.build(h, l, c, t, an, a, dates=D["dates"])
    mode, deg = ("short", "small") if tf == "1d" else ("swing", "mid")
    cands = KL.candidates(an[deg], h, l, c, t, a, price=price, k=3, look=S.KEY_LOOK[mode])
    key = S._key_out(cands, mode, price, a, st)
    prim, alt = S._with_dates(an[deg]["primary"], D["dates"]), S._with_dates(an[deg]["alternate"], D["dates"])
    pos = NE.positioning(prim, alt, price, "日 K" if tf == "1d" else "週 K")
    if tf == "1wk" and pos is not None:                     # 跟網站一樣：週 K 母尺跟日 K 同一段 → 不重複放（PLAN-B81 §7.2）
        pd_ = NE.positioning(S._with_dates(an["small"]["primary"], D["dates"]), S._with_dates(an["small"]["alternate"], D["dates"]), price, "日 K")
        if LM.same_ruler(pos, pd_):
            pos = None
    vols = D["v"][: t + 1]
    zones = VO.vol_zones(h[: t + 1], l[: t + 1], c[: t + 1], vols, a, 120 if tf == "1d" else 250)
    ld = cands.get("dir") or 0
    lm = LM.build({"price": price, "win": S.TF_WIN[tf], "levels": lv.get(mode) or {}, "key": key, "nest": None,
                   "wave": {"primary": prim, "alternate": alt}, "positioning": pos, "zones": zones, "leg_dir": ld,
                   "vol_ok": False, "hlc": (h[: t + 1], l[: t + 1], c[: t + 1])})
    return lm, key, an


if __name__ == "__main__":
    import time
    D = prep_daily(load_twii_daily())
    t0 = time.time()
    n = 0
    for t in range(len(D["c"]) - 200, len(D["c"]), 20):
        lm, key, an = map_at(D, t)
        n += 1
    print(f"{n} 次 {(time.time() - t0) / n * 1000:.0f} ms/次")
    lm, key, an = map_at(D, len(D["c"]) - 1)
    print("最後一天", D["dates"][-1], "key", key and key["price"], "top3", {k: (v or {}).get("price") for k, v in lm["top3"].items() if isinstance(v, dict) or v is None})
    print([(round(i["price"]), i["side"], i["kind"]) for i in lm["items"]])
