"""庫藏股解析 / 狀態 / 寫入測試：python -m pytest tests/test_treasury.py -q"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from treasury import db
from treasury.parser import parse_html, parse_any, roc_to_iso
from treasury.router import classify

# MOPS 式的兩列表頭（價格區間、預定買回期間各拆兩欄）
HTML = """
<html><body>
<table><tr><td>本資料由各公司提供</td></tr></table>
<table class='hasBorder'>
<tr class='tblHead'>
 <th rowspan=2>公司代號</th><th rowspan=2>公司名稱</th><th rowspan=2>董事會決議日期</th>
 <th rowspan=2>買回目的</th><th rowspan=2>買回股份總金額上限</th><th rowspan=2>預定買回股數</th>
 <th colspan=2>買回價格區間</th><th colspan=2>預定買回期間</th>
 <th rowspan=2>是否執行完畢</th><th rowspan=2>本次已買回股數</th>
 <th rowspan=2>本次執行完畢已註銷或轉讓股數</th>
 <th rowspan=2>本次已買回股數佔預定買回股數比例(%)</th><th rowspan=2>本次已買回總金額</th>
 <th rowspan=2>本次平均每股買回價格</th><th rowspan=2>本次買回股數佔公司已發行股份總數比例(%)</th>
 <th rowspan=2>本次未執行完畢之原因</th>
</tr>
<tr class='tblHead'><th>最低</th><th>最高</th><th>起</th><th>迄</th></tr>
<tr class='even'><td>2330</td><td>台積電</td><td>113/05/10</td><td>轉讓股份予員工</td>
 <td>1,000,000,000</td><td>5,000,000</td><td>500.00</td><td>900.00</td>
 <td>113/05/13</td><td>113/07/12</td><td>是</td><td>4,000,000</td><td>0</td>
 <td>80.00</td><td>3,200,000,000</td><td>800.00</td><td>0.02</td><td>股價高於區間</td></tr>
<tr class='odd'><td>6488</td><td>環球晶</td><td>113/08/01</td><td>維護公司信用及股東權益</td>
 <td>2,000,000,000</td><td>3,000,000</td><td>300</td><td>600</td>
 <td>113/08/02</td><td>113/10/01</td><td>否</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
</table></body></html>
"""


def test_parse_mops_two_row_header():
    recs = {r["stock_id"]: r for r in parse_html(HTML)}
    assert set(recs) == {"2330", "6488"}
    t = recs["2330"]
    assert t["board_date"] == "2024-05-10" and t["name"] == "台積電"
    assert t["price_low"] == 500 and t["price_high"] == 900
    assert t["period_start"] == "2024-05-13" and t["period_end"] == "2024-07-12"
    assert t["plan_shares"] == 5_000_000 and t["bought_shares"] == 4_000_000
    assert t["exec_ratio"] == 80 and t["avg_price"] == 800 and t["pct_of_capital"] == 0.02
    assert t["bought_amount"] == 3_200_000_000 and t["amount_cap"] == 1_000_000_000
    assert t["done"] == 1 and t["cancelled_shares"] == 0 and t["not_done_reason"] == "股價高於區間"
    g = recs["6488"]
    assert g["done"] == 0 and g["bought_shares"] is None and g["purpose"].startswith("維護")


def test_parse_single_column_ranges_and_reordered():
    html = """<table>
    <tr><th>董事會決議日期</th><th>公司代號</th><th>公司名稱</th><th>預定買回期間</th>
        <th>買回價格區間</th><th>預定買回股數</th></tr>
    <tr><td>1130901</td><td>3008</td><td>大立光</td><td>113/09/02~113/11/01</td>
        <td>1,800.00~2,800.00</td><td>500,000</td></tr></table>"""
    r = parse_html(html)[0]
    assert r["stock_id"] == "3008" and r["board_date"] == "2024-09-01"
    assert r["period_start"] == "2024-09-02" and r["period_end"] == "2024-11-01"
    assert r["price_low"] == 1800 and r["price_high"] == 2800 and r["plan_shares"] == 500000


def test_parse_big5_csv():
    csv_text = ("公司代號,公司名稱,董事會決議日期,買回目的,預定買回股數,買回價格區間-最低,買回價格區間-最高,"
                "預定買回期間-起,預定買回期間-迄\n"
                '"2317","鴻海","113/03/14","轉讓股份予員工","10,000,000","90","150","113/03/15","113/05/14"\n')
    recs = parse_any(csv_text.encode("cp950"))
    assert len(recs) == 1 and recs[0]["name"] == "鴻海" and recs[0]["plan_shares"] == 10_000_000
    assert recs[0]["price_high"] == 150 and recs[0]["period_end"] == "2024-05-14"


def test_no_table_returns_empty():
    assert parse_html("<html><body>查無資料</body></html>") == []
    assert parse_any(b"hello,world\n1,2\n") == []


def test_roc_dates():
    assert roc_to_iso("113/05/10") == "2024-05-10"
    assert roc_to_iso("1130510") == "2024-05-10"
    assert roc_to_iso("2024-05-10") == "2024-05-10"
    assert roc_to_iso("") is None and roc_to_iso("abc") is None


def test_classify_status():
    base = {"period_start": "2024-05-13", "period_end": "2024-07-12", "done": None, "bought_shares": None}
    assert classify(base, date(2024, 5, 11)) == "未開始"
    assert classify(base, date(2024, 6, 1)) == "進行中"
    assert classify(base, date(2024, 7, 20)) == "期滿待申報"
    assert classify({**base, "done": 1, "bought_shares": 4e6}, date(2024, 7, 20)) == "已結束"
    # 期間內就已申報執行完畢 → 已結束
    assert classify({**base, "done": 1, "bought_shares": 4e6}, date(2024, 6, 1)) == "已結束"
    # 期間內 MOPS 顯示「否」（尚未完成）→ 仍算進行中
    assert classify({**base, "done": 0}, date(2024, 6, 1)) == "進行中"


def test_upsert_updates_execution_without_wiping(tmp_path):
    p = tmp_path / "t.db"
    db.init_db(p)
    first = parse_html(HTML)
    g = next(r for r in first if r["stock_id"] == "6488")
    assert db.upsert([g], p) == {"inserted": 1, "updated": 0}
    # 期滿後公司申報執行結果 → 同一筆更新
    done = {**g, "done": 1, "bought_shares": 2_500_000.0, "avg_price": 450.0, "purpose": ""}
    assert db.upsert([done], p) == {"inserted": 0, "updated": 1}
    row = db.all_rows(p)[0]
    assert row["bought_shares"] == 2_500_000 and row["avg_price"] == 450
    assert row["purpose"].startswith("維護")          # 空值不覆蓋舊值
    assert db.upsert([done], p) == {"inserted": 0, "updated": 0}


def test_json_import_from_sync_script():
    import json
    recs = parse_html(HTML)
    back = parse_any(json.dumps(recs, ensure_ascii=False).encode("utf-8"))
    strip = lambda rs: sorted(({k: v for k, v in r.items() if k != "market"} for r in rs), key=lambda r: r["stock_id"])
    assert strip(back) == strip(recs)
    assert parse_any(b'[{"stock_id": "<script>", "board_date": "2024-01-01"}]') == []
