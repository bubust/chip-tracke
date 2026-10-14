"""B72 E1：研究候選快觸發名單（near_of 分類、只在掃描記、存檔）"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_strategy as B  # noqa: E402


def _A(bias_today=-25.0, vol=1000.0, n=200):
    """收盤 100 走平 → 最後 15 根每天小跌（不超過 10.5%，不觸發資料保護），收在大約 bias_today 的乖離"""
    c = np.full(n, 100.0)
    target = 100 * (1 + bias_today / 100)
    for _ in range(3):                                         # 60 日均線也會跟著下來，調三次逼近
        ma = c[-60:].mean()
        last = ma * (1 + bias_today / 100)
        c[-15:] = np.linspace(100, last, 16)[1:]
    assert target > 0
    d = pd.DataFrame({"date": pd.bdate_range("2025-10-01", periods=n).strftime("%Y%m%d"), "open": c, "high": c * 1.01,
                      "low": c * 0.99, "close": c, "volume": vol})
    return B._arrays(d)


def _legs(monkeypatch, xs, ys):
    def leg(A, key, j, cache):
        k = A["n"] - 1 - j
        return (xs if key == "S_BIAS" else ys)[k]
    monkeypatch.setattr(B, "_leg", leg)


@pytest.mark.parametrize("xs,ys,vol,kind", [
    ((True, False, False), (False, False, False), 1000.0, "wait_bb"),
    ((False, False, False), (True, False, False), 1000.0, "shallow"),
    ((True, False, False), (False, True, False), 100.0, "illiquid"),
    ((False, False, True), (True, False, False), 100.0, "illiquid"),
    ((True, False, False), (True, False, False), 1000.0, None),          # 兩個都有又在股票池＝會出訊號，不是快觸發
    ((False, False, True), (False, True, False), 1000.0, None),          # 兩個都是之前的，已經過了
    ((True, False, False), (False, False, False), 100.0, None),          # 只差一個條件、又不在股票池 → 不列
])
def test_near_kinds(monkeypatch, xs, ys, vol, kind):
    _legs(monkeypatch, xs, ys)
    A = _A(-17.0 if kind == "shallow" else -25.0, vol)
    r = B.near_of(A, A["n"] - 1)
    assert (r or {}).get("kind") == kind
    if r:
        assert r["why"] == B.NEAR_KINDS[kind] and r["date"] == A["date"][-1]


def test_near_guard_and_shallow_bias_cut(monkeypatch):
    _legs(monkeypatch, (True, False, False), (True, False, False))
    A = _A(-25.0)
    A["c"] = A["c"].copy(); A["c"][-30] *= 1.2                             # 60 天內單日跳 > 10.5%
    A.pop("gap", None)
    assert B.near_of(A, A["n"] - 1)["kind"] == "guard"
    _legs(monkeypatch, (False, False, False), (True, False, False))
    A = _A(-10.0)                                                         # 乖離連 −15% 都不到
    assert B.near_of(A, A["n"] - 1) is None


def test_screen_records_only_real_stocks_and_save(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "NEAR_PATH", str(tmp_path / "near.json"))
    monkeypatch.setattr(B, "signal_at", lambda A, i, name=None, cache=None: False)
    monkeypatch.setattr(B, "near_of", lambda A, i: {"kind": "wait_bb", "why": "x", "bias_min": -30.0, "date": A["date"][i],
                                                    "close": 1.0, "vol20": 1.0, "bias_date": None, "bb_date": None})
    n = 200
    df = pd.DataFrame({"date": pd.bdate_range("2025-10-01", periods=n).strftime("%Y%m%d"), "open": 50.0, "high": 51.0,
                       "low": 49.0, "close": 50.0, "volume": 1000.0})
    B.near_reset()
    B.screen_best({"1234": df}, {"1234": "甲"})
    B.screen_best({"BT": df}, {"BT": ""})                                  # K 線回測不記
    old = df.iloc[:-1]
    B.screen_best({"5678": old}, {"5678": "乙"})                           # 資料停在前一天的不算今天
    out = B.near_save("20261014")
    assert [x["stock_id"] for x in out["items"]] == ["1234"] and out["counts"]["wait_bb"] == 1
    assert json.load(open(tmp_path / "near.json", encoding="utf-8"))["items"][0]["name"] == "甲"
    B.near_reset()
    assert B.near_save("20261015")["items"] == [] and B.near_load()["scan_day"] == "20261015"
