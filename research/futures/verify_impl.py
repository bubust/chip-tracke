"""B75 §11：網站資料管線（wave.db：futdata 從 FinMind／期交所抓、存檔再讀）vs 研究（research/futures/data CSV）抽最近 30 天比對
- 夜盤報酬（同月份基準）、散戶小台多空比、外資選擇權偏多金額：0 不一致（差 < 1e-9）
- 轉折點 K3（短線／波段）：同一份加權日 K（網站資料庫）用研究的寫法（逐天 analyze＋candidates）vs 網站 service 的寫法，最後一天 0 不一致
用法：.venv/Scripts/python research/futures/verify_impl.py（要先有本機 wave.db 期貨資料）"""
import os
import sys

import numpy as np
import pandas as pd

from common import DATA, E, FD, WDATA
from wave import data as D, keylevel as KL, service as S

bad = []


def chk(name, a, b, tol=1e-9):
    if a is None or b is None or (isinstance(a, float) and np.isnan(a)) or abs(float(a) - float(b)) > tol:
        bad.append((name, a, b))


if __name__ == "__main__":
    site_fd = FD.load_fut_daily()
    res_fd = FD.select_continuous(pd.read_csv(os.path.join(DATA, "fut_tx_daily.csv"), dtype={"contract_date": str}))
    a = FD.night_returns(site_fd).set_index("date")
    b = FD.night_returns(res_fd).set_index("date")
    days = sorted(set(a.index) & set(b.index))[-30:]
    for d in days:
        chk(f"night {d}", a.loc[d, "night_ret"], b.loc[d, "night_ret"])
    print("夜盤報酬比對", len(days), "天")
    sc = FD.load_fut_chips().set_index("date")
    rc = FD.fut_chips_from_finmind(pd.read_csv(os.path.join(DATA, "fut_mtx_daily.csv"), dtype={"contract_date": str}),
                                   pd.read_csv(os.path.join(DATA, "fm_fut_mtx.csv")),
                                   pd.read_csv(os.path.join(WDATA, "fm_opt.csv"))).set_index("date")
    days2 = sorted(set(sc.dropna(subset=["retail_ratio"]).index) & set(rc.dropna(subset=["retail_ratio"]).index))[-30:]
    for d in days2:
        chk(f"retail {d}", sc.loc[d, "retail_ratio"], rc.loc[d, "retail_ratio"])
        chk(f"opt {d}", sc.loc[d, "opt_f_bull"], rc.loc[d, "opt_f_bull"], 1e-6)
    print("散戶小台／選擇權比對", len(days2), "天")
    # 轉折點：網站 base 的陣列，研究寫法（整段 ZigZag＋逐天 analyze）vs service 寫法（只用到 t 的 analyze）
    b0 = S.base("TWII")
    o, h, l, c = b0["o"], b0["h"], b0["l"], b0["c"]
    t = len(c) - 1
    for mode, deg in S.MODE_DEG.items():
        piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
        an_r = E.analyze(o, h, l, c, deg, t=t, trend=S._trend(c, t), piv=piv)
        cr = KL.candidates(an_r, h, l, c, t, b0["atr"], k=3, look=S.KEY_LOOK[mode])
        cs = KL.candidates(b0["an"][deg], h, l, c, t, b0["atr"], k=3, look=S.KEY_LOOK[mode])
        for r in KL.RULES:
            if r in cr or r in cs:
                chk(f"key {mode} {r}", (cr.get(r) or {}).get("price"), (cs.get(r) or {}).get("price"))
    print("轉折點比對 2 個模式 × 3 種候選")
    print("不一致：", len(bad))
    for x in bad[:20]:
        print("  ", x)
    sys.exit(1 if bad else 0)
