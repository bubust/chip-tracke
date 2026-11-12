"""B107 她 11/12（@fanny55520 台指期）：5-1 在 44,911 結束、進日線 5-2
- 壓回到 42,371，跌破 (1) 高點 43,108（4 不能碰 1）→ 不是 5-1-4，44,911 是 5-1 終點（夜盤 44,680→44,094→44,911 時間壓縮走完 (3)(4)(5)）
- 5-2 三個大買點＝37,694→44,911（7,217 點）的 0.382／0.5／0.618：42,154（旁邊 30 分前低 42,165）、41,303、40,451（旁邊初推小 4 低點 40,715）
  她：42,165、41,303、40,451～40,715
- 5-2-A 44,911→42,371（她：最後一腳測 42,154～42,390）；5-2-B 反彈 0.382 43,341、0.5 43,641、0.618 43,941
python -m pytest tests/test_b107_52.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402

FINE = [{"p": p, "t": t} for p, t in ((43147, "H"), (42165, "L"), (43327, "H"), (42712, "L"), (44911, "H"), (43822, "L"),
                                      (44555, "H"), (43057, "L"), (43532, "H"), (42371, "L"))]       # 網站 30 分轉折（11/10 夜盤～11/12 夜盤）


def _o(price, tail, fine=FINE):
    sm = T.SMALL + [{"p": 41873, "t": "L"}, {"p": 44911, "t": "H"}] + tail
    return W.structure(T.BIG, sm, price, 43364.0, 43818.0, T.LB, first_leg=T.FIRST, full=17015.0, fine=fine)


def test_tx_1112_51_done_and_52_buy_zones():
    o = _o(43613.0, [{"p": 42371, "t": "L"}])
    sb = o["ext3"]["paths"]["push"]["sub"]
    assert sb["done"] and sb["top"] == 44911 and sb["a_low"] == 42371
    z = {x["r"]: x for x in sb["z52"]}
    assert int(z[0.382]["v"] + 0.5) == 42154 and z[0.382]["near"] == 42165     # 她 42,165
    assert int(z[0.5]["v"] + 0.5) == 41303 and z[0.5]["near"] is None           # 她 41,303
    assert int(z[0.618]["v"] + 0.5) == 40451 and z[0.618]["near"] == 40715     # 她 40,451～40,715
    assert [int(v + 0.5) for v, _ in sb["b52"]] == [43341, 43641, 43941]
    assert o["tag"] == "52" and "5-1 在 44,911 結束" in o["status"] and "5-2-B 反彈中" in o["status"]
    assert "42,165" in o["entry"]["t"] and "0050" in o["entry"]["t"]


def test_52a_still_running_without_rebound():
    o = _o(42450.0, [])
    sb = o["ext3"]["paths"]["push"]["sub"]
    assert sb["done"] and sb["b_hi"] is None and sb["b52"] == [] and "5-2-A 進行中" in o["status"]


def test_pullback_above_wave1_high_is_still_wave4():
    """壓回還在 (1) 高點 43,108 上面＝還是 5-1-4（她早上：看 0.236～0.382 有沒有來）"""
    sb = _o(43900.0, [])["ext3"]["paths"]["push"]["sub"]
    assert not sb.get("done") and sb["pb"] == 43900


def test_only_lows_inside_51_count():
    """5-2 自己跌出來的低點（42,371）不能當大買點旁邊的前低"""
    sb = _o(43613.0, [{"p": 42371, "t": "L"}], fine=None)["ext3"]["paths"]["push"]["sub"]
    assert sb["z52"][0]["near"] is None
