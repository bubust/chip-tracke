"""B81：試單地圖（levelmap.setups）、週 K 母尺去重、研究結果寫進 stats.json、有漂移隨機漫步公式"""
import json
import math
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from wave import levelmap as LM  # noqa: E402


def _items(up=(48300, 48600), dn=(47900, 47600)):
    out = [{"price": p, "side": "up", "kind": "level", "struct": False, "name": f"壓力{p}"} for p in up]
    out += [{"price": p, "side": "down", "kind": "level", "struct": False, "name": f"支撐{p}"} for p in dn]
    return out


def test_setups_basic_numbers():
    su = LM.setups(_items(), 48000, 200, 1, "TX")
    assert su["ok"] and {x["id"] for x in su["list"]} == {"L", "S", "B"}
    L = next(x for x in su["list"] if x["id"] == "L")
    assert L["level"] == 47900 and L["zone"] == [47900, 47930] and L["stop"] == 47850 and L["t1"] == 48300 and L["t2"] == 48600
    assert L["rr"] == pytest.approx((48300 - 47915) / (47915 - 47850), abs=0.01)
    S = next(x for x in su["list"] if x["id"] == "S")
    assert S["level"] == 48300 and S["stop"] == 48350 and S["t1"] == 47900 and S["title"] == "反彈壓力試空"
    B = next(x for x in su["list"] if x["id"] == "B")
    assert B["level"] == 48300 and B["t1"] == 48600 and B["stop"] == 48250
    assert su["near"]["up"]["price"] == 48300 and su["near"]["down"]["price"] == 47900


def test_setups_trend_and_main():
    su = LM.setups(_items(), 48000, 200, -1, "TX")
    tr = {x["id"]: x["trend"] for x in su["list"]}
    assert tr == {"L": "逆勢", "S": "順勢", "B": "逆勢"}
    assert su["main"] == "S"
    assert "逆勢" in next(x for x in su["list"] if x["id"] == "L")["warn"]
    su0 = LM.setups(_items(), 48000, 200, 0, "TX")
    assert all(x["trend"] is None for x in su0["list"])


def test_setups_index_cannot_short():
    su = LM.setups(_items(), 48000, 200, -1, "TWII")
    S = next(x for x in su["list"] if x["id"] == "S")
    assert S["title"] == "減碼區" and "加權不能放空" in S["warn"] and "逆勢" not in S["warn"]


def test_setups_no_data_and_no_target():
    assert not LM.setups([], 48000, 200, 1)["ok"]
    assert not LM.setups(_items(), 48000, None, 1)["ok"]
    assert not LM.setups(_items(), 48000, float("nan"), 1)["ok"]
    assert not LM.setups(_items(), 0, 200, 1)["ok"] and not LM.setups(_items(), None, 200, 1)["ok"]   # 審查 Groq F1
    su = LM.setups(_items(up=()), 48000, 200, 1)                 # 上面沒有價位：沒有試多（沒目標）、沒有試空、沒有追多
    assert su["ok"] and su["list"] == [] and su["note"] == "附近沒有可以試單的價位" and su["main"] is None


def test_setups_bad_rr_not_main():
    su = LM.setups(_items(up=(48020, 48600), dn=(47990,)), 48000, 400, 1, "TX")   # 目標太近、停損太遠
    L = next(x for x in su["list"] if x["id"] == "L")
    assert L["rr"] < 1 and "賠率不夠" in L["warn"]
    assert su["main"] != "L"


def test_setups_worse_than_random_not_main():
    res = {"L": {"順勢": {"win": 0.3, "rw": 0.45, "n": 300, "pass": False, "worse": True}}}
    su = LM.setups(_items(), 48000, 200, 1, "TX", res)
    L = next(x for x in su["list"] if x["id"] == "L")
    assert L["res"]["worse"] and "比隨機差" in L["warn"]
    assert su["main"] == "B"                                     # 順勢、賠率夠、沒有比隨機差


def test_setups_in_zone():
    su = LM.setups(_items(up=(48010, 48600)), 48000, 200, 1, "TWII")
    S = next(x for x in su["list"] if x["id"] == "S")
    assert S["in_zone"] is True
    L = next(x for x in su["list"] if x["id"] == "L")
    assert L["in_zone"] is False


def test_same_ruler():
    a = {"ruler": [39384.85, 49968.92]}
    assert LM.same_ruler(a, {"ruler": [39390.0, 49960.0]})
    assert not LM.same_ruler(a, {"ruler": [45330.0, 50265.0]})
    assert not LM.same_ruler(a, None) and not LM.same_ruler(None, a)


def test_stats_has_b81_research():
    st = json.load(open(os.path.join(ROOT, "wave", "stats.json"), encoding="utf-8"))
    su = st["setups"]
    for tfc in ("1d", "1wk", "intra"):
        assert set(su[tfc]) >= {"L", "S", "B"}
        for sid in ("L", "S", "B"):
            for tr, r in su[tfc][sid].items():
                assert tr in ("順勢", "逆勢") and {"n", "win", "rw", "pass", "worse"} <= set(r)
    assert "text" in st["advice_bt"] and isinstance(st["advice_bt"]["pass_S0"], bool)
    assert set(st["vol2"]["tests"]) == {"V6", "V7u", "V7d", "V8", "V9"}


def test_drift_first_passage():
    sys.path.insert(0, os.path.join(ROOT, "research", "b81"))
    import common as C
    a, b = math.log(110 / 100), math.log(100 / 95)
    assert C.p_first(100, 110, 95, 1, 0.0, 0.01) == pytest.approx(b / (a + b))
    assert C.p_first(100, 110, 95, 1, 0.001, 0.01) > b / (a + b)          # 往上漂移 → 多單先到目標機率變高
    assert C.p_first(100, 90, 105, -1, 0.001, 0.01) < math.log(105 / 100) / (math.log(100 / 90) + math.log(105 / 100))
    q = C.bh({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})
    assert q["a"] == pytest.approx(0.04) and q["d"] == pytest.approx(0.5)
