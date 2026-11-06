"""B98 她 11/6 的貼文（@fanny55520 台指期）：4 不重疊 1 → 延伸第 3 段（3-1、3-2、3-3 運行中）
- 60 分：47,607→44,052＝(1)、45,487＝(2)、42,050＝(3-1)、44,274＝(3-2)，3-3 殺到 37,694（44,274 碰到 44,052，所以不是第 4 段）
- 3-3 第一煞車區 38,713～38,522＝44,274 往下 1.618 倍 3-1（3,437）、1.618 倍 (1)（3,555）
- 3-3 第二煞車區 37,564～37,400＝全波段 17,015→50,265 的 0.382、44,274 往下 2 倍 3-1
- 反彈受阻（3-3 的 0.382～0.5）或收不回 3-1 低點 42,050、壓回破 37,694＝只是 3-4；5 走完：淺 5 36,603～35,192、深 5 ～33,641
python -m pytest tests/test_b98_ext3.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402

BIG = [{"p": 50265, "t": "H"}, {"p": 45523, "t": "L"}, {"p": 47607, "t": "H"}, {"p": 41666, "t": "L"}]
SMALL = [{"p": p, "t": t} for p, t in ((47607, "H"), (44052, "L"), (45487, "H"), (42050, "L"), (44274, "H"),
                                        (42071, "L"), (42768, "H"), (37694, "L"), (40690, "H"))]
LB = {"big": "日線", "small": "60 分"}


def _o(small=SMALL, price=39810.0, full=17015.0):
    return W.structure(BIG, small, price, 42520.0, 44405.0, LB, full=full)


def test_tx_1106_matches_her_numbers():
    e = _o()["ext3"]
    assert e["y"] == 44274 and e["x"] == 42050 and e["legs"] == [3555, 3437]
    z1, z2 = e["brakes"]
    assert [round(v) for v, _ in z1["lv"]] == [38713, 38522] and z1["state"] == "through"      # 她：38713-38522
    assert [round(v) for v, _ in z2["lv"]] == [37564, 37400] and z2["state"] == "ahead"        # 她：37564-37400
    assert abs(z2["gap"] - 130.5) <= 0.5 and "0.382" in z2["lv"][0][1]                          # 37,694 離 37,564 還差 130 點
    f = e["five"]
    assert [round(v) for v, _ in f["shallow"]["lv"]] == [36601, 35192]                          # 她：淺 5 36603-35192（36,603 試算 36,601）
    assert [round(v) for v, _ in f["deep"]["lv"]] == [35192, 33640]                             # 她：深 5 35,192-33,641
    r = e["reb"]
    assert [round(r["f382"]), round(r["f5"])] == [40208, 40984] and r["hard"] == 42050 and r["from"] == 37694
    assert "0.382～0.5 之間" in r["now"]                                                         # 反彈 40,690（她空在 40,518、40,584 之下）
    txt = "\n".join(e["lines"])
    assert "42,050 只是 3-1、44,274 是 3-2" in txt and "接刀" in txt and "分批" in txt
    assert "另一種看法＝她 11/6" in _o()["lines"][1]                                              # 原本「楔形走完」那行指過來


def test_no_overlap_no_ext3():
    """第 (4) 段沒碰到第 (1) 段（44,274 改成 43,900）＝標準五段，沒有「延伸第 3 段」這種看法"""
    sm = [dict(q) for q in SMALL]
    sm[4]["p"] = 43900
    assert _o(sm)["ext3"] is None


def test_without_full_wave():
    """沒有全波段起點：第二煞車區改用 2 倍 (1)，深 5 不算"""
    e = _o(full=None)["ext3"]
    assert [round(v) for v, _ in e["brakes"][1]["lv"]] == [37400, 37164] and e["five"] is None


def test_reclaim_3_1_low_means_turn():
    e = _o(SMALL[:-1] + [{"p": 42300, "t": "H"}], price=42200.0)["ext3"]
    assert "轉浪" in e["reb"]["now"]


def test_mirror_uptrend():
    """反過來（漲勢）也算得出來：煞車區在上面、方向字眼對調"""
    m = lambda xs: [{"p": 100000 - q["p"], "t": "L" if q["t"] == "H" else "H"} for q in xs]   # noqa: E731
    o = W.structure(m(BIG), m(SMALL), 100000 - 39810.0, None, None, LB, full=100000 - 17015.0)
    e = o["ext3"]
    assert [round(v) for v, _ in e["brakes"][0]["lv"]] == [100000 - 38713, 100000 - 38522]
    assert "摸頂" in e["lines"][-1] and e["five"] is not None


def test_full_from_big_degree():
    from wave import service as SV
    sm = {"pivots": [{"date": "2026-10-07", "p": 50265, "t": "H"}, {"date": "2026-10-20", "p": 45523, "t": "L"},
                     {"date": "2026-10-29", "p": 47607, "t": "H"}, {"date": "2026-11-04", "p": 42050, "t": "L"}]}
    big = [{"p": float(q["p"]), "t": q["t"]} for q in sm["pivots"]]
    waves = {"big": {"pivots": [{"date": "2025-01-07", "p": 23990, "t": "H"}, {"date": "2025-04-10", "p": 17015, "t": "L"}]}}
    assert SV._full_from(waves, sm, big) == 17015
    assert SV._full_from({}, sm, big) is None
