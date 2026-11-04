"""B93 她 11/4 的貼文（@fanny55520 台指期）：多週期逐層驗證——60 分「大、中、小」＋兩道關卡；同一套帶進個股（日 K 兩層級數）
- 47,607 起跌到 42,050：大 47,607→44,052（3,555）、中 45,487→42,925（2,562）、小 44,069→42,050（2,019）＝三段式動能逐漸收斂
- 第一道關（安全門）44,052（60 分 (1) 浪低點、1、4 不重疊）＋0.382 44,173＋日線 5T 44,154：彈過並站穩＝60 分跌勢走完五段、轉入修正
- 第二道關＝日線 (1) 浪 45,523：日線 (4) 在 44,829（0.5）～45,357（日線 10T）～45,523 受阻 → 日線 (5) 再破 42,050；越過也先當大 B 波
- 短線看 44,173 有沒有真過，壓回第二隻腳在 0.382～0.5 才做多，去拼 0.5（44,829）；追多沒有肉
python -m pytest tests/test_b93_tiers.py -q（不連網）"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_wave as W  # noqa: E402

BIG = [{"p": 50265, "t": "H"}, {"p": 45523, "t": "L"}, {"p": 47607, "t": "H"}, {"p": 42050, "t": "L"}]
SMALL = [{"p": p, "t": t} for p, t in ((47607, "H"), (46126, "L"), (46637, "H"), (44908, "L"), (45597, "H"), (44052, "L"),
                                        (45487, "H"), (42925, "L"), (44069, "H"), (42050, "L"), (44195, "H"))]
LB = {"big": "日線", "small": "60 分"}


def test_tx_1104_matches_her_numbers():
    o = W.structure(BIG, SMALL, 44140.0, 44154.0, 45357.0, LB)
    sm = o["small"]
    assert [x["p"] for x in sm["seq"]] == [47607, 44052, 45487, 42925, 44069, 42050]          # 併成大、(2)、中、(4)、小
    assert sm["legs"] == [3555, 2562, 2019] and sm["contract"] and sm["overlap"]              # 收斂；44,069 碰到 44,052＝楔形
    g1 = o["gate1"]
    assert [round(g1["lo"]), round(g1["hi"])] == [44052, 44173] and any(t == "日線 5 均" for _, t in g1["lv"])
    assert g1["touched"] and not g1["passed"] and o["tag"] == "at1"                            # 44,140：過了 44,052、還沒過 44,173
    g2 = o["gate2"]
    assert g2["price"] == 45523 and [round(v) for v in g2["zone"]] == [44828, 45357, 45523]    # 她：44,829～45,357～45,523
    txt = "\n".join(o["lines"])
    assert "大 3,555、中 2,562、小 2,019" in txt and "動能逐漸收斂" in txt and "44,829～45,357～45,523" in txt
    assert "大 B 波" in txt and o["entry"] is None and "現在追沒有肉" in o["lines"][-1]


def test_entry_after_0382_really_passed():
    """44,173 真過以後：等這段反彈的 0.382～0.5 第二隻腳，目標 0.5（44,829）"""
    o = W.structure(BIG, SMALL[:-1] + [{"p": 44600, "t": "H"}], 44500.0, 44154.0, 45357.0, LB)
    assert o["gate1"]["passed"] and o["tag"] == "4"
    e = o["entry"]
    assert e["zone"] == [43325.0, 43625.9] and round(e["target"]) == 44828 and "第二隻腳" in e["t"]
    assert "43,325～43,626" in e["t"] and "44,829" in e["t"]


def test_second_gate_passed_is_b_wave():
    o = W.structure(BIG, SMALL[:-1] + [{"p": 45700, "t": "H"}], 45650.0, 45000.0, 45357.0, LB)
    assert o["gate2"]["passed"] and o["tag"] == "B" and "大 B 波" in o["status"]


def test_only_two_legs_and_not_broken_first_low():
    big = [{"p": 49240, "t": "H"}, {"p": 39442, "t": "L"}, {"p": 50265, "t": "H"}, {"p": 42050, "t": "L"}]
    small = [{"p": 50265, "t": "H"}, {"p": 45523, "t": "L"}, {"p": 47607, "t": "H"}, {"p": 42050, "t": "L"}]
    o = W.structure(big, small, 44140.0)
    assert o["case"] == "2" and o["gate2"] is None and o["small"]["n_seg"] == 3
    assert [round(o["gate1"]["lo"]), round(o["gate1"]["hi"])] == [45188, 45523]                 # 小級 (1) 45,523＋0.382
    assert "還沒跌破 39,442" in o["lines"][0] and "先告一段落" in o["lines"][3]


def test_uptrend_mirror():
    """漲勢（大級第 3 段創高）：看拉回的關卡"""
    big = [{"p": 100, "t": "L"}, {"p": 150, "t": "H"}, {"p": 130, "t": "L"}, {"p": 170, "t": "H"}]
    small = [{"p": p, "t": t} for p, t in ((130, "L"), (150, "H"), (140, "L"), (165, "H"), (158, "L"), (170, "H"))]
    o = W.structure(big, small, 168.0)
    assert o["dir"] == 1 and o["case"] == "3" and o["small"]["legs"] == [20, 25, 12] and not o["small"]["contract"]
    assert round(o["gate1"]["hi"]) == 155 and round(o["gate1"]["lo"]) == 150 and o["gate1"]["far"] == 150   # 拉回要守的
    assert o["tag"] == "below1" and "拉回" in o["status"]


def _daily(prices):
    a = np.array(prices, float)
    d = pd.bdate_range("2025-06-02", periods=len(a)).strftime("%Y%m%d")
    return pd.DataFrame({"date": d, "open": a, "high": a * 1.005, "low": a * 0.995, "close": a, "volume": 1000.0})


def test_analyze_daily_on_a_stock_like_series():
    seg = lambda a, b, n: list(np.linspace(a, b, n))[1:]                    # noqa: E731
    p = [100.0] + seg(100, 160, 60) + seg(160, 120, 25) + seg(120, 170, 30) + seg(170, 140, 12) + seg(140, 150, 5) \
        + seg(150, 128, 10) + seg(128, 136, 4) + seg(136, 124, 6) + seg(124, 131, 3)
    o = W.analyze_daily(_daily(p))
    assert o and o["labels"]["big"].startswith("中級") and o["dir"] == -1
    b = o["big"]                                                            # 170→140＝(1)、→150＝(2)、150 起跌＝(3) 破 140
    assert round(b["T"]) == 171 and round(b["L1"]) == 139 and round(b["H2"]) == 151 and b["ext"] < b["L1"] and o["case"] == "3"
    assert [round(x["p"]) for x in o["small"]["seq"]] == [151, 127, 137, 123] and o["small"]["n_seg"] == 3
    assert round(o["gate1"]["lo"]) == 127 and o["gate2"]["price"] == b["L1"] and "dates" in b
    assert W.analyze_daily(_daily(p[:50])) is None                          # K 線不到 120 根


def test_fmt_rounds_half_up():
    assert W._fmt(44828.5) == "44,829" and W._fmt(45.5) == "45.5" and W._fmt(1234.49) == "1,234"


# ── 台指期：線上 11/4 的 60 分轉折（47,607 之後）＋日 K → 劇本頁的兩道關卡、三種細微脈動的③改成大中小 ──
EX = [(45487, "H", 305, "11-02"), (42925, "L", 318, "11-03"), (44069, "H", 324, "11-03"), (42050, "L", 335, "11-04"),
      (43944, "H", 339, "11-04")]
CLOSES = [46560.0] * 5 + [44700.0, 44200.0, 43900.0, 43800.0, 44170.0]      # 日線 5 均 44,154、10 均 45,357


def _tx():
    import test_b89_nest as B89
    return B89._build(EX, 44140.0)


def test_tx_view3_is_big_mid_small():
    out = _tx()
    v3 = out["pulses"]["views"][2]
    assert [m["p"] for m in v3["marks"]] == [44052, 45487, 42925, 44069, 42050] and v3["now"] == "(5) 落底"
    assert "動能逐漸收斂" in v3["name"] and "大 3,555、中 2,562、小 2,019" in v3["next"]


def test_tx_service_adds_two_gates():
    from wave import service as SV
    from wave import panel as PN
    out = _tx()
    snap = {"nest": {"60m": out}}
    waves = {"small": {"pivots": [{"p": 49240.0, "t": "H"}, {"p": 39442.0, "t": "L"}, {"p": 50265.0, "t": "H"},
                                  {"p": 45523.0, "t": "L"}, {"p": 47607.0, "t": "H"}], "tentative": {"p": 42050.0, "t": "L"}}}
    SV._tiers(snap, waves, CLOSES, 44140.0)
    tz = out["tiers"]
    assert [round(v) for v, _ in tz["gate1"]["lv"]] == [44052, 44173, 44154]
    g = {x["k"]: x for x in out["gates"]}
    assert "同時匯聚" in g["分水嶺"]["t"] and "日線 5 均 44,154" in g["分水嶺"]["t"]
    assert g["日線關卡"]["price"] == 45523 and "大 B 波" in g["日線關卡"]["t"] and "44,829～45,357～45,523" in g["日線關卡"]["t"]
    assert any("現在追沒有肉" in x for x in out["plan"])
    line = PN._nest_line(snap)
    assert "兩道關卡" in line and "44,052～44,173" in line
    # 60 分起點跟日 K 這一段的起點對不上 → 不算（兩層扣不起來）
    out2 = _tx()
    SV._tiers({"nest": {"60m": out2}}, {"small": {"pivots": waves["small"]["pivots"][:-1] + [{"p": 48000.0, "t": "H"}],
                                                  "tentative": {"p": 42050.0, "t": "L"}}}, CLOSES, 44140.0)
    assert "tiers" not in out2


def test_deep_ai_block_has_wave_lines():
    import deep_ai
    o = W.structure(BIG, SMALL, 44140.0, 44154.0, 45357.0, LB)
    txt = deep_ai._data_block({"stock_id": "2330", "name": "台積電", "chip": {}, "wave": o}, [])
    assert "【波段結構" in txt and "第一道關（安全門）44,052～44,173" in txt
