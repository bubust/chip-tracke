"""B91 尾盤追蹤：日線多頭結構、13:15 大盤盤面、盤勢判斷（tail_market.py）：python -m pytest tests/test_tail_market.py -q（不連網）"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tail_market as TM  # noqa: E402


def _zig(highs_lows):
    """[(高, 低) 轉折] → 每段 4 根直線內插的日 K（高＝收×1.002、低＝收×0.998）"""
    pts = []
    for a, b in zip(highs_lows[:-1], highs_lows[1:]):
        pts += list(np.linspace(a, b, 5))[:-1]
    pts.append(highs_lows[-1])
    c = np.array(pts, float)
    return c * 1.002, c * 0.998


def test_struct_hh_hl_ok():
    # 低 90 → 高 100 → 低 95 → 高 110 → 拉回 100（不破 95）＋最後再走 4 根確認 110 是高點
    h, l = _zig([90, 100, 95, 110, 100])
    st = TM.struct_check(h, l)
    assert st["ok"] and not st["bear"] and st["reason"] == ""
    assert abs(st["H1"] - 110 * 1.002) < 0.01 and abs(st["H0"] - 100 * 1.002) < 0.01 and abs(st["L1"] - 95 * 0.998) < 0.01


def test_struct_low_breaks_prior_low():
    h, l = _zig([90, 100, 95, 110, 94])                 # 拉回到 94 < 前低 95
    st = TM.struct_check(h, l)
    assert not st["ok"] and st["reason"] == "低點跌破前低"


def test_struct_high_not_higher():
    h, l = _zig([90, 100, 95, 98, 96])                  # 高 98 < 前高 100，低 96 沒破 95
    st = TM.struct_check(h, l)
    assert not st["ok"] and st["reason"] == "高沒有過前高" and not st["bear"]


def test_struct_bear_and_not_enough_points():
    h, l = _zig([110, 100, 105, 95, 102, 90])          # 高 102 < 105、低 90 < 95 → 空頭
    st = TM.struct_check(h, l)
    assert st["bear"] and not st["ok"]
    st2 = TM.struct_check(np.linspace(10, 20, 30), np.linspace(9, 19, 30))      # 一路漲：沒有波段點
    assert not st2["ok"] and st2["reason"] == "波段點不夠"
    assert TM.struct_check([], [])["reason"] == "波段點不夠"


def test_struct_today_low_breaks_intraday():
    """盤中今天那根的低點跌破前低 → 不合格（網站每次檢查都重算）"""
    h, l = _zig([90, 100, 95, 110, 100])
    ok = TM.struct_check(np.append(h, 101), np.append(l, 96))
    bad = TM.struct_check(np.append(h, 101), np.append(l, 94.5))
    assert ok["ok"] and not bad["ok"] and bad["reason"] == "低點跌破前低"


def test_struct_series_equals_prefix():
    rng = np.random.default_rng(3)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    h, l = c * 1.01, c * 0.99
    ok = TM.struct_series(h, l)[0]
    for t in range(0, 200, 7):
        assert TM.struct_check(h[:t + 1], l[:t + 1])["ok"] == bool(ok[t])


def _daily(n=300, start=40000.0, step=10.0):
    c = start + step * np.arange(n)
    return c * 1.005, c * 0.995, c


def test_market_features_buckets():
    dh, dl, dc = _daily()
    y = dc[-1]
    f = TM.market_features(dh, dl, dc, {"o": y * 1.005, "h": y * 1.006, "l": y * 0.99, "x": y * 0.995, "y": y}, 0.012)
    assert f["M1"] == "−1～0%" and f["M2"] == "開高走低" and f["M7"] == ">0%"
    assert f["M3"] == "下 1/3" and abs(f["pos"] - 0.3125) < 0.002     # (0.995−0.99)/(1.006−0.99)＝0.3125 ＜ 1/3
    assert f["M5"] == "只站上一條" and f["x"] < f["ma20"] and f["x"] > f["ma60"] and f["M6"] == "−3～0%"   # x＝昨收×0.995、5 天前只低 40 點
    assert f["M8"] in ("一般", "高波動")
    assert f["M4"] is None and f["M9"] is None                        # 直線沒有波段點 → 大盤結構算不出來
    zh, zl = _zig([40000, 41000, 40500, 42000, 41200] * 1)
    zc = (zh + zl) / 2
    dh2, dl2, dc2 = np.r_[dh[:-len(zh)], zh], np.r_[dl[:-len(zl)], zl], np.r_[dc[:-len(zc)], zc]
    y2 = dc2[-1]
    f2 = TM.market_features(dh2, dl2, dc2, {"o": y2, "h": y2 * 1.01, "l": y2, "x": y2 * 1.005, "y": y2}, None)
    assert f2["M4"] == "多頭" and f2["M9"] == "多頭·漲"
    # 邊界：剛好 −1% 算 ≤−1%、剛好 +1% 算 ≥+1%
    assert TM._b_chg(-0.01) == "≤−1%" and TM._b_chg(0.01) == "≥+1%" and TM._b_chg(0.0) == "−1～0%"
    assert TM._b_r5(-0.03) == "≤−3%" and TM._b_r5(0.03) == "≥+3%" and TM._b_sox(-0.02) == "≤−2%" and TM._b_sox(0.0) == "−2～0%"


def test_market_features_short_history_and_bad_snap():
    dh, dl, dc = _daily(n=40)
    f = TM.market_features(dh, dl, dc, {"o": 1, "h": 1, "l": 1, "x": 1, "y": None}, None)
    assert f["M5"] is None and f["M8"] is None and f["M7"] is None and f["M6"] is not None
    assert TM.market_features(dh, dl, dc, {"o": 1, "h": 1}, None) is None           # 快照不完整
    assert TM.market_features(dh, dl, dc, {"o": 0, "h": 1, "l": 1, "x": 1}, None) is None
    f = TM.market_features(dh, dl, dc, {"o": 1, "h": 1, "l": 1, "x": 1, "y": "—"}, None)      # 昨收不是數字 → 用日 K 最後收盤
    assert f["y"] == round(float(dc[-1]), 2)
    dh3, dl3, dc3 = _daily()
    dc3[-100] = np.nan                                                                       # 日 K 有空值 → 波動不算
    assert TM.market_features(dh3, dl3, dc3, {"o": 1, "h": 1, "l": 1, "x": 1, "y": 1}, None)["M8"] is None


def test_sox_change_date_mapping():
    d = ["2026-10-29", "2026-10-30", "2026-11-02"]
    c = [100.0, 102.0, 99.96]
    assert abs(TM.sox_change(d, c, "2026-11-02") - 0.02) < 1e-9      # 台灣週一 → 美國週五（11/02 美國那筆還沒收）
    assert abs(TM.sox_change(d, c, "2026-11-03") - (99.96 / 102 - 1)) < 1e-9
    assert TM.sox_change(d[:1], c[:1], "2026-11-03") is None


def test_snap_from_5sec():
    rows = [["09:00:00", "16,408.35"], ["09:00:05", "16,362.27"], ["10:00:00", "16,500.00"], ["13:14:55", "16,300.00"],
            ["13:15:00", "16,310.00"], ["13:20:00", "16,600.00"], ["13:30:00", "16,460.75"]]
    s = TM.snap_from_5sec(rows)
    assert s == {"y": 16408.35, "o": 16362.27, "h": 16500.0, "l": 16300.0, "x": 16310.0}   # 13:15 以後的不算
    assert TM.snap_from_5sec(rows[:3]) is None


def test_verdict():
    rules = [{"family": "M4", "bucket": "空頭", "side": "bad", "pass": True},
             {"family": "M1", "bucket": "≥+1%", "side": "good", "pass": True},
             {"family": "M2", "bucket": "開高走低", "side": "bad", "pass": False}]
    R = {"rules": rules}
    assert TM.verdict(None, R)["label"] == "nodata"
    assert TM.verdict({"M4": "空頭", "M1": "≥+1%"}, R)["label"] == "bad"          # 碰到差的優先
    assert TM.verdict({"M4": "多頭", "M1": "≥+1%"}, R)["label"] == "good"
    assert TM.verdict({"M4": "多頭", "M2": "開高走低"}, R)["label"] == "neutral"   # 沒通過的規則不用
    assert TM.verdict({"M4": "空頭"}, {})["label"] == "neutral"


def test_load_research_missing_file(tmp_path):
    assert TM.load_research(tmp_path / "none.json") == {}
    p = tmp_path / "r.json"
    p.write_text('{"rules": [1]}', encoding="utf-8")
    assert TM.load_research(p) == {"rules": [1]}
    p.write_text("壞掉", encoding="utf-8")
    os.utime(p, (1, 1))
    assert TM.load_research(p) == {}
