"""關鍵價位 / 平地一聲雷：python -m pytest tests/test_price_levels.py -q"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from price_levels import detect_thunder, compute_levels


def make(closes, vols=None, spread=0.01):
    n = len(closes)
    d = pd.bdate_range("2025-01-01", periods=n).strftime("%Y%m%d")
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": d, "open": c, "high": c * (1 + spread), "low": c * (1 - spread),
                         "close": c, "volume": vols if vols is not None else [1000] * n})


def thunder_series():
    rng = np.random.default_rng(1)
    base = list(9.6 + rng.uniform(0, 0.4, 100))          # 盤整 9.6~10.0（約 4%）
    base[-1] = 10.0                                      # 盤整上緣 = 10
    rally = list(np.linspace(11, 30, 12))                # 帶量突破，漲到 30
    pull = [29, 27.5, 26, 25.2, 25.0, 26, 27]            # 回檔到 25 再彈
    closes = base + rally + pull
    vols = [1000] * len(base) + [4000] + [2500] * (len(rally) - 1) + [1200] * len(pull)
    return closes, vols


def test_thunder_target_example_30_minus_10_plus_25():
    closes, vols = thunder_series()
    df = make(closes, vols, spread=0.0)
    th = detect_thunder(df)
    assert th is not None
    assert th["base_top"] == 10.0 and th["high"] == 30.0 and th["pullback_low"] == 25.0
    assert th["target"] == 45.0                        # 30 − 10 + 25
    assert th["retrace"] == 0.25 and "回檔" in th["stage"]


def test_thunder_rejects_deep_retrace_and_weak_volume():
    closes, vols = thunder_series()
    deep = closes[:-7] + [25, 20, 16, 15, 16, 17, 17.5]   # 回檔到 15：(30−15)/(30−10)=0.75 > 0.618
    th = detect_thunder(make(deep, vols, 0.0))
    assert th and th["target"] is None and "過深" in th["stage"]
    weak = [1000] * len(vols)                              # 沒帶量
    assert detect_thunder(make(closes, weak, 0.0)) is None


def test_thunder_requires_flat_base():
    closes, vols = thunder_series()
    wide = list(np.linspace(6, 10, 100)) + closes[100:]   # 盤整區間 66%，不算盤整
    assert detect_thunder(make(wide, vols, 0.0)) is None


def test_levels_pressure_zones_ordered_above_price():
    # 先後出現 3 個高點 20、17、15，然後跌到 12 再回到 13
    seg = lambda a, b, k: list(np.linspace(a, b, k))
    closes = seg(10, 20, 15) + seg(20, 11, 15) + seg(11, 17, 12) + seg(17, 12, 12) + seg(12, 15, 10) + seg(15, 12, 10) + seg(12, 13, 8)
    lv = compute_levels(make(closes))
    assert lv["pressure1"]["low"] < lv["pressure2"]["low"]
    assert 14.5 < lv["pressure1"]["low"] < 15.5 and 16.5 < lv["pressure2"]["low"] < 17.5
    assert lv["target"] == lv["pressure2"]["low"] and "第二壓力" in lv["target_method"]
    assert "swing_low" in lv["stops"]


def test_levels_uses_thunder_target_and_uptrend_exit():
    closes, vols = thunder_series()
    closes = closes + [28, 29, 30.5, 31]                 # 回檔不破後再攻 → 上漲模式
    vols = vols + [3000] * 4
    lv = compute_levels(make(closes, vols, 0.0))
    assert lv["thunder"]["target"] is not None
    assert lv["mode"].startswith("平地一聲雷")
    assert "volume_low" in lv["stops"]
