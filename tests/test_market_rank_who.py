"""全市場排行：三大合計／外資／投信／自營商四種排行榜 × 當天張數／5 日合計／占成交量 %（2026-11-02 用戶：外資排行那頁也要投信、自營商排行）
python -m pytest tests/test_market_rank_who.py -q（不連網）"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market_rank as mr  # noqa: E402

DATES = ["2026-10-30", "2026-10-29", "2026-10-28", "2026-10-27", "2026-10-24", "2026-10-23"]
BY = {   # (外資, 投信, 自營)（張）
    "2330": {d: (5000, -100, 300) for d in DATES},
    "2317": {d: (-800, 1200, -50) for d in DATES},
    "3481": {DATES[0]: (100, 50, 2500), DATES[1]: (0, 10, 900), DATES[2]: (-5, 0, 800)},
    "6488": {DATES[0]: (-50, -900, -1500), DATES[1]: (-10, -100, -20)},
}


def _rows():
    return mr.build_rows(DATES, BY)


def test_dealer_fields():
    r = {x["stock_id"]: x for x in _rows()}
    assert r["3481"]["dealer_streak"] == 3 and r["3481"]["sum5_dealer"] == 4200
    assert r["6488"]["dealer_streak"] == -2 and r["2330"]["dealer_streak"] == 6          # 連續天數看全部載入的日子
    assert r["2317"]["sum5_trust"] == 6000 and r["2317"]["trust_streak"] == 6


def test_four_rankings_and_measures():
    rows = _rows()
    ids = lambda sort, side="buy": [x["stock_id"] for x in mr.filter_sort(rows, side=side, sort=sort)]   # noqa: E731
    assert ids("foreign") == ["2330", "3481"]
    assert ids("trust") == ["2317", "3481"]
    assert ids("dealer") == ["3481", "2330"]
    assert ids("dealer", "sell") == ["6488", "2317"]
    assert ids("sum5_dealer") == ["3481", "2330"] and ids("sum5_trust") == ["2317", "3481"]
    assert ids("total")[0] == "2330"


def test_ratio_per_investor(tmp_path):
    db = tmp_path / "cache.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE price_daily (stock_id TEXT, date TEXT, close REAL, volume REAL)")
    c.executemany("INSERT INTO price_daily VALUES (?,?,?,?)", [("3481", "20261030", 42.55, 10000), ("3481", "20261029", 44.0, 9000)])
    c.commit()
    c.close()
    rows = [x for x in _rows() if x["stock_id"] == "3481"]
    assert mr.attach_prices(rows, "2026-10-30", db)
    r = rows[0]
    assert r["dealer_ratio_pct"] == 25.0 and r["foreign_ratio_pct"] == 1.0 and r["trust_ratio_pct"] == 0.5 and r["vol_ratio_pct"] == 26.5
    assert [x["stock_id"] for x in mr.filter_sort(rows, sort="ratio_dealer")] == ["3481"]


def test_page_has_four_buttons():
    html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.html"), encoding="utf-8").read()
    for w in ("total", "foreign", "trust", "dealer"):
        assert f"setWho('{w}')" in html and f'id="mth-{w}"' in html
    assert 'id="mkt-measure"' in html and "mkt-sort" not in html
