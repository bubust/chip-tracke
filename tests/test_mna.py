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


# 真實公告內文（2026/09/29 MOPS，節錄）
TWM = ("上市公司 3045 115/09/29 16:07:32 張家麒 代重要子公司台信電訊(股)公司公告延長公開收購精誠 資訊(股)公司普通股之期間 38 115/09/29 "
       "1.決議日期:115/09/29 2.被收購有價證券之公開發行公司名稱: 精誠資訊股份有限公司(下稱「精誠資訊」或「被收購公司」) "
       "3.被收購之有價證券種類:普通股 4.被收購之有價證券數量: 本次預定收購數量為157,900,979股(下稱「預定收購數量」)，約當被收購公司於 "
       "經濟部商工登記公示資料查詢系統顯示民國(以下同)115年3月17日最後異動日所載 之已發行股份總數272,243,066股(下稱「已發行股份總數」)之58%"
       "(157,900,979股/ 272,243,066股≒58%)；惟若最終有效應賣之數量未達預定收購數量，但已達 106,174,796股(約當被收購公司已發行股份總數之39%，"
       "下稱「最低收購數量」)時， 本公開收購之數量條件即告成就。 5.被收購之有價證券價格: 精誠資訊股東應賣一股精誠資訊普通股，可換取台灣大哥大股份有限公司(下稱 "
       "「台灣大哥大」)普通股0.84股及現金新臺幣92.5元 (下稱「公開收購對價」)；任一 應賣人 6.原預訂公開收購期間: 自(臺灣時間)115年8月18日上午9時00分起至115年10月6日"
       "(下稱「收購期間屆滿日」) 下午3時30分止。 7.延長公開收購期間: 自(臺灣時間)115年8月18日上午9時00分起至115年11月5日(下稱「延長期間屆滿日」) 下午3時30分止。 "
       "8.延長公開收購期間之理由: 審查中。")
CHC = ("1.併購種類(如合併、分割、收購或股份受讓): 股份轉換 2.事實發生日:115/9/29 3.參與併購公司名稱(如合併另一方公司、分割新設公司、收購或受讓股份標的公司之 名稱: "
       "收購公司：嘉新水泥股份有限公司（以下簡稱「本公司」或「嘉新水泥」） 被收購公司：嘉新國際股份有限公司（以下簡稱「嘉新國際」） 4.交易相對人: 嘉新國際除本公司外之全體股東 "
       "7.併購目的及條件，包括併購理由、對價條件及支付時點(註七): (1)為整合企業團資源。 (2)每一股嘉新國際股份有限公司普通股股份之對價為現金新台幣15.87元。 "
       "(3)暫定之股份轉換基準日為民國115年12月1日。 10.併購之對價種類及資金來源: 本案以現金為對價，資金來源為自有資金。 "
       "17.預定完成日程(註七): 股份轉換基準日暫訂為115年12月1日。 22.併購完成後之計畫: 本股份轉換完成後，嘉新國際將成為本公司100%持股之子公司。")


def test_parse_tender_offer_detail():
    from mna.parser import parse_detail
    x = parse_detail(TWM, "代重要子公司台信電訊(股)公司公告延長公開收購精誠資訊(股)公司普通股之期間")
    assert x["target_company"] == "精誠資訊股份有限公司" and x["acquirer"] == "台信電訊"
    assert x["offer_price"] == 92.5 and x["stock_ratio"] == 0.84 and x["stock_company"] == "台灣大哥大"
    assert x["consideration"] == "現金＋換股"
    assert x["max_shares"] == 157_900_979 and x["min_shares"] == 106_174_796 and x["offer_pct"] == 58
    assert x["period_start"] == "2026-08-18" and x["period_end"] == "2026-11-05"      # 延長後
    assert x["scope"] == "部分收購"


def test_parse_share_swap_detail():
    from mna.parser import parse_detail
    x = parse_detail(CHC)
    assert x["deal_kind"] == "股份轉換" and x["acquirer"] == "嘉新水泥"
    assert x["target_company"] == "嘉新國際股份有限公司" and x["offer_price"] == 15.87
    assert x["consideration"] == "現金" and x["period_end"] == "2026-12-01" and x["scope"] == "完全收購"


def test_noise_excluded():
    for s in ("公告本公司115年9月合併營業收入淨額", "富邦金控代子公司富邦人壽公告取得「富邦產物保險股份有限公司」使用權資產",
              "公告本公司與子公司簡易合併案(合併基準日異動)。", "更正本公司114年第4季合併及個體財務報告附註部份內容"):
        assert classify(s) is None, s


def test_group_related_announcements():
    from mna.router import group_deals
    rows = [
        {"id": 1, "target_id": "6214", "deal_type": "公開收購", "announce_date": "2026-09-29", "subject": "接獲延長通知", "acquirer": "台信電訊"},
        {"id": 2, "target_id": "6214", "deal_type": "公開收購", "announce_date": "2026-09-29", "subject": "代子公司公告延長",
         "offer_price": 92.5, "stock_ratio": 0.84, "stock_ref": "3045", "period_end": "2026-11-05"},
        {"id": 3, "target_id": "6214", "deal_type": "公開收購", "announce_date": "2026-08-12", "subject": "公告公開收購", "min_shares": 1e8},
        {"id": 4, "target_id": "1103", "deal_type": "股份轉換", "announce_date": "2026-09-29", "subject": "股份轉換"},
    ]
    g = group_deals(rows)
    assert len(g) == 2
    tw = next(x for x in g if x["target_id"] == "6214")
    assert tw["offer_price"] == 92.5 and tw["acquirer"] == "台信電訊" and tw["min_shares"] == 1e8
    assert tw["first_announce"] == "2026-08-12" and len(tw["related"]) == 3
