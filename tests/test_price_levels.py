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
    assert lv["target"] == lv["pressure2"]["low"] and lv["target_kind"] == "pressure2" and "壓力區二" in lv["target_method"]
    assert "swing_low" in lv["stops"]


def test_levels_uses_thunder_target_and_uptrend_exit():
    closes, vols = thunder_series()
    closes = closes + [28, 29, 30.5, 31]                 # 回檔不破後再攻 → 上漲模式
    vols = vols + [3000] * 4
    lv = compute_levels(make(closes, vols, 0.0))
    assert lv["thunder"]["target"] is not None
    assert lv["target"] == lv["thunder"]["target"] and lv["target_kind"] == "thunder"
    assert lv["mode"].startswith("平地一聲雷")
    assert "volume_low" in lv["stops"]


# ── 2026-10-05 改版：支撐價／停損價／目標價（PLAN-LEVELS.md）───────────────────
from price_levels import measured_move

seg = lambda a, b, k: list(np.linspace(a, b, k))


def test_support_is_latest_confirmed_k5_swing_low_and_old_fields_kept():
    closes = seg(20, 10, 20) + seg(10, 16, 12) + seg(16, 12, 10) + seg(12, 15, 10)
    lv = compute_levels(make(closes))
    ss = lv["struct_support"] or lv["support"]              # 強勢延伸時前低移到 struct_support
    assert ss["kind"] == "swing" and abs(ss["price"] - 12 * 0.99) < 0.05
    for k in ("pressure1", "pressure2", "zones", "target", "target_method", "upside_pct", "stops", "thunder", "ma_near", "notes", "mode"):
        assert k in lv


def test_support_falls_back_to_60_day_low_on_short_history():
    closes = seg(10, 20, 35)                      # 一路漲：沒有波段低點；只有 35 根 → 用全部資料的最低點
    lv = compute_levels(make(closes))
    ss = lv["struct_support"] or lv["support"]
    assert ss["kind"] == "low60" and abs(ss["price"] - 10 * 0.99) < 0.01


def test_stop_formula_and_all_bases():
    """PLAN 第 7 節：強勢延伸用 5／10 日線移動停損；其他支撐 −0.5ATR、至少 1.5ATR、不設上限；任何情況停損 < 支撐"""
    seen = set()
    for seed in range(80):
        rng = np.random.default_rng(seed)
        vol = 0.01 + 0.03 * (seed % 4)
        n = 30 if seed % 7 == 0 else 160                     # 也測 30 根的短歷史
        closes = list(50 * np.exp(np.cumsum(rng.normal(0.004 * (seed % 3), vol, n))))
        lv = compute_levels(make(closes, spread=vol / 2))
        p, a, st, sup = lv["price"], lv["atr"], lv["stop"], lv["support"]
        assert st and st["price"] < p and "收盤跌破" in st["label"]
        assert st["basis"] in {"support", "floor", "atr", "trail"}
        if sup is not None:
            assert st["price"] < sup["price"]                # 停損一定在支撐下面
        c = pd.Series(closes)
        m5, m10 = c.rolling(5).mean().iloc[-1], c.rolling(10).mean().iloc[-1]
        if st["basis"] == "trail":
            ss = lv["struct_support"]
            assert ss and p - ss["price"] > 3 * a and p > m5 > m10
            assert abs(sup["price"] - m5) < 0.01 and abs(st["price"] - m10) < 0.01 and sup["kind"] == "ma5"
        elif sup is None:
            assert st["basis"] == "atr" and abs(st["price"] - (p - 2.5 * a)) < 0.02
        else:
            assert lv["struct_support"] is None
            far_trend = p - sup["price"] > 3 * a and p > m5 > m10 and round(m5, 2) > round(m10, 2)
            assert not far_trend                              # 該進移動停損卻沒進
            raw = sup["price"] - 0.5 * a
            assert abs(st["price"] - min(raw, p - 1.5 * a)) < 0.02
            assert st["basis"] == ("floor" if raw > p - 1.5 * a else "support")
        seen.add(st["basis"])
        if lv["target"]:
            assert lv["rr"] == round((lv["target"] - p) / (p - st["price"]), 1)
    assert {"floor", "support", "trail"} <= seen


def test_trailing_stop_for_extended_uptrend():
    closes = seg(20, 10, 20) + seg(10, 30, 40)                # 前低 10 之後一路漲到 30：前低遠＋強勢
    lv = compute_levels(make(closes))
    c = pd.Series(closes)
    assert lv["stop"]["basis"] == "trail" and lv["support"]["kind"] == "ma5"
    assert abs(lv["support"]["price"] - c.rolling(5).mean().iloc[-1]) < 0.01
    assert abs(lv["stop"]["price"] - c.rolling(10).mean().iloc[-1]) < 0.01
    assert lv["stop"]["price"] < lv["support"]["price"] < lv["price"]
    assert abs(lv["struct_support"]["price"] - 10 * 0.99) < 0.05 and "買回" in lv["stop"]["label"]


def test_pullback_far_support_uses_struct_support_without_cap():
    closes = seg(20, 10, 20) + seg(10, 30, 40) + seg(30, 27, 5)   # 漲完拉回到 5 日線下：不是強勢
    lv = compute_levels(make(closes))
    a, sup, st = lv["atr"], lv["support"], lv["stop"]
    assert sup["kind"] == "swing" and lv["struct_support"] is None and lv["price"] - sup["price"] > 3.5 * a
    assert st["basis"] == "support" and abs(st["price"] - (sup["price"] - 0.5 * a)) < 0.02   # 沒有 3.5ATR 上限


def test_floor_keeps_stop_below_near_support():
    closes = seg(20, 12, 20) + seg(12, 11, 6) + seg(11, 11.3, 6)   # 波段低點 11 就在現價下方不到 1 ATR
    lv = compute_levels(make(closes, spread=0.05))
    p, a, sup, st = lv["price"], lv["atr"], lv["support"], lv["stop"]
    assert p - sup["price"] < a and st["basis"] == "floor"
    assert abs(st["price"] - (p - 1.5 * a)) < 0.02 and st["price"] < sup["price"]


def test_target_measured_move_and_never_pressure1_only():
    closes = seg(20, 10, 20) + seg(10, 20, 15) + seg(20, 15, 8) + seg(15, 17, 6)
    lv = compute_levels(make(closes))
    assert lv["target_kind"] == "measured" and lv["measured"]
    m = lv["measured"]
    assert abs(lv["target"] - (m["pullback_low"] + m["high"] - m["start_low"])) < 0.02 and lv["target"] > lv["price"]
    # 只有一個前高、回檔太深沒有等幅 → 不拿壓力區一當目標，改用 3 ATR
    closes = seg(15, 10, 10) + seg(10, 20, 15) + seg(20, 12, 15) + seg(12, 14, 8)
    lv = compute_levels(make(closes))
    assert lv["pressure1"] and not lv["pressure2"] and lv["measured"] is None
    assert lv["target_kind"] == "atr" and lv["target"] != lv["pressure1"]["low"]
    assert abs(lv["target"] - (lv["price"] + 3 * lv["atr"])) < 0.02


def test_flat_prices_zero_atr_no_crash():
    lv = compute_levels(make([10.0] * 40, spread=0.0))
    assert lv["atr"] == 0.05                      # 下限 現價 × 0.5%
    assert lv["support"] is None and lv["stop"]["basis"] == "atr" and lv["stop"]["price"] == 9.88
    assert lv["target_kind"] == "atr" and lv["target"] == 10.15


def test_measured_move_guards():
    h = np.array([10.0] * 40); l = np.array([9.0] * 40)
    assert measured_move(h, l, 0, 39, 10.0) is None            # 沒有波段點
    c = seg(10, 20, 15) + seg(20, 12, 15)                      # 有高點、但高點前沒有波段低點
    assert measured_move(np.array(c) * 1.01, np.array(c) * 0.99, 0, len(c) - 1, c[-1]) is None


def test_thunder_first_high_below_breakout_no_crash():
    # 突破後第一個波段高點（9.95）沒高過突破點 10：回檔比例算不出來，以前格式化 None 會例外
    rng = np.random.default_rng(1)
    base = list(9.6 + rng.uniform(0, 0.4, 100)); base[-1] = 10.0
    after = [10.5, 9.7, 9.6, 9.7, 9.8, 9.95, 9.9, 9.85, 9.8, 10.1, 10.3, 10.6]
    vols = [1000] * len(base) + [4000] + [1000] * (len(after) - 1)
    df = make(base + after, vols, spread=0.0)
    th = detect_thunder(df)
    assert th is not None and th["retrace"] is None and th["target"] is None and "量不出來" in th["stage"]
    lv = compute_levels(df)
    assert lv["target_kind"] != "thunder" and lv["stop"]
