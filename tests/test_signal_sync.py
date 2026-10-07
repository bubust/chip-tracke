"""「外資投信同步買」要當天外資、投信都買超（PLAN-DEEP2 §2）：python -m pytest tests/test_signal_sync.py -q"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chip_tracker_v2 as ct

T = dict(ct.DEFAULT_THRESHOLDS)


def _sig(**kw):
    base = dict(cum7_whale=12326, concentration=0.5, cum7_retail=0, cum7_foreign=12000, cum7_trust=200,
                consecutive_buy=1, T=T)
    base.update(kw)
    return ct.classify_signal(**base)


def test_trust_sold_today_is_not_sync():
    # 2026-10-07 用戶回報那列：外資 +9,505、投信 −24、7 日累計 +12,326
    s = _sig(today_foreign=9505, today_trust=-24)
    assert "同步" not in s["title"]
    assert s["title"] == "法人溫和買進" and s["level"] == 1


def test_both_bought_today_is_sync():
    s = _sig(today_foreign=9505, today_trust=30)
    assert s["title"] == "外資投信同步買" and s["level"] == 2


def test_sync_build_needs_today_too():
    s = _sig(consecutive_buy=5, today_foreign=100, today_trust=10)
    assert s["title"] == "外資投信同步建倉"
    s = _sig(consecutive_buy=5, today_foreign=100, today_trust=0)
    assert s["title"] != "外資投信同步建倉"


def test_foreign_sold_today_falls_through_to_retail_rule():
    s = _sig(cum7_retail=300, today_foreign=-5, today_trust=40)
    assert s["title"] == "法人買散戶跟進"


def test_today_unknown_keeps_old_behavior():
    assert _sig()["title"] == "外資投信同步買"


def test_reclassify_records_fixes_stored_title(monkeypatch):
    monkeypatch.setattr(ct, "get_thresholds", lambda: dict(T))
    rows = [{"cum7_whale": 12326, "concentration_index": 0.5, "cum7_retail": 0, "cum7_foreign": 12000,
             "cum7_trust": 200, "consecutive_buy": 1, "foreign_lots": 9505, "trust_lots": -24,
             "signal_emoji": "🟢", "signal_title": "外資投信同步買", "signal_level": 2},
            {"cum7_whale": 1, "signal_title": "舊的", "signal_level": 0}]   # 缺欄位 → 保留
    out = ct.reclassify_records(rows)
    assert out[0]["signal_title"] == "法人溫和買進" and out[0]["signal_level"] == 1
    assert out[1]["signal_title"] == "舊的"


def test_reclassify_handles_nan(monkeypatch):
    monkeypatch.setattr(ct, "get_thresholds", lambda: dict(T))
    rows = [{"cum7_whale": float("nan"), "concentration_index": 0.5, "cum7_retail": 0, "cum7_foreign": 1,
             "cum7_trust": 1, "consecutive_buy": 0, "foreign_lots": 1, "trust_lots": 1, "signal_title": "x"}]
    assert ct.reclassify_records(rows)[0]["signal_title"] == "x"
