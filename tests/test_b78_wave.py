"""B78 波浪補齊：複合修正 W-X-Y／W-X-Y-X-Z、三角形、楔形、替代劇本、白話。
python -m pytest tests/test_b78_wave.py -q（不連網）"""
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import engine as E  # noqa: E402
from wave.plain import plain  # noqa: E402


def _pts(vals, start="L"):
    """價格序列 → 交錯的轉折點（最後一個是進行中的極值）"""
    out, t = [], start
    for i, v in enumerate(vals):
        out.append({"i": i * 10, "p": float(v), "t": t, "ci": i * 10 + 3})
        t = "H" if t == "L" else "L"
    out[-1]["ci"] = None
    return out


def _at0(vals, kind, start="L"):
    return [c for c in E.count_waves(_pts(vals, start)) if c["kind"] == kind and c["start"] == 0]


# 漲多後的雙重鋸齒：200 →a 170 →b 185 →W 150 →X 172 →a 145 →b 158 →Y 130（進行中）
WXY = [200, 170, 185, 150, 172, 145, 158, 130]


def test_wxy_counted_with_labels_and_targets():
    c = _at0(WXY, "combo", "H")
    assert c, "教科書 W-X-Y 要數得出來"
    c = c[0]
    assert c["current"] == "Y" and c["corr_kind"] == "wxy" and c["dir"] == -1
    assert [x["disp"] for x in c["labels"]] == ["0", "a", "b", "W", "X", "a", "b", "Y"]
    assert [x["label"] for x in c["labels"]][1:4] == ["Wa", "Wb", "W"]
    assert c["invalid"] == 158 and c["invalid_side"] == "above"          # Y 的 c 段：漲回 b 的高點就不對
    assert [t["price"] for t in c["targets"]] == [122.0, 91.1]            # Y＝1、1.618 倍 W（W＝50，從 172 起算）
    assert "W-X-Y" in c["text"] and "漲多後" in c["text"]


def test_complex_shows_as_alternate_when_better_fit():
    """複雜結構要明顯更好才當主要劇本；但「不算複雜度加分」時更貼近 → 一定放進替代劇本"""
    p, a = E.primary_alternate(E.count_waves(_pts(WXY, "H")))
    assert p["kind"] not in E.COMPLEX_KINDS
    assert a["kind"] == "combo" and a["fit"] < p["score"] <= a["score"]


def test_wxyxz_counted():
    c = _at0(WXY + [148, 125, 135, 115], "combo", "H")
    assert c and c[0]["current"] == "Z" and c[0]["corr_kind"] == "wxyxz"
    assert [x["disp"] for x in c[0]["labels"]][8:] == ["X", "a", "b", "Z"]


def test_combo_hard_rules():
    # X 回到 W 起點以外（205 > 200）
    assert not _at0([200, 170, 185, 150, 205, 175], "combo", "H")
    # W 的 c 沒走到 a 的終點附近（c 只到 176，a 終點 170，差 0.2 個 a）
    assert not _at0([200, 170, 185, 176, 182, 160], "combo", "H")
    # Y 比 W 大太多（W＝50、Y 的 a 已經 90 > 1.618 倍）
    assert not _at0([200, 170, 185, 150, 172, 82], "combo", "H")
    # 還沒出現 X（3 段以內）跟單純 A-B-C 分不出來 → 不列
    assert not _at0([200, 170, 185, 150], "combo", "H")


def test_correction_cannot_exceed_prior_move_start():
    # 前一段 150 → 200 的上漲；之後的「複合修正」跌到 130 ＝ 回檔超過 100% → 不是修正
    cnt = E.count_waves(_pts([150] + WXY, "L"))
    assert not any(c["kind"] == "combo" and c["start"] == 1 for c in cnt)
    # 前一段夠長（100 → 200）就可以
    cnt = E.count_waves(_pts([100] + WXY, "L"))
    assert any(c["kind"] == "combo" and c["start"] == 1 and c["current"] == "Y" for c in cnt)


def test_contracting_triangle():
    # 漲多後：200 →A 170 →B 194 →C 176 →D 190 →E 180（進行中）
    c = _at0([200, 170, 194, 176, 190, 180], "triangle", "H")
    assert c and c[0]["current"] == "E" and c[0]["corr_kind"] == "contracting"
    assert c[0]["invalid"] == 176 and c[0]["invalid_side"] == "below"     # E 不能超過 C 的終點
    nxt = [t for t in c[0]["targets"] if t["kind"] == "next"]
    assert nxt and nxt[0]["price"] > 194                                   # 走完往上突破（原本的方向）
    p = plain(c[0])
    assert "收斂三角形" in p["title"] and "往上突破" in p["meaning"]


def test_triangle_rules():
    # C 超過 A 的終點（高點一起墊高）＝楔形的形狀，不是收斂三角形
    assert not any(c["corr_kind"] == "contracting" for c in _at0([100, 130, 110, 135, 120, 130], "triangle"))
    # 收斂三角形 D 跑出 B 的終點（196 > 194）
    assert not _at0([200, 170, 194, 176, 196], "triangle", "H")
    # 擴散三角形某一段大到 2.618 倍以上 → 不是同一個型態
    assert not _at0([100, 110, 102, 115, 60], "triangle")


def test_contracting_diagonal_overlap_allowed_impulse_not():
    vals = [100, 130, 110, 135, 120, 130]                 # 第 4 浪 120 跌進第 1 浪區（<130）
    assert not any(c["kind"] == "impulse" and len(c["labels"]) == 6 for c in _at0(vals, "impulse"))
    d = _at0(vals, "diagonal")
    assert d and d[0]["current"] == "5" and d[0]["corr_kind"] == "contracting"
    caps = [t for t in d[0]["targets"] if "上限" in t["label"]]
    assert caps and caps[0]["price"] == 145                # 第 5 浪要比第 3 浪（25）短
    p = plain(d[0])
    assert "上升楔形" in p["title"]


def test_diagonal_rules():
    # 第 4 浪沒跌進第 1 浪區 → 是推動浪不是楔形
    assert not _at0([100, 130, 110, 160, 140, 150], "diagonal")
    # 第 4 浪跌破第 2 浪終點
    assert not _at0([100, 130, 110, 135, 105], "diagonal")


def test_enable_complex_off_matches_old_engine():
    """ENABLE_COMPLEX 關掉＝舊引擎；打開後推動浪／A-B-C 的候選完全一樣（只多了新結構）"""
    rng = random.Random(78)
    for _ in range(200):
        n = rng.randint(3, 14)
        v, p = [], 100.0
        for j in range(n):
            p = p * (1 + (0.05 + rng.random() * 0.2) * (1 if j % 2 == 0 else -1))
            v.append(round(p, 2))
        pts = _pts(v)
        E.ENABLE_COMPLEX = False
        try:
            old = E.count_waves(pts, max_back=9)
        finally:
            E.ENABLE_COMPLEX = True
        new = [c for c in E.count_waves(pts) if c["kind"] in ("impulse", "correction")]
        strip = lambda cs: [(c["kind"], c["start"], c["current"], c["score"], c["invalid"], c["targets"]) for c in cs]  # noqa: E731
        assert sorted(strip(old), key=str) == sorted(strip(new), key=str)
        assert not any(c["kind"] in E.COMPLEX_KINDS for c in old)


def test_plain_covers_every_label():
    for kind, labels in (("combo", E._COMBO_LABELS[4:]), ("triangle", ["D", "E"]), ("diagonal", ["4", "5"])):
        for d in (1, -1):
            for cur in labels:
                for ck in ("contracting", "expanding", "wxy"):
                    p = plain({"kind": kind, "dir": d, "current": cur, "corr_kind": ck})
                    assert p and p["title"] and p["meaning"], (kind, d, cur)
    assert plain({"kind": "combo", "dir": -1, "current": "Y"})["title"] == "複合修正的最後一段下跌（Y 的 c）"
    assert plain({"kind": "combo", "dir": 1, "current": "Y"})["title"] == "複合反彈的最後一段反彈（Y 的 c）"


def test_frontend_plain_has_same_texts():
    """regime-frontend/wave.js 的 plainComplex 跟 wave/plain.py 同一套文字（固定字串都要出現在兩邊）"""
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "regime-frontend", "wave.js"),
              encoding="utf-8").read()
    py = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wave", "plain.py"),
              encoding="utf-8").read()
    for s in ("修正拉長成兩組三段（W-X-Y），這是第二組的開始", "已經走了兩組三段（W、Y），這段連接到第三組（Z）；三組是上限",
              "楔形的最後一段；照教科書，走完常快速跌回楔形起點附近", "上下震盪越來越小"):
        assert s in js and s in py
    assert re.search(r"x\.disp \|\| x\.label", js)                        # 圖上標記用顯示字（Wa → a）
