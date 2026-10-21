"""B76：30 分 K 自己的級數、分 K 價位窗口、多週期一覽、條件式操作建議、融資近 10 天、白話。
python -m pytest tests/test_b76.py -q（不連網）"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import advice as AD, composite as CP, engine as E, intraday as I, levels as LV  # noqa: E402
from wave.plain import plain  # noqa: E402


def _bars(points, n=8, t0=1_790_000_000, step=1800):
    c = []
    for a, b in zip(points[:-1], points[1:]):
        c += list(np.linspace(a, b, n, endpoint=False))
    c.append(points[-1])
    return [{"time": t0 + k * step, "open": x, "high": x * 1.0008, "low": x * 0.9992, "close": x, "volume": 1} for k, x in enumerate(c)]


def test_30m_uses_its_own_theta(monkeypatch):
    bs = _bars([46000, 46600, 46300, 46900, 46500, 47100, 46700, 47300], 9)
    a = I.analyze_tf(30, bs, None, {})
    assert a["ok"]
    base = [p["i"] for p in a["an"]["pivots"]]
    monkeypatch.setitem(E.INTRA, "m", 50.0)            # 改 60 分 K 的 m 不影響 30 分 K
    assert [p["i"] for p in I.analyze_tf(30, bs, None, {})["an"]["pivots"]] == base
    monkeypatch.setitem(E.INTRA30, "m", 50.0)          # 改 30 分 K 自己的 m 才有影響
    monkeypatch.setitem(E.INTRA30, "floor", 0.05)
    assert [p["i"] for p in I.analyze_tf(30, bs, None, {})["an"]["pivots"]] != base


def test_analyze_tf_needs_40_closed_bars():
    bs = _bars([46000, 46500], 20)
    bs[-1]["partial"] = True
    assert I.analyze_tf(30, bs, None, {})["ok"] is False


def test_build_ultra_window_param():
    h = np.linspace(46000, 47000, 80)
    l, c = h * 0.999, h
    an = {"pivots": [], "fib": None}
    lv = LV.build_ultra(h, l, c, 79, an, 50.0, 47000.0, daily={"prev_h": 47600, "prev_l": 46400, "ma20": 45000}, win=0.02, tfn="30 分")
    for z in lv["support"] + lv["resistance"]:
        assert abs(z["price"] / 47000 - 1) <= 0.02
    assert all("30 分" in s["label"] or "昨天" in s["label"] or "整數" in s["label"] or "月線" in s["label"]
               for z in lv["support"] + lv["resistance"] for s in z["sources"])


def test_plain_matches_frontend_text():
    assert plain({"kind": "impulse", "dir": 1, "current": "2"})["title"] == "上漲途中的回檔（第 2 段）"
    assert plain({"kind": "impulse", "dir": 1, "current": "C"})["title"] == "修正的最後一段下跌（C）"
    assert plain({"kind": "correction", "dir": 1, "current": "C"})["title"] == "反彈的最後一段（C）"
    assert plain(None) is None and plain({"kind": "impulse", "dir": 1, "current": "Z"}) is None


# ── 操作建議 ─────────────────────────────────────────────────────────────────
def _snap(dirs, regime="🟡 震盪中性", oh=None, key=None, levels=None, price=47000.0):
    rows = [{"tf": tf, "dir": d} for tf, d in zip(("30m", "60m", "1d", "1wk"), dirs)]
    return {"price": price, "sym": "TWII", "ladder": rows, "context": {"regime": {"label": regime} if regime else None, "oh": oh},
            "waves": {}, "key": key or {}, "levels": levels or {}, "chips": {}, "margin": {}, "global": {}}


def test_exposure_rules():
    assert AD.exposure("🟡 震盪中性", {"60m": 1, "1d": 1, "1wk": 1}, None)[["lo", "hi"][0]] == 40
    up = AD.exposure("🔴 健康多頭", {"60m": 1, "1d": 1, "1wk": 1}, None)
    assert (up["lo"], up["hi"]) == (85, 100)
    hot = AD.exposure("🔴 健康多頭", {"60m": 1, "1d": 1, "1wk": 1}, 0.62)
    assert (hot["lo"], hot["hi"]) == (70, 85) and any("過熱" in w for w in hot["why"])
    dn = AD.exposure("🟢 空頭", {"60m": -1, "1d": -1, "1wk": -1}, None)
    assert (dn["lo"], dn["hi"]) == (0, 10)
    mix = AD.exposure(None, {"60m": 1, "1d": -1, "1wk": -1}, None)
    assert (mix["lo"], mix["hi"]) == (30, 50) and any("暫缺" in w for w in mix["why"])


def test_advice_conditions_order_merge_and_broken():
    key = {"ultra": {"kind": "轉弱點", "price": 46160.0, "side": "below", "dist_pct": -1.8},
           "short": {"kind": "轉強點", "price": 49969.0, "side": "above", "dist_pct": 6.3},
           "swing": {"kind": "轉強點", "price": 49980.0, "side": "above", "dist_pct": 6.3},      # 跟日 K 差 < 0.2% → 合併
           "m30": {"kind": "轉弱點", "price": 46900.0, "side": "below", "broken": True}}
    lv = {"short": {"support": [{"price": 46403.0}], "resistance": [{"price": 47504.0}]}}
    a = AD.build(_snap([1, 1, -1, -1], key=key, levels=lv))
    assert a["ok"] and a["range"]["lo"] == 30 and a["range"]["hi"] == 50
    ups = [c for c in a["conds"] if c["side"] == "up"]
    dns = [c for c in a["conds"] if c["side"] == "down"]
    assert [c["price"] for c in ups] == [47504.0, 49969.0] and "週 K" in ups[1]["label"]
    assert [c["price"] for c in dns] == [46403.0, 46160.0]
    assert all(c["price"] != 46900.0 for c in a["conds"])          # 已經過了的轉折點不當條件
    assert [x["k"] for x in a["lines"]][:2] == ["大方向", "短線"] and a["lines"][-1]["k"] == "風險"


def test_advice_without_levels_and_exception():
    a = AD.build(_snap([0, 0, 0, 0], regime=None))
    assert a["ok"] and a["conds"] == [] and a["cond_note"]
    assert AD.build({"price": None})["ok"] is False


def test_advice_risks_capped():
    s = _snap([1, 1, 1, 1], oh={"overheating": 0.6, "panic": 0.8})
    s["chips"] = {"f_streak": -10, "f5": -5000, "fut_pct": 0.01, "fut_f_oi": -90000}
    s["margin"] = {"ok": True, "streak": 4}
    a = AD.build(s)
    risk = [x for x in a["lines"] if x["k"] == "風險"][0]["t"]
    assert len(a["risks"]) == 5 and "等 2 項" in risk


def test_ladder_summary():
    rows = [{"tf": "30m", "dir": 1}, {"tf": "60m", "dir": 1}, {"tf": "1d", "dir": -1}, {"tf": "1wk", "dir": -1}]
    assert AD.ladder_summary(rows) == "30 分↑、60 分↑、日 K↓、週 K↓ → 大方向還在修正、短線反彈"


def test_service_ladder_dir_from_key_or_tentative():
    from wave import service as S
    waves = {"intra30": {"tentative": {"t": "H"}, "primary": {"kind": "impulse", "dir": 1, "current": "3"}},
             "intra": {}, "small": {"tentative": {"t": "L"}}, "mid": {}}
    key = {"m30": None, "ultra": {"dir": -1, "kind": "轉強點", "price": 1, "side": "above", "dist_pct": 1}, "short": None, "swing": None}
    rows = S._ladder(waves, key, {})
    assert [r["tf"] for r in rows] == ["30m", "60m", "1d", "1wk"]
    assert [r["dir"] for r in rows] == [1, -1, -1, 0]
    assert rows[0]["title"] == "上漲波・第 3 段上漲中" and rows[3]["title"] == "資料不足"


def test_margin_last10_newest_first():
    ch = pd.DataFrame({"date": [f"2026-10-{d:02d}" for d in range(1, 16)], "margin_amt": list(range(100, 115))})
    m = CP.margin_block(ch)
    assert len(m["last10"]) == 10 and m["last10"][0]["date"] == "2026-10-15" and m["last10"][0]["chg"] == 1
    assert m["last10"][-1]["date"] == "2026-10-06"
