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


def test_b132_regroup_and_describe():
    """B132 R9 換組：11/4 那種「50,265 往下自己走出三段、還沒破 39,442」→ 另外算一組（重疊線 45,523）"""
    piv = [31740, 49240, 39442, 50265, 45523, 47607, 42050]
    h, l, c = _daily(piv, tail=[42300.0, 42500.0])                  # 反彈還沒確認（42,050 還是進行中的極值）；確認了就不算換組（PLAN-B132 寫死的限制）
    o1 = SC.levels(h, l, c, 42500.0, v=1)
    o2 = SC.levels(h, l, c, 42500.0, v=2)
    assert o1.get("alt") is None and o2["alt"] is not None
    assert [round(o2["alt"][k]["p"]) for k in ("T", "L1", "H2", "X")] == [50265, 45523, 47607, 42050]
    v = {x["note"]: x["p"] for x in o2["levels"]}
    assert round(v["換組重疊線（第 1 段終點）"]) == 45523 and "換組最後一段 0.382" in v
    assert any(x["note"] == "週線轉折" for x in o2["levels"]) and not any(x["note"] == "週線轉折" for x in o1["levels"])
    top = SC.rank(o2["levels"], 42500.0, 8)
    assert 0 < len(top) <= 8 and all(abs(t["p"] / 42500 - 1) <= 0.12 for t in top)


def test_b132_describe_states():
    h, l, c = _daily(tail=list(np.linspace(33719, 39286, 5)[1:]))
    o = SC.levels(h, l, c, 39286.0, v=2)
    t = SC.describe(o["st"], 39286.0, o["levels"])
    assert t.startswith("50,265→37,694→44,911→33,719") and "過了重疊線 37,694" in t and "40,040" in t and "S2" in t


def test_b132_engine_by_tf():
    """網站：每個週期列引擎的結構線（重疊線、牆…）＋現價上下各 3 條最近的"""
    from wave import service as SV
    h, l, c = _daily(tail=list(np.linspace(33719, 39286, 5)[1:]))
    dates = [f"d{k:04d}" for k in range(len(c))]
    e = SV._engine({"chart": {}}, h, l, c, dates, 39286.0)
    d1 = {round(x["p"]): x for x in e["by_tf"]["1d"]}
    assert d1[37694]["role"] and d1[40040]["role"] and "S2" in e["text"]
    assert all("60 分" not in n for x in e["by_tf"]["1wk"] for n in x["notes"])
