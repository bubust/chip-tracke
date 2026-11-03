"""B89 她 11/3 下午的貼文（@fanny55520 台指期）：47,607 起跌的三種細微脈動（她的圖 3～5）
- 日線：三段式 A＝50,265→46,107、B＝→47,607（破底穿頭）、C 起跌（主視角）vs 五段式 1＝45,523、2＝47,607、3 運行中
- 60 分：① 圖 3（3-3-1＝44,052、3-3-2＝45,487、現在 3-3-3，五段式擴延）② 圖 4（C-1＝44,052、C-2＝45,487、現在 C-3）
  ③ 圖 5（1＝46,126、2＝46,637、3＝44,052、4＝45,487、5＝42,925，C 五小波已落底）
- 先看 43,432（60 分 5 均）這筆下殺停了沒；上方最重要分水嶺 44,052：過不去又轉弱＝圖 3（3-3-4）或圖 4（C-4），順勢空最後一腳去 41,285；
  突破站穩 44,052＝排除圖 3、圖 4 的不重疊限制 → 大級數反彈（或圖 5），壓回第二隻腳守住再偏多；再看 44,714；下方 42,925、41,285（日線 0.5）
網站改之前（11/3 17:42）：60 分只有主要 3、備選 1-3、關卡 39,735／45,487／趨勢線；沒有 44,052 分水嶺、5 均、圖 5、日線中線支撐。
python -m pytest tests/test_b89_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_b86_nest as B86  # noqa: E402
from wave import nest as N  # noqa: E402
from wave import panel as PN  # noqa: E402
from wave import service as SV  # noqa: E402

H = (45487, "H", 305, "11-02")
LOW = [H, (42925, "L", 322, "11-03")]                       # 11/03 15:00 夜盤開盤殺到 42,925（她 16:21 截圖）
TAIL = [43849, 43655, 43360, 43121]                         # 60 分收完的最後 4 根（10:45～15:00）


def _build(extra, price, tail=None):
    rows = B86.LIVE[:-1] + extra
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 1} for p, t, i, _ in rows]
    pts[-1].update(ci=None)
    day = {i: dt.date(2026, int(d[:2]), int(d[3:])) for _, _, i, d in rows}
    n = rows[-1][2] + 1
    times = [1791288000 + 3600 * k for k in range(n)]
    tdate = lambda i: day.get(i) or max(v for k, v in day.items() if k <= i)   # noqa: E731
    closes = None
    if tail is not None:
        closes = np.interp(np.arange(n - 1), [r[2] for r in rows], [r[0] for r in rows])   # 收完的 K 棒（不含進行中那根）
        closes[-len(tail):] = tail
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, "60 分", B86.DAILY, B86.DATES, tdate=tdate,
                   tlabel=lambda i: f"#{i}", closes=closes)


def test_three_pulses_after_breaking_44052():
    out = _build(LOW, 43159.0, TAIL)
    assert out["primary"]["path"] == "3"                                                    # 47,607 起：1＝44,052、2＝45,487、3 進行中
    pz = out["pulses"]
    assert pz and out["two"] is None
    assert pz["end1"] == 44052 and pz["h2"] == 45487 and pz["low"] == 42925
    assert round(pz["f382"]) == 44714                                                      # 她：44,714
    assert round(pz["ma5"]) == 43429                                                       # 她：43,432（60 分 5 均，含進行中那根）
    v1, v2, v3 = pz["views"]
    assert v1["fig"] == "圖 3" and [m["text"] for m in v1["marks"]] == ["3-3-1", "3-3-2"] and v1["now"] == "3-3-3"
    assert v2["fig"] == "圖 4" and [m["text"] for m in v2["marks"]] == ["C-1", "C-2"] and v2["now"] == "C-3"
    assert v3["fig"] == "圖 5" and [m["p"] for m in v3["marks"]] == [46126, 46637, 44052, 45487, 42925]
    assert round(next(t["price"] for t in v3["targets"] if t["label"] == "5＝3 等長")) == 42902    # 42,925 ≈ 5＝3 等長


def test_gates_and_plan_follow_her_order():
    out = _build(LOW, 43159.0, TAIL)
    ks = [g["k"] for g in out["gates"]]
    assert ks[:4] == ["止跌", "分水嶺", "第二關", "支撐"]
    ws = out["gates"][1]
    assert ws["price"] == 44052 and "不重疊" in ws["t"] and "第二隻腳" in ws["t"] and not ws["ok"]
    v1, v2 = [x for x in out["plan"] if x.startswith("版本")]
    assert "過不去 44,052 又轉弱" in v1 and "順勢空最後一腳" in v1
    assert "站穩 44,052" in v2 and "44,714" in v2 and "45,266" in v2 and "45,818" in v2      # 她圖上的黃金切割


def test_rebound_keeps_the_three_and_44052_first():
    out = _build(LOW + [(43600, "H", 325, "11-04")], 43500.0)
    pz = out["pulses"]
    assert pz["views"][0]["now"] == "3-3-4" and pz["views"][1]["now"] == "C-4"
    ks = [g["k"] for g in out["gates"]]
    assert ks[0] == "分水嶺" and out["gates"][0]["price"] == 44052
    assert next(g for g in out["gates"] if g["k"] == "第二關")["price"] == 44713.52       # 反彈中的 0.382 改叫第二關
    up = _build(LOW + [(44300, "H", 325, "11-04")], 44250.0)
    assert up["gates"][0]["k"] == "分水嶺" and up["gates"][0]["ok"]                          # 站上 44,052


def test_daily_mid_ruler_half_is_the_last_leg():
    piv = [{"p": float(p), "t": t, "date": d} for p, t, d in B86.WEEKLY]
    bp = N.big_picture(piv, 43159.0, B86.MID)
    lv = {v["r"]: round(v["price"]) for v in bp["mid"]["levels"]}
    assert bp["mid"]["from"] == 31740 and lv == {0.382: 43188, 0.5: 41002, 0.618: 38817}
    her = [dict(q, p=32306.0) if q["p"] == 31740 else q for q in piv]                       # 她的日線黃金切割從 32,306 起算
    lv2 = {v["r"]: round(v["price"]) for v in N.big_picture(her, 43159.0, B86.MID)["mid"]["levels"]}
    assert lv2[0.5] == 41286 and lv2[0.382] == 43405 and lv2[0.618] == 39166                # 她：41,285、43,405、39,166


def test_service_fills_mid_support_into_pulses():
    out = _build(LOW, 43159.0, TAIL)
    piv = [{"p": float(p), "t": t, "date": d} for p, t, d in B86.WEEKLY]
    snap = {"nest": {"60m": out}}
    SV._pulses_mid(snap, N.big_picture(piv, 43159.0, B86.MID), 43159.0)
    pz = out["pulses"]
    assert round(pz["mid"]["price"]) == 41002
    assert any(g["k"] == "中線支撐" and round(g["price"]) == 41002 for g in out["gates"])
    sup = next(g for g in out["gates"] if g["k"] == "支撐")
    assert "41,002" in sup["t"] or "41,003" in sup["t"]
    assert any("日線中線支撐 41,00" in x for x in out["plan"])
    line, prices = PN._nest_line(snap), PN._nest_prices(snap)
    assert "三種細微脈動" in line and "分水嶺 44,052" in line and 44052 in prices


def test_not_triggered_before_breaking_the_first_low():
    """11/2（44,052 還沒破）：還是 B87／B88 的兩種，不是三種細微脈動"""
    out = _build([H, (44832, "L", 306, "11-02")], 44976.0)
    assert out["pulses"] is None and out["two"]["phase"] == "pull"
