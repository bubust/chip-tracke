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
