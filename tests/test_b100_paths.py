"""B100 她 11/8 的貼文（@fanny55520 台指期）：60 分結構怎麼接回日線定位——37,694 的級數身分＝三條路徑＋三層驗證
- 路徑 A：日線三段式修正已完成（37,694 離全波段 0.382 37,564 只差 130 點 → 37,694 起漲＝日線大 B 浪 B-a）
- 路徑 B：60 分原切組 3-4-c 運行中（a 37,694→40,690、b 39,129、c 進行中），走完還有 3-5 破底或雙底測試
- 路徑 C：日線五段式（37,694＝C-3 終點、走 C-4），不重疊 C-1 低點 45,523 就還有 C-5 破底
- 第一層：守住壓回低點（39,977；她 39,944～40,000）、實體站回 40,335～40,419（＝40,690→39,977 的 0.5～0.618）
- 第二層：站穩前高 40,690～40,745 與 40,981（c＝0.618 倍 a）；第三層：41,481 收盤接受 → 挑戰 41,677～42,125（日線 5T、c＝a），站穩 42,050＝升級日線級反彈
python -m pytest tests/test_b100_paths.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402

BIG = [{"p": 50265, "t": "H"}, {"p": 45523, "t": "L"}, {"p": 47607, "t": "H"}, {"p": 37694, "t": "L"}]
SMALL = [{"p": p, "t": t} for p, t in ((47607, "H"), (44052, "L"), (45487, "H"), (42050, "L"), (44274, "H"), (42071, "L"),
                                        (42768, "H"), (37694, "L"), (40690, "H"), (39129, "L"), (40845, "H"), (39977, "L"))]
LB = {"big": "日線", "small": "60 分"}


def _p(price=40286.0, small=SMALL, ma5=41677.0):
    return W.structure(BIG, small, price, ma5, 43000.0, LB, full=17015.0)["ext3"]["paths"]


def test_tx_1108_matches_her_numbers():
    p = _p()
    assert p["a"] == [37694, 40690] and p["b"] == 39129 and p["c1"] == 40845 and p["c2"] == 39977
    assert round(p["c"]["0.618"]) == 40981 and p["c"]["1.0"] == 42125            # 她：40,981、42,125
    L1, L2, L3 = p["layers"]
    assert [round(v) for v in L1["zone"]] == [40334, 40418]                      # 她：40,335～40,419
    assert L1["defend"] == 39977 and L1["part"] and not L1["ok"]                 # 40,286：守住 39,977、還沒站回
    assert L2["prev"] == [40690, 40845] and round(L2["f5"]) == 40984 and not L2["ok"]
    assert round(L3["gate"]) == 41481 and L3["hard"] == 42050
    assert [round(v) for v, _ in L3["chal"]] == [41677, 42125]                   # 她：41,677～42,125
    assert [x["k"] for x in p["paths"]] == ["A", "B", "C"]
    txt = "\n".join(p["lines"])
    assert "只差 130 點" in txt and "45,523" in txt and "3-4-c" in txt and "升級日線級反彈" in txt


def test_layers_pass_in_order():
    """站回 40,418 以上＝第一層過；過 40,984＝第二層過；站穩 42,050＝第三層過"""
    assert _p(40500.0)["layers"][0]["ok"] and not _p(40500.0)["layers"][1]["ok"]
    assert _p(41100.0)["layers"][1]["ok"] and not _p(41100.0)["layers"][2]["part"]
    p = _p(42200.0)
    assert p["layers"][2]["ok"]


def test_no_abc_when_b_breaks_low():
    """b 跌破 37,694＝不是 a-b-c（反彈失敗），不出三條路徑"""
    sm = SMALL[:-4] + [{"p": 40690, "t": "H"}, {"p": 37500, "t": "L"}]
    o = W.structure(BIG, sm, 38000.0, 41677.0, 43000.0, LB, full=17015.0)
    assert o["ext3"] is None or o["ext3"]["paths"] is None


def test_only_a_leg_no_paths():
    sm = SMALL[:-3]                                                               # 只有 37,694→40,690，還沒有 b
    assert _p(40500.0, sm) is None
