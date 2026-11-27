"""B129 個股借券（chip_tracker_v2）：證交所 TWT93U 新路徑、照位置讀借券賣出的前日／當日餘額
欄位格式照 2026-11-24 GitHub Actions 實測；python -m pytest tests/test_b129_sbl_stock.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chip_tracker_v2 as CT  # noqa: E402

FIELDS = ["代號", "名稱", "前日餘額", "賣出", "買進", "現券", "今日餘額", "次一營業日限額",
          "前日餘額", "當日賣出", "當日還券", "當日調整", "當日餘額", "次一營業日可限額", "備註"]


def row(sid, m_prev, m_bal, s_prev, s_bal):
    return [sid, "x", f"{m_prev:,}", "0", "0", "0", f"{m_bal:,}", "1", f"{s_prev:,}", "0", "0", "0", f"{s_bal:,}", "1", " "]


J = {"stat": "OK", "date": "20261124", "fields": FIELDS,
     "data": [row("2330", 5_000, 9_000, 24_557_000, 17_266_000), row("1303", 0, 0, 193_695_000, 194_737_000)]}


def test_new_url():
    assert CT.ENDPOINTS["sbl"] == "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"


def test_parse_uses_sbl_columns_not_short_sale():
    m = CT.parse_sbl_all(J)
    assert m["2330"]["sbl_chg"] == -7_291_000          # 借券賣出那幾欄（融券的 +4,000 不算）
    assert m["1303"]["sbl_chg"] == 1_042_000
    assert CT.parse_sbl_day(J, "2330") == {"sbl_chg": -7_291_000}
    assert CT.parse_sbl_day(J, "9999") == {"sbl_chg": 0.0}


def test_bad_or_empty():
    assert CT.parse_sbl_all({}) == {}
    assert CT.parse_sbl_all({"stat": "OK", "fields": FIELDS[:4], "data": []}) == {}          # 假日
    assert CT.parse_sbl_all({"stat": "OK", "fields": ["a"] * 15, "data": J["data"]}) == {}   # 欄位變了就不收
