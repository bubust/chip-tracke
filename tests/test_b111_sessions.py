"""B111 用戶 11/16：台指期日盤、夜盤的漲跌點數要分開
- 11/16 15:18 夜盤顯示「40,908 ▼2,926（-6.68%）」＝拿夜盤價去比上週五日盤收盤 43,834，把當天日盤的大跌（-2,794）也算進去
- 改：夜盤的漲跌比當天日盤收盤（-132）、日盤的漲跌比前一個交易日的日盤收盤；另一盤的結果放旁邊
python -m pytest tests/test_b111_sessions.py -q（不連網）"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import futdata as FD  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=8))
T = lambda *a: int(datetime.datetime(*a, tzinfo=TZ).timestamp())      # noqa: E731


def _sess(st, en, o, c):
    n = (en - st) // 300 + 1
    return [(st + 300 * k, o, max(o, c), min(o, c), o + (c - o) * k / (n - 1), 10) for k in range(n)]


ROWS = (_sess(T(2026, 11, 12, 8, 45), T(2026, 11, 12, 13, 45), 43900, 43500)         # 11/12 日盤收 43,500
        + _sess(T(2026, 11, 12, 15, 0), T(2026, 11, 13, 5, 0), 43500, 43700)
        + _sess(T(2026, 11, 13, 8, 45), T(2026, 11, 13, 13, 45), 43925, 43834)       # 11/13 日盤收 43,834
        + _sess(T(2026, 11, 13, 15, 0), T(2026, 11, 14, 5, 0), 43921, 43701)         # 夜盤收 43,701
        + _sess(T(2026, 11, 16, 8, 45), T(2026, 11, 16, 13, 45), 43300, 41040))      # 11/16 日盤收 41,040
NIGHT = [(T(2026, 11, 16, 15, 0) + 300 * k, 41000, 41010, 40900, 40908, 5) for k in range(4)]
DC = {"2026-11-12": 43500.0, "2026-11-13": 43834.0}


def test_night_change_is_vs_same_day_close():
    """15:18 夜盤：比 11/16 日盤收盤 41,040（-132），不是比 11/13 的 43,834（-2,926）；日盤自己的 -2,794 放旁邊"""
    x = FD.session_changes(ROWS + NIGHT, 40908, T(2026, 11, 16, 15, 18), DC)       # 日資料還沒有 11/16：用 5 分 K 的日盤收盤
    c, o = x["cur"], x["other"]
    assert (c["kind"], c["label"], c["open"], c["ref"], c["chg"], c["chg_pct"]) == ("night", "夜盤", True, 41040.0, -132.0, -0.32)
    assert c["ref_label"] == "11/16 日盤收盤"
    assert (o["kind"], o["label"], o["date"], o["close"], o["ref"], o["chg"], o["chg_pct"]) == ("day", "日盤收", "11/16", 41040.0, 43834.0, -2794.0, -6.37)
    y = FD.session_changes(ROWS + NIGHT, 40908, T(2026, 11, 16, 15, 18), {**DC, "2026-11-16": 41052.0})   # 日資料進來以後用它
    assert y["cur"]["ref"] == 41052.0 and y["cur"]["chg"] == -144.0


def test_day_change_is_vs_prev_day_close_and_shows_night():
    x = FD.session_changes(ROWS[:-45], 42800, T(2026, 11, 16, 10, 0), DC)
    c, o = x["cur"], x["other"]
    assert (c["kind"], c["label"], c["ref"], c["chg"]) == ("day", "日盤", 43834.0, -1034.0) and c["ref_label"] == "11/13 日盤收盤"
    assert (o["kind"], o["label"], o["date"], o["close"], o["chg"], o["chg_pct"]) == ("night", "夜盤收", "11/13", 43701.0, -133.0, -0.3)


def test_between_sessions_and_weekend():
    a = FD.session_changes(ROWS, 41040, T(2026, 11, 16, 14, 20), DC)                # 日盤收了、夜盤還沒開
    assert (a["cur"]["label"], a["cur"]["open"], a["cur"]["chg"]) == ("日盤收", False, -2794.0) and a["other"]["label"] == "夜盤收"
    b = FD.session_changes(ROWS, 41005, T(2026, 11, 16, 15, 0, 20), DC)             # 夜盤剛開、還沒有 5 分 K
    assert (b["cur"]["kind"], b["cur"]["open"], b["cur"]["ref"], b["cur"]["chg"]) == ("night", True, 41040.0, -35.0)
    w = FD.session_changes(ROWS[:-61], 43701, T(2026, 11, 15, 20, 0), DC)           # 週日：最後一盤是 11/13 的夜盤
    assert (w["cur"]["label"], w["cur"]["open"], w["cur"]["ref"], w["cur"]["chg"]) == ("夜盤收", False, 43834.0, -133.0)
    assert (w["other"]["date"], w["other"]["chg"]) == ("11/13", 334.0)             # 11/13 日盤 43,834 比 11/12 的 43,500


def test_not_enough_data():
    assert FD.session_changes([], 41000, T(2026, 11, 16, 20, 0)) is None
    assert FD.session_changes(NIGHT, 40908, T(2026, 11, 16, 15, 18)) is None        # 沒有前面的日盤可以比
