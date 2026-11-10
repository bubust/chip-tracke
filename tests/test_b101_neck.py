"""B101 她 11/10 盤前（@fanny55520 台指期）：40,715 起漲＝新脈動，跟舊脈動做撐壓交換
- 11/9 從 41,970 空到 40,715 停住；40,715 起漲這一腳衝到 43,269～43,307＝小 (3) 延伸、壓回段（42,317→40,715）1.618 倍外部投射（43,307）
- 47,555～47,607 往下的等幅目標 43,397～43,449（a＝50,265→46,107）被灌破以後，連同 60 分前波平台低點 42,925 轉成撐壓互換頸線
- 網站：37,694 被日線確認、後面出現暫定高點 42,317 以後，兩道關卡不能翻成「上漲結構」（第 (2) 段回到第 (1) 段 1.382 倍以上＝不是這種結構），
  要沿用 47,607 起跌那組（service._tiers_inputs），三層驗證全過、路徑 B 淘汰
python -m pytest tests/test_b101_neck.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
from wave import service as SV  # noqa: E402

BIG = [{"p": 50265, "t": "H"}, {"p": 45523, "t": "L"}, {"p": 47607, "t": "H"}, {"p": 37694, "t": "L"}]
SMALL = [{"p": p, "t": t} for p, t in ((47607, "H"), (44052, "L"), (45487, "H"), (42925, "L"), (44069, "H"), (42050, "L"), (44274, "H"),
                                        (37694, "L"), (40690, "H"), (39129, "L"), (42317, "H"), (40715, "L"), (43108, "H"))]
FIRST = [{"p": p, "t": t} for p, t in ((50265, "H"), (48413, "L"), (49594, "H"), (46107, "L"), (47555, "H"), (45523, "L"))]
LB = {"big": "日線", "small": "60 分"}


def _o(price=42844.0):
    return W.structure(BIG, SMALL, price, 41834.0, 43000.0, LB, first_leg=FIRST, full=17015.0)


def test_tx_1110_matches_her_numbers():
    p = _o()["ext3"]["paths"]
    assert all(L["ok"] for L in p["layers"])                                      # 三層都過（站穩 42,050）
    assert p["paths"][1].get("out") and "已淘汰" in p["paths"][1]["name"]          # 路徑 B（單純 3-4）淘汰
    n = p["next"]
    assert n["from"] == 40715 and n["prev_hi"] == 42317 and round(n["proj"]) == 43307   # 她：43,307
    assert [round(v) for v, _ in n["neck"]] == [42925, 43397, 43449]              # 她：42,925、43,397～43,449
    assert "還在頸線下" in n["neck_state"]                                         # 42,844 < 42,925
    assert "在頸線區裡" in _o(43200.0)["ext3"]["paths"]["next"]["neck_state"]
    assert "站上頸線" in _o(43500.0)["ext3"]["paths"]["next"]["neck_state"]
    c1 = p["c1"]
    assert c1 == 42317                                                            # c-1＝最後一次壓回前的高點（不是之後的 43,108）
    assert [round(v) for v in p["layers"][0]["zone"]] == [41516, 41705]           # 壓回沒回到 a 高點以下 → 用 42,317→40,715


def test_flipped_structure_rejected():
    """37,694 確認、42,317 暫定高點：直接拿最後四個（45,523→47,607→37,694→42,317）當上漲結構不合理 → None"""
    big = BIG[1:] + [{"p": 42317, "t": "H"}]
    assert W.structure(big, [{"p": 37694, "t": "L"}, {"p": 42317, "t": "H"}], 42844.0) is None


def test_tiers_inputs_fallback():
    big = BIG + [{"p": 42317, "t": "H"}]
    n60 = {"anchor": {"p": 37694.0}}
    P = {"marks": [{"p": 40690, "t": "H"}, {"p": 39129, "t": "L"}, {"p": 42317, "t": "H"}, {"p": 40715, "t": "L"}]}
    sm = {"tentative": {"p": 42317, "t": "H"}}
    a60 = {"ok": True, "an": {"pivots": [{"p": q["p"], "t": q["t"]} for q in SMALL[:-1]], "tentative": {"p": 43108, "t": "H"}}}
    got = list(SV._tiers_inputs(big, n60, P, sm, a60))
    assert len(got) == 2
    bg, small = got[1]
    assert [q["p"] for q in bg] == [50265, 45523, 47607, 37694] and small[0]["p"] == 47607 and small[-1]["p"] == 43108
    assert W.structure(got[0][0], got[0][1], 42844.0) is None                     # 第一組翻成上漲結構 → 不用
    assert W.structure(bg, small, 42844.0, 41834.0, 43000.0, LB, full=17015.0)["ext3"]["paths"]["next"]
