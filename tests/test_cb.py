"""可轉債：python -m pytest tests/test_cb.py -q"""
import os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cb.parser import parse_bonds, parse_quotes_csv, parse_conv_adjust, parse_tpex_margin, parse_twse_margin, series_of
from cb.screener import evaluate, short_signal, vol_surge, low_issue

CSV = '''TITLE,櫃檯買賣轉(交)換公司債買賣斷交易行情表-含議價及鉅額交易
DATADATE,日期:115年10月02日
HEADER,代號,名稱,交易,收市,漲跌,開市,最高,最低,筆數,單位,金額,均價,明日參價,明日漲停,明日跌停
BODY,"11011","台泥一永  ","等價","102.00 ","","102.00 ","102.00 ","102.00 ","4       ","25      ","2,550,000     ","102.00 ","102.00 ","112.20 ","91.80  "
BODY,"","","議價","","","","","","","","","","","",""
BODY,"12561","鮮活果汁一KY","等價","","","","","","","","","102.00 ","101.95 ","112.10 ","91.80  "
BODY,"合計","","","","","","","","4,178","17,595","2,230,737,100","","","",""
'''


def test_parse_quotes_and_bonds():
    d, rows = parse_quotes_csv(CSV)
    assert d == "2026-10-02" and len(rows) == 2
    assert rows[0] == {"code": "11011", "name": "台泥一永", "close": 102.0, "chg": None, "volume": 25.0,
                       "amount": 2550000.0, "avg": 102.0, "ref": 102.0}
    assert rows[1]["close"] is None and rows[1]["ref"] == 101.95
    b = parse_bonds([{"BondCode": "11011", "IssuerCode": "1101", "IssuerName": "台泥", "ShortName": "台泥一永",
                      "ListingStatus": "2", "IssueDate": "20241210", "MaturityDate": "20291210", "IssueAmount": "8000000000",
                      "OutstandingAmount": "6000000000", "Conversion/ExchangePriceAtIssuance": "36.5000", "PutOptionDate": "20271210"},
                     {"BondCode": "", "IssuerCode": "00009815", "ListingStatus": "5"}])
    assert len(b) == 1 and b[0]["conv_price_issue"] == 36.5 and b[0]["issue_date"] == "2024-12-10"
    assert series_of("11011", "1101") == 1 and series_of("140202", "1402") == 2


def test_conv_adjust():
    assert parse_conv_adjust("公告本公司國內第三次無擔保轉換公司債轉換價格調整",
                             "自115年09月24日起，國內第三次無擔保轉換公司債轉換價格\n 由新台幣202.3元調整為新台幣199.9元。") == [{"series": 3, "price": 199.9}]
    assert parse_conv_adjust("公告本公司國內第五次無擔保轉換公司債轉換價格及轉換溢價率",
                             "訂定轉換價格為每股新台幣82.23元。因除息，轉換價格由每股新台幣 82.23元調整\n為每股新台幣81.83元")[0]["price"] == 81.83
    assert parse_conv_adjust("公告調整本公司第一次海外無擔保可轉換公司債轉換價格", "由1元調整為2元") == []


def test_margin_parsers():
    tp = {"tables": [{"fields": ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額", "資屬證金", "資使用率(%)", "資限額",
                                 "前券餘額(張)", "券賣", "券買", "券償", "券餘額"], "data": [["3141", "晶宏"] + ["0"] * 12 + ["1,234"]]}]}
    assert parse_tpex_margin(tp) == {"3141": 1234.0}
    tw = {"tables": [{"fields": ["項目"]}, {"fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "限額",
                                                     "買進", "賣出", "現券償還", "前日餘額", "今日餘額"],
                                          "data": [["1101", "台泥", "1", "1", "0", "10", "10", "9", "0", "0", "0", "50", "80"]]}]}
    assert parse_twse_margin(tw) == {"1101": 80.0}


def test_signals_helpers():
    s = short_signal([(f"d{i}", v) for i, v in enumerate([100, 100, 110, 120, 200, 400])])
    assert s["surge"] and not s["drop"]
    s2 = short_signal([(f"d{i}", v) for i, v in enumerate([500, 480, 450, 300, 250, 200])])
    assert s2["drop"]
    q = [{"date": f"d{i}", "volume": 10} for i in range(20)] + [{"date": "x", "volume": 80}]
    assert vol_surge(q)[2]
    closes = [(f"2025{(i // 28) + 1:02d}{(i % 28) + 1:02d}", 100 - i * 0.2) for i in range(200)]
    assert low_issue(closes, closes[150][0]) < 0.1


def _bond(**k):
    b = {"conv_start": None, "code": "11011", "name": "台泥一永", "sid": "1101", "issuer": "台泥", "issue_date": "2026-08-01",
         "maturity_date": "2029-08-01", "issue_amt": 1e9, "outstanding": 9.5e8, "put_date": None}
    b.update(k)
    return b


def test_evaluate_tiers():
    today = date(2026, 10, 3)
    quotes = [{"date": "2026-10-02", "close": 98.0, "volume": 20, "chg": 0.5}]
    closes = [("20261002", 40.0)]
    r = evaluate(_bond(), 36.5, "發行時", quotes, closes, [], {"ym": "11508", "yoy": 12.0, "cum_yoy": -3.0}, today)
    assert r["parity"] == round(40 / 36.5 * 100, 2) and r["gap"] > 0 and r["tier"] == "buy_cb" and r["buy_what"] == "cb"
    assert r["rev_turn"] and "定價後・開放轉換前" in r["stage"] and r["near_par"] and r["shares_per_bond"] == 2740
    shorts = [(f"2026-09-{i:02d}", v) for i, v in enumerate([100, 100, 100, 100, 200, 500], 20)]
    assert evaluate(_bond(), 36.5, "發行時", quotes, closes, shorts, None, today)["tier"] == "exit"
    r2 = evaluate(_bond(issue_date="2024-01-01"), 60, "發行時", [{"date": "2026-10-02", "close": 120.0, "volume": 5}],
                  closes, [], {"yoy": -5.0, "cum_yoy": -2.0}, today)
    assert r2["tier"] == "watch" and r2["premium_pct"] > 30 and not r2["grab"]
    # 上課筆記：CB 市價 > 理論價＋CB 量大增＝搶購訊號
    qs = [{"date": f"2026-09-{i:02d}", "close": 105.0, "volume": 10} for i in range(1, 22)] + \
         [{"date": "2026-10-02", "close": 112.0, "volume": 200}]
    r3 = evaluate(_bond(issue_date="2025-01-01"), 40, "發行時", qs, closes, [], {"yoy": 5.0, "cum_yoy": 3.0}, today)
    assert r3["grab"] and r3["tier"] == "buy_stock" and r3["buy_what"] == "stock"


def test_build_list(tmp_path):
    from cb import db
    from cb.router import build_list
    p = tmp_path / "cb.db"
    db.init_db(p)
    c = db.get_conn(p)
    c.execute("INSERT INTO cb_bond(code,name,sid,issuer,issue_date,maturity_date,issue_amt,outstanding,conv_price_issue) "
              "VALUES ('11011','台泥一永','1101','台泥','2024-12-10','2029-12-10',8e9,8e9,36.5)")
    c.execute("INSERT INTO cb_quote(date,code,close,volume,ref) VALUES ('2026-10-02','11011',102,25,102)")
    c.execute("INSERT INTO cb_conv_adj(sid,series,date,price,subject) VALUES ('1101',1,'2026-07-15',34.0,'x')")
    c.commit()
    rows = build_list(c, date(2026, 10, 3), prices={"1101": [("20261002", 35.0)]})
    assert rows[0]["conv_price"] == 34.0 and "公告調整" in rows[0]["conv_src"]
    c.execute("INSERT INTO cb_manual(code,conv_price) VALUES ('11011',33.0)")
    c.commit()
    assert build_list(c, date(2026, 10, 3), prices={})[0]["conv_src"] == "手動"
    c.close()
