"""B103 她 11/10 傍晚（@fanny55520 台指期）：37,694→43,108 是清楚的「小 5 段」初推，接下來的壓回三種區
- 小 5 段：40,690、39,129、42,317、40,715、43,108（2 不破起點、3 不是最短、4 不碰 1：40,715 > 40,690）
- ① 強勢橫盤換手 41,873～41,481（日盤低點 41,873、初推 0.236＝41,830、47,607→37,694 的 0.382＝41,481）
- ② 標準對稱 41,040～40,715（初推 0.382、小 4 低點 40,715、小 1 高點 40,690）
- ③ 深層 1 轉 2 40,401～39,762（初推 0.5～0.618）
- 分辨：C-4-c 上攻不能重疊 C-1 低點 45,523；越過 45,523 甚至 46,107＝確立日線級新推升
python -m pytest tests/test_b103_push.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402

SM = T.SMALL + [{"p": 41873, "t": "L"}]                                        # 11/10 日盤壓回到 41,873


def _p(price=42420.0, small=SM):
    return W.structure(T.BIG, small, price, 41700.0, 43000.0, T.LB, first_leg=T.FIRST, full=17015.0)


def test_tx_1110_evening_matches_her_numbers():
    o = _p()
    pu = o["ext3"]["paths"]["push"]
    assert pu["seq"] == [37694, 40690, 39129, 42317, 40715, 43108]
    assert [round(pu["fib"][k]) for k in ("0.236", "0.382", "0.5", "0.618")] == [41830, 41040, 40401, 39762]   # 她的四個數字
    z1, z2, z3 = pu["zones"]
    assert [round(v) for v, _ in z1["lv"]] == [41873, 41830, 41481]            # 她：41,873（0.236＝41,830）～41,481
    assert [round(v) for v, _ in z2["lv"]] == [41040, 40715, 40690]            # 她：41,040～40,715（與小 1 高點 40,690）
    assert [round(v) for v, _ in z3["lv"]] == [40401, 39762]                   # 她：40,401～39,762
    assert pu["where"] == 1 and "第 1 區" in pu["state"]
    assert "初推小 5 段走完" in o["status"] and "第 1 區" in o["status"]
    nx = o["ext3"]["paths"]["next"]
    assert nx["proj"] is None and nx["neck"]                                    # 壓回還在走：先不給新脈動目標，頸線還在


def test_pullback_zones_move():
    assert _p(41000.0, T.SMALL + [{"p": 40950, "t": "L"}])["ext3"]["paths"]["push"]["where"] == 2
    assert _p(40000.0, T.SMALL + [{"p": 39900, "t": "L"}])["ext3"]["paths"]["push"]["where"] == 3


def test_no_push_without_five_waves():
    """只有 a-b 兩段（三段的弱勢反彈）＝不算初推"""
    sm = T.SMALL[:9] + [{"p": 39129, "t": "L"}, {"p": 40845, "t": "H"}, {"p": 39977, "t": "L"}]
    o = W.structure(T.BIG, sm, 40286.0, 41677.0, 43000.0, T.LB, full=17015.0)
    assert o["ext3"]["paths"]["push"] is None


def test_morning_case_keeps_new_pulse_target():
    """11/10 早上（43,108 之後還沒出現壓回轉折）：新脈動目標 43,307 照舊"""
    nx = W.structure(T.BIG, T.SMALL, 42844.0, 41834.0, 43000.0, T.LB, first_leg=T.FIRST, full=17015.0)["ext3"]["paths"]["next"]
    assert round(nx["proj"]) == 43307


def test_tx_1110_night_third_wave():
    """B104 她 11/10 夜盤：42,777 多單 4 口、「半夜發動三浪推升」——41,873 壓回之後創高 43,147＝第 (3) 浪／小 c 啟動；
    初推高點固定在 43,108（41,873 的壓回 0.228 倍 ≥ 0.2），不能把 (2) 併進第 5 段變成「初推還在走」"""
    sm = T.SMALL + [{"p": 41873, "t": "L"}, {"p": 43147, "t": "H"}]
    pu = _p(42527.0, sm)["ext3"]["paths"]["push"]
    assert pu["seq"][-1] == 43108 and pu["pull"] == 41873 and pu["third"] and pu["where"] == 1
    assert "第 (3) 浪" in pu["state"] and "43,147" in pu["state"]
    assert [round(v) for v, _ in pu["targets"]] == [45219, 47287, 50633]
    assert "第 (3) 浪" in _p(42527.0, sm)["status"]


def test_tx_1111_big_mid_small():
    """B105 她 11/11：5-1 推升的大中小——(1) 37,694→43,108、(2) 橫台 41,873～43,147（43,147 只過 39 點、還算橫台）、
    (3) 42,165→44,680；(4) 淺回 44,086（0.236）、標準 43,719（0.382），不能碰 43,108～43,147；(5) 45,463／45,641；
    日線 5-2 推敲 0.382 42,532～42,893、0.5 41,609～41,901、0.618 40,685～40,908（她 42,520～42,884、41,604～41,893、40,680～40,902）"""
    sm = T.SMALL + [{"p": 41873, "t": "L"}, {"p": 43147, "t": "H"}, {"p": 42165, "t": "L"}, {"p": 44680, "t": "H"}]
    o = _p(44495.0, sm)
    sb = o["ext3"]["paths"]["push"]["sub"]
    assert sb["launch"] == 42165 and sb["top3"] == 44680 and sb["plat"] == [41873, 43147] and sb["limit"] == [43108, 43147]
    assert [round(sb["z4"][k]) for k in ("0.236", "0.382")] == [44086, 43719]
    assert [round(v) for v, _ in sb["t5"]] == [45463, 45641]
    assert [(r, int(a + 0.5), int(b + 0.5)) for r, a, b in sb["d52"]] == [(0.382, 42532, 42893), (0.5, 41609, 41901), (0.618, 40685, 40908)]
    assert o["tag"] == "up5" and "第四大波完成" in o["status"] and "45,523" in o["status"] and "46,107" in o["status"]


def test_big_picture_expanded_flat():
    from wave import nest as NE
    piv = [{"p": p, "t": t, "date": d} for p, t, d in ((17015, "L", "2025-04-10"), (28594, "H", "2025-11-04"), (26247, "L", "2025-11-24"),
                                                       (31740, "L", "2026-04-01"), (49240, "H", "2026-06-23"), (39442, "L", "2026-07-29"),
                                                       (50265, "H", "2026-10-07"))]
    piv = sorted(piv, key=lambda q: q["date"])
    piv = [q for k, q in enumerate(piv) if k == 0 or q["t"] != piv[k - 1]["t"]]
    b = NE.big_picture(piv, 44495.0, None, low_after=37694.0)
    assert b and b["her"] == "4" and "擴張平台" in b["scenarios"][1]["title"]
    assert [round(v["price"]) for v in b["scenarios"][1]["levels"]] == [43980, 45463, 37694]
    assert NE.big_picture(piv, 44495.0, None, low_after=40000.0)["her"] is None
