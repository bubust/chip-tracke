"""B95 核對網友 the.wave.dog.hk 的推敲（她 11/5 回「推敲正確」）＋她：「46103、45523 不同的判斷落點，可以看出影響推敲日線定位」
- 下跌劇本：日線 3-3-5 平台（6/22 4.8 萬→7/29 3.9 萬→10/7 5 萬→五波下跌），47,607→42,050 也可能只是 (3)-1
- 見底劇本：(3) 浪應該更猛，卻走成「大中小」動能遞減 → 更像 C 浪五段收尾：50,265→45,523 (A)→47,607 (B)→42,050 (C)
- 驗證關卡：44,052（60 分 (1) 浪底，彈過＝走完）、45,484～45,523（0.618＋60 分 (2) 浪 45,487＋日線 (1) 浪）站上就很有機會轉強
- 她的兩張 60 分圖：① 50,265→48,413→49,594→46,107 是 ABC（5-3-5）＝日線 a（三段式，c＝a 43,449）
  ② 50,265→(1)48,413→(2)49,594→(3)46,107→(4)47,555→(5)45,523 五段＝日線 C-1／(1)
python -m pytest tests/test_b95_fork.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
from wave import service as S  # noqa: E402

BIG = [{"p": 50265, "t": "H"}, {"p": 45523, "t": "L"}, {"p": 47607, "t": "H"}, {"p": 42050, "t": "L"}]
SMALL = [{"p": p, "t": t} for p, t in ((47607, "H"), (46126, "L"), (46637, "H"), (44908, "L"), (45597, "H"), (44052, "L"),
                                        (45487, "H"), (42925, "L"), (44069, "H"), (42050, "L"), (44274, "H"))]
FIRST = [{"p": p, "t": t} for p, t in ((50265, "H"), (48413, "L"), (49594, "H"), (46107, "L"), (47555, "H"), (45523, "L"))]
LB = {"big": "日線", "small": "60 分"}


def test_fork_46107_vs_45523_matches_her_numbers():
    o = W.structure(BIG, SMALL, 43300.0, 43884.0, 45224.0, LB, first_leg=FIRST)
    f = o["fork"]
    assert f["a3"] == 46107 and f["l1"] == 45523
    v3, v5 = f["v3"]["targets"], f["v5"]["targets"]
    assert round(v3[0]["price"]) == 43449 and v3[0]["hit"]                   # 她 11/1：三段式 c＝a 43,449（已經跌到）
    assert round(v3[1]["price"]) == 40879 and not v3[1]["hit"]
    assert round(v5[0]["price"]) == 42865 and v5[0]["hit"]                   # 50,265→45,523 的 C＝A 42,865
    assert round(v5[1]["price"]) == 39934 and not v5[1]["hit"]
    txt = "\n".join(o["lines"])
    assert "46,107、45,523 不同的判斷落點" in txt and "c＝a 等幅 43,449（已到）" in txt and "C＝A 等幅 42,865（已到）" in txt
    assert "破底穿頭的 b（中間跌到 45,523）" in txt and "比較像 C 浪五段收尾" in txt      # 大中小遞減＝見底劇本
    assert "現在追沒有肉" in o["lines"][-1]                                    # 進場那行還是最後一行（劇本分頁拿它當計畫）


def test_gate2_band_45484_45523():
    o = W.structure(BIG, SMALL, 43300.0, 43884.0, 45224.0, LB, first_leg=FIRST)
    b = o["gate2"]["band"]
    assert [round(b["lo"]), round(b["hi"])] == [45484, 45523] and not b["passed"]
    labs = {round(v): t for v, t in b["lv"]}
    assert labs[45484].endswith("的 0.618") and labs[45487] == "60 分第 (2) 段高點" and labs[45523] == "日線第 (1) 段低點"
    assert [round(v) for v in o["gate2"]["zone"]] == [44828, 45224, 45523]   # 她 11/4 的受阻區不變
    assert "45,484～45,523 是" in o["lines"][4] and "很有機會轉強" in o["lines"][4] and "大 B 波" in o["lines"][4]


def test_fork_merges_small_wiggles_and_needs_lower_fifth():
    wig = FIRST[:2] + [{"p": 48900, "t": "H"}, {"p": 48700, "t": "L"}] + FIRST[2:]
    o = W.structure(BIG, SMALL, 43300.0, 43884.0, 45224.0, LB, first_leg=wig)
    assert o["fork"]["a3"] == 46107                                          # 小抖動 48,900／48,700 先併掉
    hi5 = FIRST[:3] + [{"p": 45400, "t": "L"}, {"p": 47555, "t": "H"}, {"p": 45523, "t": "L"}]
    assert W.structure(BIG, SMALL, 43300.0, 43884.0, 45224.0, LB, first_leg=hi5)["fork"] is None   # 第 5 段沒破第 3 段＝沒有分歧
    assert W.structure(BIG, SMALL, 43300.0, 43884.0, 45224.0, LB)["fork"] is None


def test_service_first_leg_from_60m_pivots():
    piv = [{"p": 49100, "t": "L"}] + FIRST + [{"p": 47607, "t": "H"}, {"p": 44052, "t": "L"}]
    a60 = {"ok": True, "an": {"pivots": piv}}
    got = S._first_leg(a60, {"p": 50265.0, "t": "H"}, {"p": 45523.0, "t": "L"})
    assert [q["p"] for q in got] == [50265, 48413, 49594, 46107, 47555, 45523]
    assert S._first_leg({"ok": False}, BIG[0], BIG[1]) is None
