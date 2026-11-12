"""B106 她的進場做法回測（research/b106/run.py）的核心規則：刺穿再收回、尖端外停損、三口分批出（保守成交）。
她 11/11 早盤：頸線 42,925 被洗到 42,646、下一根收回 42,957 → 進場；停損放 42,646 外。
python -m pytest tests/test_b106_pierce.py -q（不連網）"""
import importlib.util
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("b106_run", os.path.join(ROOT, "research", "b106", "run.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def _D(bars, a15=100.0, a60=300.0):
    o, h, l, c = (np.array([b[i] for b in bars], float) for i in range(4))
    n = len(bars)
    return {"o": o, "h": h, "l": l, "c": c, "atr15": np.full(n, a15), "atr60": np.full(n, a60)}


def test_pierce_then_reclaim_like_her_1111():
    D = _D([(43000, 43100, 42950, 43050), (43050, 43327, 42646, 42808), (42809, 42990, 42712, 42957), (42956, 43237, 42884, 43204)])
    Y = R.ysp(D, 1)
    k, X = R.find_reclaim(D, Y, 1, 1, 42925.0)
    assert k == 2 and X == 42646                                     # 第 2 根收回、尖端 42,646


def test_too_deep_is_real_break_and_too_shallow_is_touch():
    D = _D([(43000, 43100, 42950, 43050), (43050, 43060, 42500, 42600), (42600, 43000, 42550, 42960)])
    assert R.find_reclaim(D, R.ysp(D, 1), 1, 1, 42925.0) is None      # 刺穿 425 點 > 1 ATR60（300）＝真的跌破
    D = _D([(43000, 43100, 42950, 43050), (43050, 43060, 42915, 42960)])
    assert R.find_reclaim(D, R.ysp(D, 1), 1, 1, 42925.0) is None      # 只刺 10 點 < 0.15 ATR15＝只是碰到


def test_short_side_mirrors():
    D = _D([(40400, 40500, 40300, 40450), (40450, 40690, 40400, 40524), (40536, 40630, 40066, 40162)])
    k, X = R.find_reclaim(D, R.ysp(D, -1), -1, 1, -40584.0)
    assert k == 1 and -X == 40690                                    # 她 11/6：刺過 40,584 到 40,690、同一根收回


def test_three_lots_breakeven_and_trail():
    # 進場 100、停損 90（R＝10）：T1 110 出 1 口 → 停損拉到 100；T2 120 出 1 口 → 停損拉到 110；之後跌回 110
    bars = [(100, 105, 95, 104), (104, 112, 103, 111), (111, 121, 111.5, 119), (119, 119, 109, 109)]
    Y = tuple(np.array([b[i] for b in bars], float) for i in range(4))
    pts, tag, kend = R.sim(Y, 0, 100.0, 90.0, [110.0, 120.0, 130.0])
    assert tag == "trail" and kend == 3 and abs(pts - (10 + 20 + 10) / 3) < 1e-9


def test_same_bar_target_and_stop_counts_stop():
    bars = [(100, 115, 89, 100)]                                     # 同一根碰到停損 90 和 T1 110 → 算停損
    Y = tuple(np.array([b[i] for b in bars], float) for i in range(4))
    pts, tag, _ = R.sim(Y, 0, 100.0, 90.0, [110.0, 120.0, 130.0])
    assert tag == "stop" and pts == -10


def test_research_line():
    import json
    import sys
    sys.path.insert(0, ROOT)
    from wave import service as SV
    st = json.load(open(os.path.join(ROOT, "wave", "stats.json"), encoding="utf-8"))
    x = st.get("entry_b106")
    assert x and x["n"] > 100 and x["vs_rand"]["verdict"] in ("✅", "△", "✗")
    line = SV._research_b106(st)[0]
    assert "刺穿" in line and "三口分批" in line
    assert SV._research_b106({}) == []
    assert SV._research(st)["pierce"] == x
