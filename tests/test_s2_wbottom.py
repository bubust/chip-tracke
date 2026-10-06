"""S2 W底（碗公底・不破前低・盤整後再攻擊）：python -m pytest tests/test_s2_wbottom.py -q"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scanner import screen_s2, strategy_signal_mask

seg = lambda a, b, k: list(np.linspace(a, b, k))


def make(closes, vol=1000):
    n = len(closes)
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=n).strftime("%Y%m%d"),
                         "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": [vol] * n})


BOWL = seg(100, 90, 40) + seg(90, 110, 25)          # 碗底 90 → 第一波攻擊到 110（+22%）
BASE = [108, 107, 106.5, 107.5]                      # 盤整 4 天，不破前低


def run(closes):
    return screen_s2({"T": make(closes)}, {"T": "測試"})


def test_bowl_first_wave_base_then_attack():
    r = run(BOWL + BASE + [111])                     # 今天突破盤整高點
    assert len(r) == 1
    x = r[0]
    assert abs(x["prev_low"] - 90 * 0.99) < 0.01 and abs(x["wave_high"] - 110 * 1.01) < 0.01
    assert x["base_days"] == 5 and abs(x["base_low"] - 106.5 * 0.99) < 0.01 and x["stop"] == x["base_low"]
    assert x["close"] > x["base_high"]


def test_not_attacking_yet():
    assert run(BOWL + BASE + [107]) == []            # 還在盤整區裡


def test_base_breaks_previous_low():
    # 第一波後回檔跌破碗底（前低）→ 不算；均線也會跟著壞，所以另外確認只差「破前低」也不算
    closes = BOWL + BASE + [111]
    df = make(closes)
    i_low = int(np.argmin(df["low"].values[:65]))
    df.loc[len(df) - 3, "low"] = df["low"].iloc[i_low] - 0.5   # 盤整中有一根下影線破前低
    assert screen_s2({"T": df}, {"T": ""}) == []


def test_base_above_first_wave_high_is_not_a_base():
    assert run(BOWL + [108, 112, 113, 112.5] + [114]) == []   # 盤整期間已經過了第一波高點


def test_requires_ma10_gt_ma20_gt_ma60():
    assert run(seg(130, 90, 40) + seg(90, 100, 25) + [99, 98.5, 98, 98.6] + [101]) == []   # 長期空頭裡的反彈


def test_backtest_mask_uses_same_function():
    df = make(BOWL + BASE + [111])
    mask = strategy_signal_mask(df, "S2")
    assert mask[-1] and not mask[-2]
