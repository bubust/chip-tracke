"""B112 大跌後結論卡的 C 段：11/16 一天跌 2,949 點、最低 40,714，5-2 的三個大買點全到
- C 段量度加 1.618 倍 A＝44,824 − 1.618×2,540＝40,714（剛好是當天低點），到了的標「已到」
- 上方格子＝已經跌破、離現價最近的那一層（41,303）；下方格子＝現價下面最近的一層（40,715）；改判線＝B 段高點 44,824
python -m pytest tests/test_b112_deep_c.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b110_fork as B  # noqa: E402

TAIL = B.TAIL + [{"p": 40714, "t": "L"}]                              # 44,824→42,956→43,770→40,714（60 分暫定低點）
FINE = B.FINE + [{"p": 40714, "t": "L"}]


def _card(price):
    o = B._o(price, TAIL, FINE)
    return B._sb(o), W.plan_card(o, price, None, 150.0, 500.0)


def test_tx_1116_all_three_zones_hit():
    sb, c = _card(41067.0)
    assert sb["stage"] == "C" and sb["fork"] is None and sb["c_low"] == 40714 and [z["hit"] for z in sb["z52"]] == [True, True, True]
    assert [int(v + 0.5) for v, _ in sb["c52"]] == [43254, 42284, 40714]                     # 0.618、1、1.618 倍 A
    assert "三個大買點都到了" in c["pos"][1] and "40,714" in c["pos"][1]
    assert c["plays"][0]["tag"] == "不追空" and c["plays"][0]["t"].count("（已到）") == 3
    assert "最深這一區 40,451～40,715 守不守是關鍵" in c["plays"][1]["t"]
    tl = c["tiles"]
    assert (tl["up"]["price"], tl["up"]["name"]) == (41302.5, "大買點 0.5") and tl["down"]["price"] == 40715 and tl["stop"]["price"] == 44824


def test_tiles_follow_price():
    _, lo = _card(40600.0)                                                                   # 再破低：上方＝剛跌破的 40,714、下方＝40,451
    assert (int(lo["tiles"]["up"]["price"] + 0.5), int(lo["tiles"]["down"]["price"] + 0.5)) == (40714, 40451)
    _, hi = _card(41500.0)                                                                   # 站回 41,303：上方換成 42,154、下方 41,303
    assert (int(hi["tiles"]["up"]["price"] + 0.5), int(hi["tiles"]["down"]["price"] + 0.5)) == (42154, 41303)
