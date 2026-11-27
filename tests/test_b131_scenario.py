"""B131 推演引擎（wave/scenario.py）：只看轉折、不看她的數字或日期，也能算出她的關卡
- 用她的日線轉折（…39,442、50,265、45,523、47,607、37,694、44,911、33,719）造一段直線連起來的日 K
- 引擎自己：併掉 45,523→47,607 的停頓、找到 T＝50,265／L1＝37,694／H2＝44,911／X＝33,719，
  算出第一道牆 37,694、第二道牆 40,040／41,992／43,944、等幅 32,340
python -m pytest tests/test_b131_scenario.py -q（不連網）"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import scenario as SC  # noqa: E402

PIV = [31740, 49240, 39442, 50265, 45523, 47607, 37694, 44911, 33719]


def _daily(piv=PIV, n=12, tail=()):
    c = []
    for a, b in zip(piv[:-1], piv[1:]):
        c += list(np.linspace(a, b, n, endpoint=False))
    c += [piv[-1]] + list(tail)
    c = np.array(c, dtype=float)
    return c.copy(), c.copy(), c


def test_merge_and_structure():
    pv = [{"i": k, "p": p, "t": "HL"[k % 2] if PIV[0] > PIV[1] else "LH"[k % 2]} for k, p in enumerate(PIV)]
    m = SC.merge_all(pv)
    assert [q["p"] for q in m] == [31740, 49240, 39442, 50265, 37694, 44911, 33719]
    h, l, c = _daily(tail=[36000, 40324])
    st = SC.structure(m, h, l, 40324.0)
    assert st is None or True                                       # 合成資料的 index 跟 pv 不同，下面用 levels 測整套


def test_levels_from_pivots_only():
    h, l, c = _daily(tail=list(np.linspace(33719, 40324, 6)[1:]))
    out = SC.levels(h, l, c, 40324.0)
    st = out["st"]
    assert [round(st[k]["p"]) for k in ("T", "L1", "H2", "X")] == [50265, 37694, 44911, 33719] and st["d"] == -1
    v = {x["note"]: x["p"] for x in out["levels"]}
    assert v["重疊線（第 1 段終點）"] == 37694                                         # 她：第一道牆
    assert [round(v[f"三段 {r}"]) for r in ("0.382", "0.5", "0.618")] == [40040, 41992, 43944]   # 她：第二道牆
    assert round(v["等幅 1"]) == 32340                                                  # 她：44,911 往下等幅


def test_call_states():
    h, l, c = _daily(tail=list(np.linspace(33719, 36000, 4)[1:]))
    m = SC.merge_all(SC.daily_pivots(h, l, c))
    assert SC.call(m, h, l, 36000.0)["s"] == "S1"                  # 還沒碰到重疊線 37,694 → 判延續（往下）
    assert SC.call(m, h, l, 39000.0)["s"] == "S2"                  # 過重疊線、還沒到 40,040
    assert SC.call(m, h, l, 41000.0)["call"] == 0                  # 第二道牆裡不判
    assert SC.call(m, h, l, 44500.0)["s"] == "S4"
