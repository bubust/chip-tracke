"""B119 跟進她 11/17（@fanny55520 台指期）
- 早上：情境 A（主候選）41,484→40,616 已走完 5-2-C-5，41,627 仙人指路、40,616→40,637→40,875 墊高；
  情境 B（威脅）橫台是 C-4 箱體，結算前再踹最後一腳 C-5 黃金坑 40,313～40,451，站回收上 40,616 就是很漂亮的買點。
- 5-3 要過關：41,500～41,700 保留站穩、第二目標 41,650～41,745、站穩 41,745 後看 42,134～42,349，都過才開啟 5-3。
- 她 2 口多單 40,356（早上殺到 40,005），41,215、41,039 各平一口。之後盤中再跌到 39,761（跌破 40,616、40,005）。
- 網站：C-5 之後站上 C-4 高點 41,465＝C 段走完（done）；之後又跌破 C-5 低點＝C-5 延伸（ext）——以前全部併成「C-5 到最低點」
python -m pytest tests/test_b119_c5_phase.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b110_fork as B  # noqa: E402
import test_b113_settle_c5 as C  # noqa: E402

H = [{"p": 41828, "t": "H"}]


def _o(price, tail):
    return W.structure(C.T.BIG, C.SMALL + tail, price, 43800.0, 43400.0, C.T.LB, first_leg=C.T.FIRST, full=17015.0, fine=C.FINE)


def test_done_then_53_gates():
    """C-5 40,616 之後反彈 41,828 站上 C-4 高點 41,465＝C 段走完（她的情境 A），5-3 三關"""
    o = _o(41700.0, C.TAIL + H)
    cg = B._sb(o)["cleg"]
    assert cg["phase"] == "done" and cg["c5a"] == 40616 and cg["reb"] == 41828
    g = cg["gates53"]
    assert len(g) == 2 and (g[0]["lo"], g[0]["hi"]) == (41465, 41828)                       # 她：41,500～41,700（只有一個反彈高點）
    assert (int(g[1]["lo"] + 0.5), g[1]["hi"]) == (42154, 42371)                            # 她：42,134～42,349（0.382 42,257 在它上面，不列）
    o2 = _o(41700.0, C.TAIL + [{"p": 41627, "t": "H"}, {"p": 40637, "t": "L"}] + H)          # 她早上：41,627 仙人指路、40,637 墊高、再到 41,828
    g2 = B._sb(o2)["cleg"]["gates53"]
    assert [(x["lo"], x["hi"]) for x in g2[:2]] == [(41465, 41627), (41828, 41828)]          # 她：41,500～41,700、41,650～41,745
    c = W.plan_card(o, 41700.0, None, 190.0, 464.0)
    assert c["plays"][0]["tag"] == "5-3 還沒開" and "三關都過才開啟 5-3" in c["plays"][0]["t"]
    assert (c["tiles"]["up"]["price"], c["tiles"]["down"]["price"]) == (41828, 40616) and "C-5 還在延伸" in c["flip"]


def test_extended_c5_after_breaking_low():
    """站上 C-4 高點之後又跌破 40,616 到 40,040＝C-5 延伸（她的情境 B）：站回 40,616 才是買點，下面看第二層"""
    o = _o(40206.0, C.TAIL + H + [{"p": 40040, "t": "L"}])
    sb = B._sb(o)
    cg = sb["cleg"]
    assert cg["phase"] == "ext" and cg["c5a"] == 40616 and cg["legs"][-1]["p"] == 40040
    c = W.plan_card(o, 40206.0, None, 190.0, 464.0)
    assert "站回 40,616 才是買點" in c["pos"][2] and any(x["tag"] == "站回才做多" for x in c["plays"])
    tl = c["tiles"]
    assert (tl["up"]["price"], tl["down"]["price"], tl["stop"]["price"]) == (40616, 39977, 41828)    # 第二層上緣 39,977（她 39,238～39,977）
    assert (int(sb["z786"]["lo"] + 0.5), sb["z786"]["hi"]) == (39238, 39977)


def test_box_unchanged_when_no_break_above_c4():
    o = _o(41165.0, C.TAIL)
    assert B._sb(o)["cleg"]["phase"] == "box"
