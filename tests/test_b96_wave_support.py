"""B96 支撐補波浪價位＋BB 布林三條線：python -m pytest tests/test_b96_wave_support.py -q"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from price_levels import compute_levels, with_wave
from scanner import calc_bb_bands, calc_bb_score
import stock_wave


def make(closes, spread=0.01):
    n = len(closes)
    d = pd.bdate_range("2024-01-01", periods=n).strftime("%Y%m%d")
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": d, "open": c, "high": c * (1 + spread), "low": c * (1 - spread),
                         "close": c, "volume": [1000] * n})


def seg(a, b, n):
    return list(np.linspace(a, b, n + 1)[1:])


def crash_series():
    """像群創：11 漲到 72（中間 26→23 小回檔＝前低 23）、跌到 40、彈到 56、再跌到 38（跌破所有近的前低）"""
    return (seg(20, 11, 40) + seg(11, 26, 60) + seg(26, 23, 6) + seg(23, 72, 80)
            + seg(72, 40, 25) + seg(40, 56, 40) + seg(56, 38, 20))


def Z(price, label="x"):
    return {"price": price, "lo": price, "hi": price, "sources": [{"price": price, "label": label}]}


def test_far_previous_low_switches_to_wave():
    sup = {"price": 22.95, "date": "20260427", "label": "前低", "kind": "swing"}
    s1, s2 = with_wave(sup, [Z(34.53, "大波段 11→72.6 回檔 0.618"), Z(24.18, "回檔 0.786")], 38.0, 2.78)
    assert s1["kind"] == "wave" and s1["price"] == 34.53 and "0.618" in s1["label"] and "22.95" in s1["note"]
    assert s2["price"] == 22.95 and s2["kind"] == "swing"
    assert [w["price"] for w in s2["wave"]] == [24.18]               # 0.5 ATR 內＝匯聚，寫進前低


def test_near_previous_low_stays_support():
    """前低在 3 倍 ATR 內：支撐照舊是前低（10-06 用戶規則），波浪價位當支撐二"""
    sup = {"price": 95.0, "date": "20261001", "label": "前低", "kind": "swing"}
    s1, s2 = with_wave(sup, [Z(97.0), Z(90.0)], 100.0, 2.0)
    assert s1 is sup and s2["kind"] == "wave" and s2["price"] == 97.0
    # 只有跟前低重疊的波浪價位 → 沒有支撐二，前低記匯聚
    s1, s2 = with_wave(sup, [Z(95.4)], 100.0, 2.0)
    assert s2 is None and s1["wave"][0]["price"] == 95.4


def test_wave_outside_window_or_below_far_low_not_used():
    sup = {"price": 50.0, "label": "前低", "kind": "swing"}
    s1, s2 = with_wave(sup, [Z(65.0)], 100.0, 2.0)                    # −35%：超過 30% 不挑
    assert s1 is sup and s2 is None
    s1, s2 = with_wave(sup, [Z(80.0)], 100.0, 2.0)                    # 前低太遠、波浪較近 → 換
    assert s1["price"] == 80.0 and s2 is sup
    s1, s2 = with_wave(None, [Z(90.0)], 100.0, 2.0)                   # 沒有前低
    assert s1["price"] == 90.0 and s2 is None and "沒有" in s1["note"]
    assert with_wave(None, [], 100.0, 2.0) == (None, None)


def test_compute_levels_crash_uses_wave_support():
    df = make(crash_series())
    lv = compute_levels(df)
    p, a, s1, s2 = lv["price"], lv["atr"], lv["support"], lv["support2"]
    assert s1["kind"] == "wave" and s2["kind"] == "swing"
    assert s2["price"] < s1["price"] < p and p - s2["price"] > 3 * a  # 前低太遠才換
    assert abs(s2["price"] - 23 * 0.99) < 0.05
    cand = {x["price"] for x in stock_wave.support_candidates(df["high"], df["low"], df["close"])}
    assert all(x["price"] in cand for x in s1["sources"])
    assert "回檔" in s1["label"] and s1["label"].startswith("波浪：")
    # 停損照舊用前低算，文字不說「支撐」
    assert lv["stop"]["price"] <= s2["price"] + 1e-9 and "收盤跌破支撐" not in lv["stop"]["label"]
    # wave=False（前一根那次）不算波浪
    assert compute_levels(df, wave=False)["support2"] is None


def test_support_candidates_fib_and_equal_leg():
    df = make(crash_series())
    cs = stock_wave.support_candidates(df["high"], df["low"], df["close"])
    labels = " ".join(x["label"] for x in cs)
    assert "大波段" in labels and "0.618" in labels and "等幅" in labels
    eq = next(x for x in cs if "等幅" in x["label"])
    # 從 56.56 起跌＝前一段 72.72→39.6 的跌幅（高低點含 1% 影線）
    assert abs(eq["price"] - (56 * 1.01 - (72 * 1.01 - 40 * 0.99))) < 0.05
    zs = stock_wave.support_zones(df["high"], df["low"], df["close"], 38.0, 2.0)
    assert zs and all(z["hi"] < 38 for z in zs) and zs == sorted(zs, key=lambda z: -z["hi"])
    assert stock_wave.support_candidates([1.0] * 30, [1.0] * 30, [1.0] * 30) == []


def test_bb_bands_match_score():
    df = make([50.0, 50.5] * 10 + [46.0])                            # 平盤後一根大跌，收在下軌下面
    b, s = calc_bb_bands(df), calc_bb_score(df)
    assert b["lower"] < b["mid"] < b["upper"]
    c = float(df["close"].iloc[-1])
    assert abs((c - b["mid"]) / (b["upper"] - b["mid"]) * 10 - s) < 0.1
    assert s < -10 and c < b["lower"]                                 # 跌破下軌 → 分數低於 −10（不夾上下限）
    assert calc_bb_bands(df.iloc[:10]) is None
