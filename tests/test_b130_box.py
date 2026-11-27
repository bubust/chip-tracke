"""B130 她 11/26（@fanny55520 台指期）：
- 日線：33,719→40,900 先按 5-1-1（暫定）；40,900→35,933 盤中刺穿 36,462 後收腳（爆量長下影、低點墊高、收回 37,694）＝5-1-2
  → 分辨「直接走 5-1-3 主推」還是「35,933～40,900 大箱體震盪築底」：站穩 40,040、突破 40,900 停留、回測不退回＝5-1-3（往 41,992、43,944）
- 60 分三道邊界：出箱驗證門 39,688、結構底線 39,003、波段升級門 40,900
- 週線：17,015→50,265 的 0.5＝33,640（最低 33,719 只高 79 點）、0.382＝37,564；主追蹤＝週線第 4 浪收尾接第 5 浪，威脅＝週線 A 浪收尾走大 B
- 月線：24,449＝12,652 起算的不重疊底線
- 用戶 11/27：日 K 少了 11/27 那根（FinMind 晚上才更新、即時那根是夜盤）→ 用 5 分 K 補
python -m pytest tests/test_b130_box.py -q（不連網）"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b123_two_walls as X  # noqa: E402
from wave import futdata as FD  # noqa: E402

TW = timezone(timedelta(hours=8))


def test_fill_day_from_bars5():
    fb = pd.DataFrame([{"date": "2026-11-26", "o": 37868.0, "h": 39688.0, "l": 35933.0, "c": 39455.0, "v": 158828.0}])
    rows = []
    t = datetime(2026, 11, 26, 15, 0, tzinfo=TW).timestamp()            # 11/26 夜盤 → 算 11/27
    while t < datetime(2026, 11, 27, 5, 0, tzinfo=TW).timestamp():
        rows.append((t, 39400.0, 39500.0, 39300.0, 39450.0, 100.0)); t += 300
    t = datetime(2026, 11, 27, 8, 45, tzinfo=TW).timestamp()
    while t < datetime(2026, 11, 27, 13, 45, tzinfo=TW).timestamp():
        rows.append((t, 39400.0, 39700.0, 39000.0, 39350.0, 200.0)); t += 300
    after = datetime(2026, 11, 27, 15, 10, tzinfo=TW).timestamp()
    out = FD.fill_from_bars5(fb, rows, after)
    assert list(out.date) == ["2026-11-26", "2026-11-27"]
    r = out.iloc[-1]
    assert (r.o, r.h, r.l, r.c) == (39400.0, 39700.0, 39000.0, 39350.0) and r.v == 168 * 100 + 60 * 200
    assert len(FD.fill_from_bars5(fb, rows, datetime(2026, 11, 27, 12, 0, tzinfo=TW).timestamp())) == 1   # 日盤還沒收完不補
    assert len(FD.fill_from_bars5(fb, rows[:100], after)) == 1                                           # 沒有日盤（假日）不補


def _box_frame(price):
    t = W.structure(W.merge_pause(X.DAILY), X.H60 + [{"p": 40900, "t": "H"}, {"p": 35933, "t": "L"}], price, 38079.0, 39000.0, X.LB, full=17015.0)
    box = {"top": 40900.0, "lo": 35933.0, "hi": 39688.0, "floor": 39003.0}
    fr = W.big_frame(t, price, 17015.0, lows=[31740.0, 39442.0], cyc=[8268.0, 12652.0, 24449.0], leg=(35933.0, 39688.0), box=box)
    return t, fr


def test_box_daily():
    t, fr = _box_frame(39286.0)
    bx = fr["box"]
    assert W._fmt(bx["wk382"]) == "37,564" and bx["state"] == "in" and fr["pull"] is None      # 她：週線分割位 37,564
    assert any(x.startswith("箱體（她 11/26）") for x in fr["lines"]) and "5-1-2" in fr["status"]
    t["frame"] = fr
    c = W.plan_card(t, 39286.0)
    v = W.frame_views(c, fr, 39286.0)["1d"]
    assert [s["title"] for s in v["scen"]] == ["① 5-1-3 起推", "② 大箱體震盪築底"] and v["scen"][1]["now"]
    assert (v["tiles"]["up"]["price"], v["tiles"]["down"]["price"], v["tiles"]["stop"]["price"]) == (40900, 37694, 35933)
    assert "41,992" in v["plays"][1]["t"] and "43,944" in v["plays"][1]["t"]


def test_box_60m_and_weekly():
    t, fr = _box_frame(39286.0)
    pw = [{"p": p, "t": tt} for p, tt in ((28594, "H"), (26247, "L"), (49240, "H"), (39442, "L"), (50265, "H"), (37694, "L"), (44911, "H"),
                                           (33719, "L"), (40900, "H"))]
    p60 = [{"p": p, "t": tt} for p, tt in ((44824, "H"), (39010, "L"), (40693, "H"), (33719, "L"), (40900, "H"), (36500, "L"), (38489, "H"),
                                            (35933, "L"), (39688, "H"))]
    p15 = [{"p": p, "t": tt} for p, tt in ((36994, "H"), (35966, "L"), (39688, "H"), (39003, "L"), (39577, "H"), (39050, "L"), (39350, "H"))]
    o = W.frame_tfs(fr, 39286.0, {"1wk": pw, "60m": p60, "15m": p15}, {"15m": 39374.0})
    g = o["60m"]["tiles"]
    assert (g["up"]["price"], g["down"]["price"], g["stop"]["price"]) == (39688, 39003, 40900)               # 她：39,688／39,003／40,900
    assert [x["title"] for x in o["60m"]["map"]["versions"]] == ["出箱", "箱內輪動", "斜率斷裂"] and o["60m"]["map"]["versions"][1]["now"]
    wk = o["1wk"]
    assert wk["map"]["title"].startswith("週線前沿") and "只高出 79 點" in wk["map"]["sub"]                 # 她：只高出 79 點
    assert [x["title"].split("｜")[0] for x in wk["map"]["versions"]] == ["主追蹤", "威脅路徑"] and "24,449" in wk["plays"][2]["t"]
    assert o["15m"]["tiles"]["up"]["price"] == 39688 and o["15m"]["map"]["path"][0]["p"] == 35933


def test_clock_night_bar_is_next_day():
    """用戶 11/27：夜盤那根日 K 標 11/30，「今天」還是 11/27（週五）→ 週線收盤＝11/27，不是 12/4"""
    bars = [{"time": d, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for d in ("2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27", "2026-11-30")]
    ck = W.frame_clock(bars, [], "2026-11-06", "2026-11-12", "2026-11-23", "2026-11-27")
    assert ck["wk_close"] == "2026-11-27" and ck["reb_days"] == 4
