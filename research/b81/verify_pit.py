"""B81 防偷看驗證（PLAN-B81 §6）：隨機 200 個 t，「截斷到 t 的資料重算轉折」vs「全資料＋ci≤t」的價位梯與試單必須一樣
用法：python research/b81/verify_pit.py"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pit  # noqa: E402
from wave import levelmap as LM  # noqa: E402
from wave import service as S  # noqa: E402


def sig(lm, price, atr, d):
    items = [(round(it["price"], 4), it["side"], it["kind"]) for it in lm["items"]]
    st = LM.setups(lm["items"], price, atr, d)
    ss = [(x["id"], x["level"], x["stop"], x["t1"]) for x in st["list"]]
    return items, ss


def main():
    full = pit.prep_daily(pit.load_twii_daily())
    n = len(full["c"])
    rng = np.random.default_rng(7)
    ts = sorted(rng.choice(np.arange(300, n), size=200, replace=False).tolist())
    st = S.stats()
    bad = []
    for tf in ("1d", "1wk"):
        deg = "small" if tf == "1d" else "mid"
        for t in ts:
            cut = {k: (v[: t + 1] if hasattr(v, "__len__") and len(v) == n else v) for k, v in full.items() if k not in ("atr", "piv")}
            cut = pit.prep_daily(cut)
            a1, k1, an1 = pit.map_at(full, t, tf, st=st)
            a2, k2, an2 = pit.map_at(cut, t, tf, st=st)
            atr = float(full["atr"][t])
            from run_setups import ladder_dir
            s1 = sig(a1, float(full["c"][t]), atr, ladder_dir(k1, an1[deg]))
            s2 = sig(a2, float(cut["c"][t]), float(cut["atr"][t]), ladder_dir(k2, an2[deg]))
            if s1 != s2:
                bad.append({"tf": tf, "t": t, "date": str(full["dates"][t]), "full": s1, "cut": s2})
    out = {"checked": len(ts) * 2, "mismatch": len(bad), "examples": bad[:5]}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "results", "verify_pit.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"檢查 {out['checked']} 個、不一致 {out['mismatch']} 個")
    for b in bad[:3]:
        print(json.dumps(b, ensure_ascii=False, default=str)[:800])


if __name__ == "__main__":
    main()
