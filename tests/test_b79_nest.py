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
    # B83：最前面加「分水嶺」＝大段還在走的數法（A-4-c）這段反彈最多到哪（第 4 段常見回到第 3 段的 0.5＝47,793、碰到 48,413＝1、4 重疊）
    assert [x["k"] for x in out["gates"]] == ["分水嶺", "前提", "第一關", "第二關", "失敗"]
    assert "47,793" in g["分水嶺"]["t"] and "48,413" in g["分水嶺"]["t"] and "A-4" in g["分水嶺"]["t"]
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


# ── 她的貼文時間軸（注意上下文的時間）：照她當時看得到的轉折重跑，看系統的候選有沒有她的說法 ──
HIST = [(50265, "H", 0), (48413, "L", 20), (49479, "H", 40), (48240, "L", 80), (48705, "H", 100), (46456, "L", 140),
        (47356, "H", 147), (46107, "L", 160), (47033, "H", 175), (46136, "L", 195)]


def _at(n, price, t_now):
    pts = [{"i": i, "p": float(v), "t": t, "ci": i + 3} for v, t, i in HIST[:n - 1]]
    pts.append({"i": t_now, "p": float(price), "t": "L" if HIST[n - 2][1] == "H" else "H", "ci": None})
    out = N.build({"pivots": pts[:-1], "tentative": pts[-1]}, [1759800000 + 3600 * k for k in range(t_now + 1)], price, "60 分",
                  DAILY, DATES, tdate=lambda i: dt.date(2026, 10, 7) + dt.timedelta(days=i // 19), tlabel=lambda i: f"#{i}")
    return [x["path"] for x in (out["primary"], out["alternate"], out.get("third")) if x]


def test_her_timeline_replay():
    # 10/16 她：「60 分正在反彈 3-4 或 4」→ 兩個都在系統的候選裡
    c = _at(7, 47356, 147)
    assert any(p.endswith("3-4") for p in c) and any(p.split("-")[-1] == "4" for p in c)
    # 10/19 她：「C-1-3 落底、C-1-4-a」→ 主要＝A-4（第 4 段反彈剛開始）
    assert _at(9, 47033, 175)[0] == "A-4"
    # 10/20 她：主要 C-1-4-b、備選「47033 只是 3-5-2，3-5-3 加速下跌」→ 兩個都在前三名
    c = _at(10, 46136, 195)
    assert "A-4-b" in c and any(p.endswith("5-3") for p in c)
    # 10/21 她：C-1-4-C 或「日線 C-1 落底轉 C-2」→ A-4-c、B-c
    assert set(_at(11, 47100, 205)[:2]) == {"A-4-c", "B-c"}


def test_progress_vs_recount():
    assert N._progress("C-3", "C-4") and N._progress("A-4", "A-4-a") and N._progress("A-4-c", "A-5")
    assert not N._progress("A-4-c", "B-c") and not N._progress("C-5", "A-4")


def test_timeline_replays_without_peeking():
    import numpy as np
    vals = [50265, 48413, 49479, 48240, 48705, 46456, 47356, 46107, 47033, 46136, 47250]
    idx = [0, 20, 40, 80, 100, 140, 147, 160, 175, 195, 205]
    c = np.interp(np.arange(206), idx, vals)
    h, l = c * 1.0005, c * 0.9995
    piv = N.E.zigzag(h, l, 0.006)
    times = [1759800000 + 3600 * k for k in range(206)]
    ends = list(range(60, 206, 19)) + [205]
    tl = N.timeline(piv, h, l, c, times, ends, "60 分", lambda i: DAILY, DATES,
                    tdate=lambda i: dt.date(2026, 10, 7) + dt.timedelta(days=i // 19), tlabel=lambda i: f"#{i}")
    assert len(tl) >= 5 and tl[-1]["primary"] in ("A-4-c", "B-c")
    assert all(r["price"] == round(float(c[e]), 2) for r, e in zip(tl, [e for e in ends][-len(tl):]))
    assert any(r["step"] for r in tl)                      # 有「照原本數法走到下一段」


def test_positioning_matches_her_daily_numbers():
    """她 10/15：45330→50265 當母尺，0.382＝48380、0.5＝47798、0.618＝47215，鐵律底線 45330"""
    prim = {"labels": [{"p": 45330, "date": "2026-09-23"}, {"p": 50265, "date": "2026-10-07"}, {"p": 47850, "date": "2026-10-15"}]}
    alt = {"text": "大 B 波假突破、大 C 波主跌", "invalid": 50265, "invalid_side": "above"}
    x = N.positioning(prim, alt, 47850)
    assert [round(float(v)) for v in x["levels"].values()] == [48380, 47798, 47215] and x["iron"] == 45330
    assert "47,798" in x["lines"][1] and "45,330" in x["lines"][1]
    assert "依序跌破 47,798（0.5）、47,215（0.618）、45,330（起點）" in x["lines"][2]
    # 現在這段跟前一段同方向 → 不是回檔，不給定位
    assert N.positioning({"labels": [{"p": 45330}, {"p": 50265}, {"p": 51000}]}, None, 51000) is None
