"""B85 她 10/29 晚上的貼文（@fanny55520 台指期 60 分）：45523 是 C-1 結束、45523→47606 是 C-2-a，現在 C-2-b；
生死臨界線 46,148～46,006（60 分收盤守住），帶量跌破（或反抽不過 46,300）＝C-2 結束、C-3 主跌直破 45,523；橫台 8～12 根才判。
網站改之前：日 K 剛把 47607 數成第 3 浪 → 60 分起點跑到 46006（10/23 颱風休市，45523 對不到），寫「第 3 段上漲、別逆勢放空」。
python -m pytest tests/test_b85_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import nest as N  # noqa: E402

# 線上台指期 60 分 K 的轉折（10/30 00:40 快照）：(價, 高低, 第幾根, 日期)
LIVE = [(50265, "H", 0, "10-06"), (49842, "L", 10, "10-07"), (50117, "H", 12, "10-07"), (49253, "L", 20, "10-07"),
        (49692, "H", 29, "10-08"), (48788, "L", 36, "10-08"), (49226, "H", 40, "10-08"), (48413, "L", 43, "10-09"),
        (49594, "H", 51, "10-12"), (48240, "L", 67, "10-13"), (49200, "H", 87, "10-14"), (46674, "L", 110, "10-15"),
        (47166, "H", 112, "10-15"), (46456, "L", 115, "10-15"), (47634, "H", 124, "10-16"), (46107, "L", 141, "10-17"),
        (47033, "H", 155, "10-19"), (46222, "L", 161, "10-20"), (46920, "H", 162, "10-20"), (46136, "L", 171, "10-20"),
        (47288, "H", 180, "10-21"), (46596, "L", 184, "10-21"), (47555, "H", 196, "10-22"), (45523, "L", 216, "10-23"),
        (46846, "H", 218, "10-27"), (46006, "L", 223, "10-27"), (47607, "H", 255, "10-29"), (46126, "L", 262, "10-29"),
        (46637, "H", 269, "10-29")]
# 日 K（線上）：39,442 → 50,265 第 1 浪、→ 45,523 第 2 浪（日 K 標在 10/27：10/23、10/26 颱風休市）、→ 47,607 第 3 浪（暫定）
DATES = ["2026-07-29", "2026-10-06", "2026-10-22", "2026-10-27", "2026-10-29"]
DAILY = {"kind": "impulse", "current": "3", "labels": [{"i": 0, "p": 39442, "label": "0"}, {"i": 1, "p": 50265, "label": "1"},
                                                       {"i": 3, "p": 45523, "label": "2"}, {"i": 4, "p": 47607, "label": "3"}]}


def _build(price=46615.0, last=None, add=None, with_closes=True):
    rows = list(LIVE) if last is None else LIVE[:-1] + [last]
    rows = rows + [add] if add else rows
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 2} for p, t, i, _ in rows]
    pts[-1].update(p=float(price), ci=None)
    day = {i: dt.date(2026, int(d[:2]), int(d[3:])) for _, _, i, d in rows}
    t_now = rows[-1][2]
    times = [1791288000 + 3600 * k for k in range(t_now + 1)]
    closes = np.interp(np.arange(t_now + 1), [r[2] for r in rows], [r[0] for r in rows[:-1]] + [price]) if with_closes else None
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, "60 分", DAILY, DATES,
                   tdate=lambda i: day.get(i, dt.date(2026, 10, 6) + dt.timedelta(days=i // 19)), tlabel=lambda i: f"#{i}",
                   closes=closes)


def test_young_wave_counts_from_the_previous_correction():
    """日 K 第 3 浪才走前一段的 44%（< 0.618）→ 先從 50,265（第 2 浪的起點）數，第一層用 A-B-C（她：C-1 走完、現在 C-2）"""
    seg = N.daily_seg(DAILY)
    assert seg[0]["p"] == 50265 and seg[2] == "C" and seg[3] is True
    out = _build()
    assert out["anchor"]["p"] == 50265 and out["anchor"]["young"] and out["daily_role"] == "C"
    P, A = out["primary"], out["alternate"]
    assert P["path"].startswith("B") and not P["with_trend"]               # 她的 C-2（C-B）
    labs = {m["p"]: m["text"] for m in P["marks"]}
    assert labs[47555].endswith("4-c") and labs[45523] == "A／5" and labs[47607] == "a"
    assert A["path"].startswith("C") and A["with_trend"]                   # B 已在 47,607 結束、C 段主跌（她的 C-3）


def test_not_young_when_new_wave_is_big_or_is_a_correction():
    big = {**DAILY, "labels": DAILY["labels"][:3] + [{"i": 4, "p": 48900, "label": "3"}]}     # 走出前一段的 0.71
    assert N.daily_seg(big)[3] is False and N.daily_seg(big)[0]["p"] == 45523
    corr = {"kind": "impulse", "current": "2", "labels": DAILY["labels"][:3]}                  # B83：第 2 浪（修正）照舊從 50,265
    assert N.daily_seg(corr)[0]["p"] == 50265 and N.daily_seg(corr)[2] == "C" and N.daily_seg(corr)[3] is False


def test_typhoon_gap_still_finds_45523():
    """日 K 把 45,523 標在 10/27（前一根是 10/22），60 分的 45,523 在 10/23 03:00 → 前一根日 K 那天起都算"""
    not_young = {**DAILY, "labels": DAILY["labels"][:3] + [{"i": 4, "p": 48900, "label": "3"}]}
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 2} for p, t, i, _ in LIVE]
    day = {i: dt.date(2026, int(d[:2]), int(d[3:])) for _, _, i, d in LIVE}
    k, how, role, young = N._anchor(pts, not_young, DATES, lambda i: day[i])
    assert how == "daily" and pts[k]["p"] == 45523 and role == "M" and not young


def test_life_line_matches_her_numbers():
    out = _build()
    life = out["life"]
    assert life["zone"] == [46006.0, 46147.9] or (round(life["r70"]) == 46148 and life["origin"] == 46006)
    assert round(life["r618"]) == 46319 and life["bars"] == 14 and not life["broken"]
    g = out["gates"][0]
    assert g["k"] == "生死線" and "46,148～46,006" in g["t"] and "46,319" in g["t"] and "14 根" in g["t"]
    assert "MACD" in g["t"]
    assert out["gates"][-1]["k"] == "失敗" and out["gates"][-1]["t"].endswith("45,523（新低）→ C 段主跌（她的 C-3）")
    v1, v2 = [x for x in out["plan"] if x.startswith("版本")]
    assert "守住 46,148～46,006" in v1 and "C 段主跌" in v2 and "45,523" in v2 and "42,865" in v2   # C＝A 等長（以 47,607 估）


def test_life_line_breaks_and_disappears():
    br = _build(45980.0, add=(45980, "L", 275, "10-30"))                   # 46,637 之後跌破 46,006
    # 她：跌破生死線＝C-2 結束、C-3 主跌 → 系統主要換成 C（B 在 47,607 結束），目標 C＝A 等長 42,865
    assert br["primary"]["path"] == "C" and br["primary"]["with_trend"] and br["life"] is None
    assert any(round(t["price"]) == 42865 for t in br["primary"]["targets"])
    up = _build(47700.0, last=(47700, "H", 275, "10-30"))                  # 過了 B-a 高點 47,607：生死線用不到
    assert up["life"] is None
