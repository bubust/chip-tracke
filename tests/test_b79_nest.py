"""B79 多層浪名（學 @fanny55520）：同級數子浪拆解、主要＋備選、證據換數法、關卡、淘汰價位。
python -m pytest tests/test_b79_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import nest as N  # noqa: E402

# 她貼的台指期 60 分轉折（10/06～10/21）：50265 起跌 → 1 48413 → 2 49479 → 3-1～3-5 → 4-a 47033 → 4-b 46136 → 現在
VALS = [50265, 48413, 49479, 48240, 48705, 46456, 47634, 46107, 47033, 46136, 47250]
IDX = [0, 14, 24, 33, 38, 52, 60, 70, 80, 88, 96]


def _pts(vals=VALS, idx=IDX, start="H"):
    out, t = [], start
    for v, i in zip(vals, idx):
        out.append({"i": i, "p": float(v), "t": t, "ci": i + 2})
        t = "L" if t == "H" else "H"
    out[-1]["ci"] = None
    return out


DAILY = {"kind": "impulse", "current": "2", "labels": [{"i": 0, "p": 39385}, {"i": 1, "p": 50265}, {"i": 2, "p": 46107}]}
DATES = ["2026-07-29", "2026-10-06", "2026-10-20"]


def _build(price, vals=None):
    vals = list(vals or VALS)
    vals[-1] = price
    pts = _pts(vals)
    times = [1760000000 + 3600 * k for k in range(100)]
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, "60 分", DAILY, DATES,
                   tdate=lambda i: dt.date(2026, 10, 6) + dt.timedelta(days=i // 8),
                   tlabel=lambda i: f"#{i}")


def test_parse_finds_her_three_readings():
    """C-1-4-c（A-4-c）、ABC 5-3-5 在 46107 結束→B 反彈（B-c）、C 段才走完第 1 段（C-2-c）"""
    cs = N.parse(_pts(), 0, top_k=12)
    paths = {(c["role"], c["path_str"]) for c in cs}
    assert ("C", "A-4-c") in paths and ("C", "B-c") in paths and ("C", "C-2-c") in paths
    a4c = next(c for c in cs if c["path_str"] == "A-4-c")
    # 第 3 段再拆成 3-1～3-5（她的圖）、第 4 段 a、b
    assert [a4c["labels"][k] for k in range(1, 10)] == ["A-1", "A-2", "A-3-1", "A-3-2", "A-3-3", "A-3-4", "A-3-5", "A-4-a", "A-4-b"]
    bc = next(c for c in cs if c["path_str"] == "B-c")
    assert bc["labels"][7] == "A-c-5" and bc["lab1"][7] == "A"      # A＝a-b-c（5-3-5），c 在 46107 結束


def test_impulse_rules_enforced():
    # 第 4 段反彈碰到第 1 段終點（48413）＝1、4 重疊 → 不能再是「五段推動的第 4 段」（楔形允許重疊，可以留著）
    vals = VALS[:-1] + [48500]
    cs = N.parse(_pts(vals), 0, top_k=12)
    assert not any(c["chain"][0]["kind"] == "imp" and c["path_str"].endswith("4-c") for c in cs)
    assert not any(c["top_kind"] == "imp" and c["path"][0] == "4" for c in cs)
    # 第 2 段漲過起點 → 不能是推動浪
    cs = N.parse(_pts([50265, 48413, 50500, 48000]), 0, top_k=12)
    assert not any(c["top_kind"] == "imp" for c in cs)


def test_evidence_switches_primary():
    """她：前提越過下降趨勢線、站穩 0.382 才換成「ABC 已結束、B 反彈」；之前「A 還有第 5 段」優先"""
    lo = _build(47000)               # 趨勢線下方
    assert lo["evidence"] == {"trend": False, "f382": False}
    assert lo["primary"]["path"] == "A-4-c" and lo["alternate"]["path"] == "B-c"
    hi = _build(47700)               # 越過趨勢線＋站上 0.382（47695）
    assert hi["evidence"] == {"trend": True, "f382": True}
    assert hi["primary"]["path"] == "B-c" and not hi["primary"]["with_trend"]


def test_gates_match_her_levels():
    out = _build(47250)
    g = {x["k"]: x for x in out["gates"]}
    # 0.382／0.5／0.618 of 50265→46107＝47695／48186／48677；第 1 段低點領地 48240～48413
    assert round(float(out["fib"]["0.382"])) == 47695 and round(float(out["fib"]["0.5"])) == 48186
    # 前一個反彈高點 47634 跟 0.382 只差 0.13% → 併成第一關
    assert "47,695" in g["第一關"]["t"] and "47,634" in g["第一關"]["t"] and "第 5 段" in g["第一關"]["t"]
    assert "48,186～48,677" in g["第二關"]["t"] and "48,240～48,413" in g["第二關"]["t"]
    assert [x["k"] for x in out["gates"]] == ["前提", "第一關", "第二關", "失敗"]
    assert "46,136" in g["失敗"]["t"] and "46,107" in g["失敗"]["t"]
    tl = out["trendline"]
    assert tl["from"]["p"] == 50265 and tl["to"]["p"] == 49479          # 最平的一條：起點連 2 的高點


def test_rule_levels_and_targets():
    out = _build(47000)
    a4c = out["primary"]
    whys = {r["why"][:6]: r for r in a4c["rules"]}
    assert any(r["price"] == 48413 and r["side"] == "above" and "1、4 浪重疊" in r["why"] for r in a4c["rules"])
    assert any(r["price"] == 46136 for r in a4c["rules"])
    assert whys
    fifth = [t for t in a4c["targets"] if "第 5 段" in t["label"]]
    assert fifth and all(t["price"] < 47000 for t in fifth) and fifth[0]["kind"] == "next"


def test_with_trend_leg_gates():
    """順著大段走的時候：給目標＋轉強價位（不是反彈關卡）"""
    vals = [50265, 48413, 49479, 47900]           # 第 3 段下跌進行中
    pts = _pts(vals, [0, 14, 24, 40])
    out = N.build({"pivots": pts[:-1], "tentative": pts[-1]}, [1760000000 + 3600 * k for k in range(50)], 47900, "60 分")
    assert out["ok"] and out["cur_dir"] == out["dir"] == -1
    ks = [g["k"] for g in out["gates"]]
    assert "轉強" in ks and "第二關" not in ks


def test_anchor_fallback_and_limits():
    pts = _pts()
    out = N.build({"pivots": pts[:-1], "tentative": pts[-1]}, [1760000000 + 3600 * k for k in range(100)], 47250, "60 分")
    assert out["ok"] and out["anchor"]["how"] == "window" and out["anchor"]["p"] == 50265
    assert out["daily_role"] is None
    assert not N.build({"pivots": pts[:2], "tentative": pts[2]}, [0] * 30, 49000)["ok"]


def test_daily_role_mapping():
    assert N.daily_role({"kind": "impulse", "current": "3"}) == "M"
    assert N.daily_role({"kind": "impulse", "current": "4"}) == "C"
    assert N.daily_role({"kind": "correction", "current": "B"}) == "C"
    assert N.daily_role({"kind": "correction", "current": "C"}) == "M"
    assert N.daily_role({"kind": "combo", "current": "X"}) == "C"
    assert N.daily_role(None) is None


def test_parse_is_fast_enough():
    import time
    vals, p, t = [], 100.0, 0
    for k in range(19):
        p *= (0.97 if k % 2 == 0 else 1.02)
        vals.append(round(p, 2))
    t0 = time.time()
    N.parse(_pts(vals, list(range(0, 190, 10))), 0, top_k=6)
    assert time.time() - t0 < 3.0
