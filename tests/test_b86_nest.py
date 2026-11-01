"""B86 她 11/1 的貼文（@fanny55520 台指期）：「回到最源頭的思路」——50,265 起的下跌三種日線定位＋60 分兩種切組。
- 第一種切組（三段式）：50,265→48,413(a)→49,594(b)→46,107(c)＝A；46,107→47,555→45,523→47,607＝B（破底穿頭平台）；47,607 起 C 走五波
  → C＝A 等幅 43,449
- 第二種切組（威脅）：50,265→45,523 走五波 (1)～(5)＝C-1、47,607＝C-2、47,607→44,052 只是 C-3-1、接著弱勢 C-3-2、C-3-3 主跌
- 三種日線定位：全波段 17,016→50,265 的 0.382＝37,564；第 (3) 浪 31,740→49,240 的 0.382～0.5＝42,555～40,490、守 39,442；
  49,240 結束全波段、50,265 B 假突破 → C 浪 37,564～33,641
網站改之前：週末台指期現價停在日盤收盤 45,301（夜盤已經跌到 44,052、收 44,442），關卡用錯價；60 分只從 47,607 拆，看不到源頭兩種切組；
日 K 母尺 45,523→47,607 已經「回檔 111%」還照列。
python -m pytest tests/test_b86_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import nest as N  # noqa: E402

# 線上台指期 60 分 K 的轉折（11/01 15:22 快照＋10/27 舊快照合併）：(價, 高低, 第幾根, 日期)
LIVE = [(50265, "H", 0, "10-06"), (49842, "L", 10, "10-07"), (50117, "H", 12, "10-07"), (49253, "L", 20, "10-07"), (49692, "H", 29, "10-08"),
        (48788, "L", 36, "10-08"), (49226, "H", 40, "10-08"), (48413, "L", 43, "10-09"), (49594, "H", 51, "10-12"), (48240, "L", 67, "10-13"),
        (49200, "H", 87, "10-14"), (46674, "L", 110, "10-15"), (47166, "H", 112, "10-15"), (46456, "L", 115, "10-15"), (47634, "H", 124, "10-16"),
        (46107, "L", 141, "10-17"), (47033, "H", 155, "10-19"), (46222, "L", 161, "10-20"), (46920, "H", 162, "10-20"), (46136, "L", 171, "10-20"),
        (47288, "H", 180, "10-21"), (46596, "L", 184, "10-21"), (47555, "H", 196, "10-22"), (45523, "L", 216, "10-23"), (46846, "H", 218, "10-27"),
        (46006, "L", 223, "10-27"), (47607, "H", 255, "10-29"), (46126, "L", 262, "10-29"), (46637, "H", 269, "10-29"), (44908, "L", 275, "10-30"),
        (45597, "H", 279, "10-30"), (44052, "L", 291, "10-31"), (44579, "H", 293, "10-31")]
# 日 K（線上）：50,265 起鋸齒 A-B-C，A＝45,523（10/27，颱風休市）、B＝47,607、C 進行中
DATES = ["2026-10-02", "2026-10-07", "2026-10-22", "2026-10-27", "2026-10-29", "2026-10-30"]
DAILY = {"kind": "correction", "current": "C", "corr_kind": "zigzag",
         "labels": [{"i": 1, "p": 50265, "label": "0"}, {"i": 3, "p": 45523, "label": "A"}, {"i": 4, "p": 47607, "label": "B"},
                    {"i": 5, "p": 44908, "label": "C"}]}
# 週 K 轉折（線上）
WEEKLY = [(22004, "L", "2024-11-29"), (23990, "H", "2025-01-07"), (17015, "L", "2025-04-10"), (28594, "H", "2025-11-04"),
          (26247, "L", "2025-11-24"), (35879, "H", "2026-03-02"), (31124, "L", "2026-03-09"), (34734, "H", "2026-03-19"),
          (31740, "L", "2026-04-01"), (46994, "H", "2026-06-03"), (40779, "L", "2026-06-08"), (49240, "H", "2026-06-23"),
          (39442, "L", "2026-07-29"), (50265, "H", "2026-10-07")]
MID = {"kind": "correction", "current": "C", "corr_kind": "flat",
       "labels": [{"p": 49240.0, "label": "0"}, {"p": 39442.0, "label": "A"}, {"p": 50265.0, "label": "B"}, {"p": 44908.0, "label": "C"}]}


def _build(price=44442.0):
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 2} for p, t, i, _ in LIVE]
    pts[-1].update(ci=None)
    day = {i: dt.date(2026, int(d[:2]), int(d[3:])) for _, _, i, d in LIVE}
    t_now = LIVE[-1][2]
    times = [1791288000 + 3600 * k for k in range(t_now + 1)]
    tdate = lambda i: day.get(i) or max(v for k, v in day.items() if k <= i)   # noqa: E731
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, "60 分", DAILY, DATES, tdate=tdate, tlabel=lambda i: f"#{i}")


def test_source_cut_first_kind_is_her_three_segments():
    out = _build()
    src = out["source"]
    assert src["from"]["p"] == 50265 and src["b_end"] == 47607
    t3 = src["three"]
    marks = {m["p"]: m["text"] for m in t3["marks"]}
    assert marks[48413] == "A-a" and marks[49594] == "A-b" and marks[46107] == "A"         # 50,265→46,107 三波 a-b-c
    assert marks[47555] == "B-a" and marks[45523] == "B-b" and marks[47607] == "B"         # 破底穿頭：b 刺穿 46,107
    assert t3["bpn"] and "破底穿頭" in t3["desc"] and t3["path"].startswith("C")
    assert round(t3["targets"][0]["price"]) == 43449                                       # 她：A-c 等幅 43,449


def test_source_cut_second_kind_is_her_threat():
    t5 = _build()["source"]["five"]
    marks = {m["p"]: m["text"] for m in t5["marks"]}
    assert [marks[p] for p in (48413, 49594, 46107, 47555)] == ["1-1", "1-2", "1-3", "1-4"]   # 她的 (1)～(4)
    assert marks[45523] == "1" and marks[47607] == "2" and marks[44052] == "3-1"           # (5)＝C-1、C-2、C-3-1
    assert t5["path"] == "3-2"                                                             # 接著弱勢反彈 C-3-2
    r = t5["rebound"]
    assert round(r["p50"]) == 45830 and round(r["p618"]) == 46249 and r["kill"] == 47607
    assert round(t5["targets"][0]["price"]) == 42865                                       # 第 3 段＝1 倍第 1 段


def test_main_count_from_47607_uses_night_price():
    out = _build(44442.0)
    assert out["anchor"]["p"] == 47607 and not out["evidence"]["trend"]                    # 夜盤收 44,442：還沒越過趨勢線
    assert out["primary"]["path"] == "5-2"                                                 # C 的五波還沒走完（第一種）
    assert out["alternate"]["path"] == "2"                                                 # 第 1 段走完、第 2 段反彈（第二種的 3-1／3-2）


def test_big_picture_three_scenarios():
    piv = [{"p": float(p), "t": t, "date": d} for p, t, d in WEEKLY]
    bp = N.big_picture(piv, 44442.0, MID)
    assert bp["pts"]["g0"]["p"] == 17015 and bp["pts"]["s3"]["p"] == 31740 and bp["pts"]["h3"]["p"] == 49240
    assert bp["pts"]["w4"]["p"] == 39442 and bp["pts"]["h"]["p"] == 50265
    lv = {x["key"]: {v["label"]: round(v["price"]) for v in x["levels"]} for x in bp["scenarios"]}
    assert lv["A"]["全波段 0.382（總修正目標）"] == 37564                                     # 她：37,564
    assert lv["4"]["第 (3) 浪 0.382"] == 42555 and lv["4"]["第 (3) 浪 0.5（極限防守）"] == 40490  # 她：42,555、40,490
    assert any(v == 39442 for v in lv["4"].values())                                       # 需守在 39,442 之上
    assert lv["C"]["全波段 0.5"] == 33640                                                   # 她：37,564～33,641
    assert bp["favored"] == "C"                                                            # 週 K 主要數法＝49,240 結束、50,265 B 假突破
    assert N.big_picture(piv, 50500.0, MID) is None                                        # 創新高就沒有「下跌三種定位」


def test_daily_positioning_switches_to_extension_when_ruler_broken():
    daily = {"kind": "correction", "current": "C", "labels": [{"p": 50265.0, "date": "2026-10-07"}, {"p": 45523.0, "date": "2026-10-27"},
                                                               {"p": 47607.0, "date": "2026-10-29"}, {"p": 44908.0, "date": "2026-10-30"}]}
    r = N.positioning(daily, {"text": "下跌推動浪・第 3 浪", "invalid": 47607.0, "invalid_side": "above"}, 44442.0)
    assert r["extension"] and "母尺已經失效" in r["lines"][0] and "111%" not in r["lines"][0]
    assert {k: round(v) for k, v in r["levels"].items()} == {"x0.618": 44676, "x1": 42865, "x1.618": 39934}
    assert r["passed"] == ["x0.618"]


def test_flat_b_over_138_needs_penalty():
    """破底穿頭：b 到 a 的 1.40 倍可以（FLAT_HARD 1.45），但比 1.38 以內多扣 FLAT_OVER（她 10/20 的 A-4-b 不能被擠掉）"""
    P = N._Parser([{"i": i, "p": p, "t": t} for p, t, i in [(46107, "L", 0), (47555, "H", 5), (45523, "L", 10), (47607, "H", 15)]])
    pens, extra = P._rules("flat", [0, 1, 2, 3], 1, 3, False)
    assert extra >= N.FLAT_OVER
    P2 = N._Parser([{"i": i, "p": p, "t": t} for p, t, i in [(46107, "L", 0), (47555, "H", 5), (45000, "L", 10), (47607, "H", 15)]])
    assert P2._rules("flat", [0, 1, 2, 3], 1, 3, False) is None                           # 1.76 倍：不是平台


def test_tx_after_hours_price(monkeypatch):
    """週末：日 K 最後一天 10/30 收 45,301，但夜盤（10/30 15:00～10/31 05:00）已經跌到 44,052、收 44,442 → 現價用夜盤"""
    from wave import futdata as FD
    from wave import service as SV
    base = int(dt.datetime(2026, 10, 30, 15, 0, tzinfo=SV.TW).timestamp())
    rows = [(base + 300 * k, 45400.0 - 5 * k, 45410.0 - 5 * k, 45390.0 - 5 * k, 45400.0 - 5 * k, 10) for k in range(160)]
    rows[100] = (rows[100][0], 44100.0, 44110.0, 44052.0, 44080.0, 10)
    rows[-1] = (rows[-1][0], 44450.0, 44460.0, 44430.0, 44442.0, 10)
    monkeypatch.setattr(FD, "load_bars5", lambda sym, since_ts=None: [r for r in rows if r[0] >= (since_ts or 0)])
    ah = SV._tx_after_hours("2026-10-30")
    assert ah["c"] == 44442.0 and ah["l"] == 44052.0 and ah["date"] == "2026-11-02" and ah["time"].startswith("夜盤收")
    night = SV._tx_after_hours("2026-10-30", night_only=True)
    assert night["c"] == 44442.0
    monkeypatch.setattr(FD, "load_bars5", lambda sym, since_ts=None: [])
    assert SV._tx_after_hours("2026-10-30") is None
