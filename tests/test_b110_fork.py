"""B110 她 11/15（@fanny55520 台指期「T3 60M MOTHER MAP：43,706 雙路徑裁決」）
- 37,694→44,911 完成日線 5-1；5-2：A 44,911→42,371、B →44,824（候選終點），之後 43,692、44,423、42,956、43,770（收 43,706）
- 主追蹤＝重疊型 5-2-C：C-1 43,692、C-2 44,423、C-3 42,956、C-4 反彈 43,770（越過 C-1 低點＝4 碰到 1 → 只能是終結 C）、還欠 C-5 破底
  強替代＝44,824→42,956 只是較大 5-2-B 的 B-b，接 B-c 往上；再突破守穩 44,824／44,911＝5-2 已在 42,956 走完、直接 5-3
- 往上三關：控制區 43,834～43,890（網站 43,863～43,890）、44,423、44,824／44,911
  往下三道：43,454～43,500（網站 43,459～43,492）、43,272（網站 43,267）、42,956；再下面 42,371、母級共振 42,154～42,496
- 修正：日線把 44,911 確認成高點、後面又有暫定低點 42,371 以後，兩道關卡對不上她的框架（結論卡整個不見）→ 最多拿掉最後 3 個日線轉折；
  60 分轉折只留 40 天 → 接上資料庫裡更早的
python -m pytest tests/test_b110_fork.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402
from wave import service as SV  # noqa: E402

# 正式站 11/16 00:32 快照：60 分轉折（37,694 之後）和 30 分轉折（最後一個是暫定的 43,770）
TAIL = [{"p": p, "t": t} for p, t in ((41873, "L"), (44911, "H"), (42371, "L"), (44824, "H"), (42956, "L"), (43770, "H"))]
FINE = [{"p": p, "t": t} for p, t in ((43147, "H"), (42165, "L"), (43327, "H"), (42712, "L"), (44911, "H"), (43822, "L"), (44555, "H"),
                                      (43057, "L"), (43532, "H"), (42371, "L"), (44034, "H"), (43492, "L"), (44824, "H"), (43692, "L"),
                                      (44423, "H"), (42956, "L"), (43770, "H"))]
r = lambda xs: [int(v + 0.5) for v in xs]                             # noqa: E731


def _o(price, tail=TAIL, fine=FINE):
    return W.structure(T.BIG, T.SMALL + tail, price, 43800.0, 43400.0, T.LB, first_leg=T.FIRST, full=17015.0, fine=fine)


def _sb(o):
    return o["ext3"]["paths"]["push"]["sub"]


def test_tx_1115_overlapping_c_and_her_gates():
    o = _o(43701.0)
    sb = _sb(o)
    fk = sb["fork"]
    assert o["tag"] == "52" and sb["stage"] == "B" and (sb["a_low"], sb["b_hi"]) == (42371, 44824)
    assert [(x["k"], x["p"]) for x in fk["legs"]] == [(1, 43692), (2, 44423), (3, 42956), (4, 43770)]
    assert fk["overlap"] and fk["where"] == "mid" and (fk["c_lo"], fk["g2"]) == (42956, 44423)
    assert [(g["kind"], int(g["lo"] + 0.5), int(g["hi"] + 0.5)) for g in fk["up"]] == [
        ("ctrl", 43863, 43890), ("g2", 44423, 44423), ("g3", 44824, 44911)]                  # 她：43,834～43,890、44,423、44,824／44,911
    assert [(g["kind"], int(g["lo"] + 0.5), int(g["hi"] + 0.5)) for g in fk["down"]] == [
        ("r382", 43459, 43492), ("r618", 43267, 43267), ("lo", 42956, 42956)]                # 她：43,454～43,500、43,272、42,956
    assert fk["deep"]["a_low"] == 42371 and r([fk["deep"]["lo"], fk["deep"]["hi"]]) == [42154, 42496]   # 她：42,371、42,154～42,496
    assert "重疊型 5-2-C" in fk["main"] and "還欠 C-5 破底" in fk["main"] and "B-b" in fk["alt"] and "直接 5-3" in fk["alt"]
    assert len(fk["evo"]) == 3 and "候選終點" in o["status"] and "42,956～44,423" in o["entry"]["t"]


def test_card_mid_wait_short_long():
    c = W.plan_card(_o(43701.0), 43701.0, None, 113.0, 331.0)
    assert "5-2 回檔" in c["pos"][0] and "第 4 腳反彈（42,956→43,770）" in c["pos"][1] and "也可能 B 還沒走完" in c["pos"][1]
    assert "重疊型 C" in c["shape"] and "C-5 還沒走" in c["shape"]
    assert [x["k"] for x in c["plays"]] == ["wait", "short", "long"]
    assert "43,863～43,890、44,423" in c["plays"][1]["t"] and "43,459、43,267" in c["plays"][1]["t"]
    assert "42,371、42,154～42,496" in c["plays"][2]["t"]
    tl = c["tiles"]
    assert (int(tl["up"]["price"] + 0.5), tl["down"]["price"], tl["stop"]["price"]) == (43863, 43492, 44423)
    assert c["steps"] and len(c["steps"]["up"]) == 3 and len(c["steps"]["down"]) == 3 and c["steps"]["src"] == "她 11/15"
    assert r(v for v, _ in c["watch"]["short"]) == [43863, 43890, 44423, 44824, 44911]
    assert 42956 in [v for v, _ in c["watch"]["long"]] and 43459 not in r(v for v, _ in c["watch"]["long"])   # 反彈的 0.382 會移動，不當訊號線
    assert "44,423" in c["flip"] and "啟動 5-3" in c["flip"]


def test_above_c2_high_is_bigger_b():
    """站上 44,423：排除 C-5，B-b 落底、往 44,824 走 B-c（她的第二關）"""
    o = _o(44500.0)
    assert _sb(o)["fork"]["where"] == "bc"
    c = W.plan_card(o, 44500.0, None, 113.0, 331.0)
    assert "站上 44,423" in c["pos"][1] and "較大的 5-2-B" in c["shape"] and [x["k"] for x in c["plays"]] == ["wait", "short", "long"]
    assert (c["tiles"]["up"]["price"], c["tiles"]["down"]["price"], c["tiles"]["stop"]["price"]) == (44824, 44423, 44911)


def test_break_c3_low_is_c5():
    """跌破 42,956：C-5 取得主導，往 42,371、42,154～42,496（她的第三道防線）"""
    o = _o(42900.0)
    fk = _sb(o)["fork"]
    assert fk["n"] == 5 and fk["where"] == "fall" and fk["prev_lo"] == 42956 and fk["down"] == [] and fk["up"][0]["kind"] == "prev"
    c = W.plan_card(o, 42900.0, None, 113.0, 331.0)
    assert "第 5 腳下跌（到 42,900）" in c["pos"][1] and [x["k"] for x in c["plays"]] == ["wait", "long"]
    assert (c["tiles"]["up"]["price"], c["tiles"]["down"]["price"], c["tiles"]["stop"]["price"]) == (42956, 42371, 43770)


def test_break_above_51_top_is_53():
    """再突破 44,911：5-2 已在 42,956 走完、啟動 5-3（不是 5-1 延伸）"""
    o = _o(44950.0)
    sb = _sb(o)
    assert o["tag"] == "52" and sb["stage"] == "3" and sb["fork"] is None and (sb["top"], sb["end52"], sb["pb"]) == (44911, 42956, 42371)
    assert r(v for v, _ in sb["t53"]) == [50173, 54633]                                      # 42,956＋7,217、＋1.618 倍
    c = W.plan_card(o, 44950.0, None, 113.0, 331.0)
    assert "5-3 啟動" in c["pos"][0] and [x["k"] for x in c["plays"]] == ["wait", "long"] and "44,824～44,911" in c["plays"][1]["t"]
    assert (c["tiles"]["down"]["price"], c["tiles"]["stop"]["price"]) == (44911, 42956) and c["steps"] is None


def test_shallow_pullback_is_still_b_and_break_a_low_is_c():
    b = _sb(_o(44700.0, TAIL[:4], FINE[:13]))                                                # 44,824 之後只回 124 點
    assert b["stage"] == "B" and b["fork"] is None and b["b52"]
    c = _sb(_o(42300.0))                                                                     # 跌破 A 低點 42,371＝原本的 C 段
    assert c["stage"] == "C" and c["fork"] is None and c["c_low"] == 42300.0


def test_first_leg_after_b_high():
    """44,824 之後第一腳就跌很深（11/13 午盤 43,692）：C 可能已經開始，只有一腳"""
    fk = _sb(_o(43700.0, TAIL[:4], FINE[:14]))["fork"]
    assert fk and fk["n"] == 1 and fk["g2"] is None and [g["kind"] for g in fk["up"]] == ["g3"] and fk["where"] == "fall"


def test_tiers_inputs_two_extra_daily_pivots():
    """日線：…47,607、37,694、44,911（確認）＋暫定 42,371 → 拿掉最後 2 個才是她的框架；三組裡挑有「5-2」的那一組"""
    big = T.BIG + [{"p": 44911, "t": "H"}, {"p": 42371, "t": "L"}]
    n60 = {"anchor": {"p": 37694.0}}
    sm = {"tentative": {"p": 42371, "t": "L"}}
    pv = T.SMALL + TAIL
    a60 = {"ok": True, "an": {"pivots": pv[:-1], "tentative": pv[-1]}}
    got = list(SV._tiers_inputs(big, n60, {"marks": []}, sm, a60))
    assert [[q["p"] for q in bg[-2:]] for bg, _ in got] == [[37694, 44911], [47607, 37694]]
    outs = [W.structure(bg, small, 43701.0, 43800.0, 43400.0, T.LB, fine=FINE) for bg, small in got]
    assert outs[0] is None and outs[1]["tag"] == "52"                                        # 45,523→47,607→37,694→44,911 不是合理的上漲結構
    assert [SV._tiers_rank(x) for x in outs] == [0, 3]


def test_join_pivots():
    old = [{"time": k, "p": 100.0 + k, "t": "HL"[k % 2]} for k in range(10)]
    new = ([{"time": 5, "p": 999.0, "t": "L"}, old[6], {"time": 6.5, "p": 1.0, "t": "H"}, {"time": 6.6, "p": 2.0, "t": "L"}]   # 窗口開頭比較碎
           + old[7:] + [{"time": 10, "p": 110.0, "t": "H"}])
    out = SV.join_pivots(old, new)
    assert [q["time"] for q in out] == list(range(11)) and out[5]["p"] == 105.0             # 重疊的部分以看得久的那份為準，只接最新的
    assert SV.join_pivots([], new) == new and SV.join_pivots(old[:3], new) == new            # 接不上就只用新的
