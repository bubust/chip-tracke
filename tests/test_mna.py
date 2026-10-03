"""收購併購：python -m pytest tests/test_mna.py -q"""
import os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mna.parser import classify, extract, parse_announcements
from mna import db
from mna.router import enrich, classify_status


def test_classify():
    assert classify("代子公司公告公開收購XX科技股份有限公司普通股") == "公開收購"
    assert classify("本公司董事會決議與YY公司進行股份轉換") == "股份轉換"
    assert classify("本公司董事會決議與ZZ公司合併案") == "合併"
    assert classify("公告本公司9月份合併營收") is None
    assert classify("公告本公司董事會決議發放股利") is None


def test_extract_price_shares_period_scope():
    s = "公告公開收購ABC公司普通股，每股新台幣52.5元，最低收購數量1,000,000股，預定收購數量上限30,000,000股，收購期間115/10/05至115/11/03，以現金為對價，部分收購"
    x = extract(s)
    assert x["offer_price"] == 52.5 and x["min_shares"] == 1_000_000 and x["max_shares"] == 30_000_000
    assert x["period_start"] == "2026-10-05" and x["period_end"] == "2026-11-03"
    assert x["scope"] == "部分收購" and x["consideration"] == "現金"
    assert extract("擬以每股現金80元收購全部股權並下市")["scope"] == "完全收購"


def test_parse_mops_table():
    html = """<table><tr><th>公司代號</th><th>公司簡稱</th><th>發言日期</th><th>發言時間</th><th>主旨</th></tr>
    <tr><td>1234</td><td>測試</td><td>115/10/02</td><td>17:30:00</td><td>公告公開收購甲公司普通股，每股新台幣30元</td></tr>
    <tr><td>5678</td><td>無關</td><td>115/10/02</td><td>17:31:00</td><td>公告本公司9月份合併營收</td></tr></table>"""
    recs = parse_announcements(html)
    assert len(recs) == 1 and recs[0]["target_id"] == "1234" and recs[0]["offer_price"] == 30
    assert recs[0]["announce_date"] == "2026-10-02" and recs[0]["deal_type"] == "公開收購"


def test_status_premium_and_manual_not_overwritten(tmp_path):
    p = tmp_path / "m.db"
    db.init_db(p)
    rec = {"target_id": "1234", "announce_date": "2026-10-02", "subject": "公開收購", "deal_type": "公開收購", "source": "MOPS"}
    assert db.upsert_auto([rec], p)["inserted"] == 1
    row = db.all_rows(db_path=p)[0]
    db.save_manual({"offer_price": 30.0, "period_start": "2026-10-05", "period_end": "2026-11-03", "scope": "部分收購"}, row["id"], p)
    db.upsert_auto([{**rec, "offer_price": 99.0}], p)                 # 自動資料不能蓋掉手動填的價格
    row = db.all_rows(db_path=p)[0]
    assert row["offer_price"] == 30.0
    assert classify_status(row, date(2026, 10, 10)) == "進行中"
    assert classify_status(row, date(2026, 11, 10)) == "已結束"
    assert classify_status({**row, "status_override": "已取消"}, date(2026, 10, 10)) == "已取消"
