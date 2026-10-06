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
    # 2026-10-06 用戶規則：上方有前高還沒過 → 目標就是前高（壓力區一）
    assert lv["target"] == lv["pressure1"]["low"] and lv["target_kind"] == "pressure1" and "前高" in lv["target_method"]
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


def test_support_is_latest_confirmed_swing_low_and_old_fields_kept():
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
    """PLAN 第 8 節：強勢延伸 撐＝10 日線、損＝min(20 日線−1ATR, 10 日線−0.5ATR, 價−1.5ATR)；
    其他（10-06 起含前低遠又不強勢）支撐−0.5ATR、至少 2.5ATR；有支撐時停損一定 < 支撐"""
    seen = set()
    for seed in range(80):
        rng = np.random.default_rng(seed)
        vol = 0.01 + 0.03 * (seed % 4)
        n = 30 if seed % 7 == 0 else 160                     # 也測 30 根的短歷史
        closes = list(50 * np.exp(np.cumsum(rng.normal(0.004 * (seed % 3), vol, n))))
        lv = compute_levels(make(closes, spread=vol / 2))
        p, a, st, sup, ss = lv["price"], lv["atr"], lv["stop"], lv["support"], lv["struct_support"]
        assert st and st["price"] < p and "收盤跌破" in st["label"]
        assert st["basis"] in {"support", "floor", "atr", "trail"}           # 10-06 起不再用 risk（前低遠也顯示前低）
        if sup is not None:
            assert st["price"] < sup["price"]                # 停損一定在支撐下面
        c = pd.Series(closes)
        m5, m10, m20 = (c.rolling(k).mean().iloc[-1] for k in (5, 10, 20))
        if st["basis"] == "trail":
            assert ss and p - ss["price"] > 3 * a and p > m5 > m10
            assert sup["kind"] == "ma10" and abs(sup["price"] - m10) < 0.01
            assert abs(st["price"] - min(m20 - a, m10 - 0.5 * a, p - 1.5 * a)) < 0.02
        elif sup is None:
            assert st["basis"] == "atr" and ss is None and abs(st["price"] - (p - 2.5 * a)) < 0.02
        else:
            assert ss is None
            raw = sup["price"] - 0.5 * a
            assert abs(st["price"] - min(raw, p - 2.5 * a)) < 0.02
            assert st["basis"] == ("floor" if raw > p - 2.5 * a else "support")
        seen.add(st["basis"])
        if lv["target"]:
            assert lv["rr"] == round((lv["target"] - p) / (p - st["price"]), 1)
    assert {"floor", "support", "trail"} <= seen


def test_trailing_stop_for_extended_uptrend():
    closes = seg(20, 10, 20) + seg(10, 30, 40)                # 前低 10 之後一路漲到 30：前低遠＋強勢
    lv = compute_levels(make(closes))
    c = pd.Series(closes)
    m10, m20, a = c.rolling(10).mean().iloc[-1], c.rolling(20).mean().iloc[-1], lv["atr"]
    assert lv["stop"]["basis"] == "trail" and lv["support"]["kind"] == "ma10"
    assert abs(lv["support"]["price"] - m10) < 0.01
    assert abs(lv["stop"]["price"] - min(m20 - a, m10 - 0.5 * a, lv["price"] - 1.5 * a)) < 0.02
    assert lv["stop"]["price"] < lv["support"]["price"] < lv["price"]
    assert abs(lv["struct_support"]["price"] - 10 * 0.99) < 0.05 and "20 日線" in lv["stop"]["label"]
    assert lv["ma5"] is not None


def test_pullback_far_support_still_shows_previous_low():
    """10-06 用戶：支撐要顯示前低（10-05 版前低遠又不強勢時撐顯示「—」、停損用現價 −3.5ATR）"""
    closes = seg(20, 10, 20) + seg(10, 30, 40) + seg(30, 27, 5)   # 漲完拉回到 5 日線下：不是強勢
    lv = compute_levels(make(closes))
    a, st, sup = lv["atr"], lv["stop"], lv["support"]
    assert sup is not None and lv["struct_support"] is None and lv["price"] - sup["price"] > 3 * a
    assert st["basis"] == "support" and abs(st["price"] - (sup["price"] - 0.5 * a)) < 0.02 and "部位" in st["label"]


def test_floor_keeps_stop_below_near_support():
    closes = seg(20, 12, 20) + seg(12, 11, 6) + seg(11, 11.3, 6)   # 波段低點 11 就在現價下方不到 1 ATR
    lv = compute_levels(make(closes, spread=0.05))
    p, a, sup, st = lv["price"], lv["atr"], lv["support"], lv["stop"]
    assert p - sup["price"] < a and st["basis"] == "floor"
    assert abs(st["price"] - (p - 2.5 * a)) < 0.02 and st["price"] < sup["price"]


def test_target_prefers_previous_high_then_measured_move():
    # 上方有前高還沒過（回檔後彈到 17，前高 20 在上面）→ 目標＝前高，不跳到等幅
    closes = seg(20, 10, 20) + seg(10, 20, 15) + seg(20, 15, 8) + seg(15, 17, 6)
    lv = compute_levels(make(closes))
    assert lv["measured"] and lv["pressure1"]
    assert lv["target_kind"] == "pressure1" and lv["target"] == lv["pressure1"]["low"]
    # 已經過了前高、上方沒有前高 → 才用等幅
    closes = seg(20, 10, 20) + seg(10, 20, 15) + seg(20, 15, 8) + seg(15, 21, 8)
    lv = compute_levels(make(closes))
    assert lv["pressure1"] is None and lv["target_kind"] == "measured" and lv["measured"]
    m = lv["measured"]
    assert abs(lv["target"] - (m["pullback_low"] + m["high"] - m["start_low"])) < 0.02 and lv["target"] > lv["price"]
    assert "沒有前高" in lv["target_method"]
    # 只有一個前高、回檔太深沒有等幅 → 目標＝前高
    closes = seg(15, 10, 10) + seg(10, 20, 15) + seg(20, 12, 15) + seg(12, 14, 8)
    lv = compute_levels(make(closes))
    assert lv["pressure1"] and not lv["pressure2"] and lv["measured"] is None
    assert lv["target_kind"] == "pressure1" and lv["target"] == lv["pressure1"]["low"]


def test_recent_unconfirmed_high_counts_as_previous_high():
    """2026-10-06 南茂：前天最高 133、這兩天拉回到 127.5，右邊不滿 5 根 → 以前漏掉、顯示「無前高」、目標跳去算 3 ATR"""
    closes = seg(10, 20, 30) + [19.0, 18.5]
    lv = compute_levels(make(closes))
    assert lv["pressure1"] and abs(lv["pressure1"]["low"] - 20 * 1.01) < 0.01
    assert lv["target_kind"] == "pressure1" and lv["target"] == lv["pressure1"]["low"]
    # 今天自己的最高不算前高（還在創新高）
    lv = compute_levels(make(seg(10, 20, 30)))
    assert lv["pressure1"] is None and lv["target_kind"] != "pressure1"


def test_support_uses_nearest_higher_low_not_older_low():
    """2026-10-06 群創：起漲前的低點 48.55（k=3 波段低）才是支撐，k=5 會跳到更早更低的 46.25"""
    closes = seg(20, 10, 20) + seg(10, 15, 8) + [12.0, 13.5, 14.5, 13.8, 13.2, 13.8, 14.3, 14.6]
    lv = compute_levels(make(closes))
    sup = lv["support"]
    assert sup and sup["kind"] == "swing" and abs(sup["price"] - 13.2 * 0.99) < 0.01     # 較近的墊高低點，不是 12.0 × 0.99
    assert lv["stop"]["price"] < sup["price"]


def test_intraday_break_that_closes_back_keeps_previous_low():
    """京元電子 10/06：前低 292（10/01），今天盤中 288.5 收 298 → 不算跌破，支撐還是 292"""
    hi = [330, 321.5, 315.5, 305.5, 304, 298.5, 298, 303.5, 301]
    # 前面墊一段上漲，最後 9 根照京元 9/22～10/06
    base = seg(250, 300, 40)
    df = make(base + [317, 304, 311, 294.5, 294.5, 296, 295.5, 294, 298], spread=0.0)
    n = len(df)
    df.loc[n - 9:, "high"] = hi
    df.loc[n - 9:, "low"] = [312, 302.5, 300.5, 293, 294, 292, 292, 294, 288.5]
    lv = compute_levels(df)
    assert lv["support"]["price"] == 292.0
    # 收盤跌破 292 → 不再是支撐
    df.loc[n - 1, "close"] = 290.0
    lv = compute_levels(df)
    assert lv["support"] is None or lv["support"]["price"] < 290


def test_pullback_low_after_steep_rally():
    """友達：9/18 29.5 → 9/22 高 36.65 → 9/23 回檔低 33.4 → 10/05 高 43.55 → 現在 37.45；33.4 左邊比它低，波段低點抓不到"""
    closes = seg(25, 30, 30) + [33.35, 36.65, 34.7, 34.2, 35.05, 38.55, 38.3, 40.45, 39.05, 37.45]
    df = make(closes, spread=0.0)
    n = len(df)
    df.loc[n - 10:, "high"] = [33.35, 36.65, 36.65, 35.95, 35.8, 38.55, 40.0, 40.85, 43.55, 39.5]
    df.loc[n - 10:, "low"] = [31.8, 34.0, 33.4, 33.75, 33.8, 35.65, 37.8, 38.65, 39.0, 37.15]
    lv = compute_levels(df)
    assert lv["support"]["price"] == 33.4 and lv["pressure1"]["low"] == 43.55 and lv["target"] == 43.55


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


# ── 觀察／持有模式：進場價 −10% 底線（PLAN-POSITIONS.md）─────────────────────
from price_levels import apply_entry_floor


def _lv(price=100.0, stop=95.0, support=97.0, target=110.0, high=None):
    return {"price": price, "high": high if high is not None else price, "stop": {"price": stop, "basis": "support", "label": "x"},
            "support": {"price": support, "kind": "swing", "label": "波段低點", "date": "20261001"},
            "struct_support": None, "target": target, "rr": 1.0, "downside_pct": -5.0}


def test_entry_floor_not_binding_keeps_stop_and_adds_entry():
    lv = _lv(stop=95)
    out = apply_entry_floor(lv, 100, "added")
    assert out["stop"]["price"] == 95 and out["entry"] == {"price": 100, "kind": "added", "floor": 90.0, "pnl_pct": 0.0}
    assert lv.get("entry") is None                                  # 不改原 dict


def test_entry_floor_binds_and_keeps_support_visible():
    out = apply_entry_floor(_lv(price=100, stop=80, support=85, target=120), 100, "cost")
    st = out["stop"]
    assert st["price"] == 90 and st["basis"] == "entry10" and "成本" in st["label"] and not st["breached"]
    assert out["support"]["price"] == 85 and "比支撐 85" in st["label"]           # 10-06：支撐照樣顯示
    assert out["stop_before_floor"]["price"] == 80
    assert out["downside_pct"] == -10.0 and out["rr"] == 2.0


def test_entry_floor_breached_and_no_original_stop():
    out = apply_entry_floor({**_lv(price=85, stop=None, target=120), "stop": None}, 100, "cost")
    assert out["stop"]["price"] == 90 and out["stop"]["breached"] and out["stop"]["label"].startswith("已跌破")
    assert out["rr"] is None and out["downside_pct"] is None and out["alerts"]["stop_hit"]


def test_alerts_use_previous_bar_levels_plus_floor():
    lv = _lv(price=93, stop=88, support=90, target=110, high=94)
    prev = {"date": "20261004", "stop": 94.0, "target": 93.5}
    out = apply_entry_floor(lv, 100, "added", prev)
    assert out["alerts"]["stop_ref"] == 94.0 and out["alerts"]["stop_hit"]          # 93 < 昨天的 94
    assert out["alerts"]["target_ref"] == 93.5 and out["alerts"]["target_hit"]      # 今天最高 94 ≥ 昨天目標 93.5
    out = apply_entry_floor(lv, 120, "cost", {"date": "x", "stop": None, "target": None})
    assert out["alerts"]["stop_ref"] == 108.0 and out["alerts"]["stop_hit"] and not out["alerts"]["target_hit"]
    out = apply_entry_floor(lv, None, "added", {"date": "x", "stop": None, "target": None})
    assert out["alerts"]["stop_ref"] is None and not out["alerts"]["stop_hit"]


def test_falling_price_only_detected_against_previous_stop():
    """回歸：價位用當下價格重算，股價跌下去停損也跟著往下 → 用「現在的停損」永遠抓不到跌破，要用前一根算出的"""
    closes = seg(20, 10, 20) + seg(10, 20, 20) + seg(20, 17, 6) + seg(17, 19.5, 6) + [16.0]   # 回檔到 17 再彈，最後一天大跌破前低
    df = make(closes)
    now, prev = compute_levels(df), compute_levels(df.iloc[:-1])
    assert now["price"] > now["stop"]["price"]                                       # 重算的停損永遠在現價下面
    out = apply_entry_floor(now, None, "added", {"date": prev["date"], "stop": prev["stop"]["price"], "target": prev["target"]})
    assert prev["stop"]["price"] > now["price"] and out["alerts"]["stop_hit"]
