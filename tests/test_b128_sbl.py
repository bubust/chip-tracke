"""B128 借券賣出餘額（證交所 TWT93U＋櫃買信用額度總量管制餘額表）：解析、補抓、彙總
欄位格式照 2026-11-24 GitHub Actions 實測（scratch_probe，已刪）；python -m pytest tests/test_b128_sbl.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import data as D, service as SV  # noqa: E402

F_TWSE = ["代號", "名稱", "前日餘額", "賣出", "買進", "現券", "今日餘額", "次一營業日限額",
          "前日餘額", "當日賣出", "當日還券", "當日調整", "當日餘額", "次一營業日可限額", "備註"]
F_TPEX = ["股票代號", "股票名稱", "前日餘額", "賣出", "買進", "現券", "當日餘額", "限額",
          "前日餘額", "當日賣出", "當日還券", "當日調整數額", "當日餘額", "次一營業日可借券賣出限額", "備註"]


def row(sid, name, prev, sell, ret, bal):
    return [sid, name, "0", "0", "0", "0", "0", "1", f"{prev:,}", f"{sell:,}", f"{ret:,}", "0", f"{bal:,}", "1", " "]


def twse(rows):
    return {"stat": "OK", "date": "20261124", "fields": F_TWSE, "data": rows}


def tpex(rows):
    return {"date": "20261124", "tables": [{"title": "信用額度總量管制餘額表", "fields": F_TPEX, "data": rows}], "stat": "ok"}


def test_parse_both_formats():
    a = D.parse_sbl(twse([row("2330", "台積電", 1_000_000, 300_000, 100_000, 1_200_000), row("00400A", "ETF", 0, 0, 0, 5000)]), "twse")
    assert a[0] == {"sid": "2330", "mkt": "twse", "name": "台積電", "prev": 1e6, "sell": 3e5, "ret": 1e5, "adj": 0.0, "bal": 1.2e6}
    assert len(a) == 2
    b = D.parse_sbl(tpex([row("6488", "環球晶", 0, 2000, 0, 2000)]), "tpex")
    assert b[0]["sid"] == "6488" and b[0]["bal"] == 2000 and b[0]["mkt"] == "tpex"
    assert D.parse_sbl({"stat": "OK", "fields": F_TWSE[:4], "data": []}, "twse") == []        # 假日：沒有資料
    assert D.parse_sbl({"stat": "很抱歉，沒有符合條件的資料!"}, "twse") == []
    assert D.parse_sbl({"stat": "OK", "fields": ["a"] * 15, "data": [row("2330", "x", 1, 1, 1, 1)]}, "twse") == []   # 欄位變了就不收


def test_is_stock():
    assert SV.is_stock("2330") and SV.is_stock("6488")
    assert not SV.is_stock("0050") and not SV.is_stock("00679B") and not SV.is_stock("00400A")


def test_sbl_out_numbers():
    d1 = [{"sid": "2330", "mkt": "twse", "name": "台積電", "sell": 0, "ret": 0, "bal": 1_000_000},
          {"sid": "6488", "mkt": "tpex", "name": "環球晶", "sell": 0, "ret": 0, "bal": 500_000},
          {"sid": "0050", "mkt": "twse", "name": "元大台灣50", "sell": 0, "ret": 0, "bal": 9_000_000}]
    d2 = [{"sid": "2330", "mkt": "twse", "name": "台積電", "sell": 300_000, "ret": 100_000, "bal": 1_200_000},
          {"sid": "6488", "mkt": "tpex", "name": "環球晶", "sell": 0, "ret": 100_000, "bal": 400_000},
          {"sid": "0050", "mkt": "twse", "name": "元大台灣50", "sell": 0, "ret": 0, "bal": 9_000_000}]
    px = {"2330": 1000.0, "6488": 400.0}
    o = SV.sbl_out({"2026-11-21": d1, "2026-11-24": d2}, lambda s, d: px.get(s))
    assert o["ok"] and o["date"] == "2026-11-24"
    assert o["lots"] == 1600 and o["etf_lots"] == 9000                       # ETF 不算進總數
    assert o["amt_yi"] == round((1_200_000 * 1000 + 400_000 * 400) / 1e8, 1) == 13.6
    assert (o["twse_yi"], o["tpex_yi"]) == (12.0, 1.6)
    assert o["chg1"] == 100 and o["chg1_yi"] == round((200_000 * 1000 - 100_000 * 400) / 1e8, 1)
    assert o["chg5"] is None and o["streak"] == 1 and (o["sell"], o["ret"]) == (300, 200)
    assert [t["sid"] for t in o["up"]] == ["2330"] and o["up"][0]["chg"] == 200 and o["up"][0]["chg_yi"] == 2.0
    assert [t["sid"] for t in o["down"]] == ["6488"] and o["down"][0]["chg"] == -100
    assert o["series"][-1]["chg"] == 100 and o["cover"] == 1.0
    n = SV.sbl_out({"2026-11-24": d2})                                       # 沒有收盤價：金額留空、張數照算
    assert n["ok"] and n["amt_yi"] is None and n["lots"] == 1600
    assert SV.sbl_out({})["ok"] is False


def test_update_sbl_fills_missing_days(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "DB_PATH", tmp_path / "wave.db")
    D.init_db()
    with D.db() as c:
        c.executemany("INSERT INTO idx_daily(sym,date,c) VALUES ('TWII',?,1)", [("2026-11-20",), ("2026-11-23",), ("2026-11-24",)])
    calls = []

    def get(m, d):
        calls.append((m, d))
        if d == "2026-11-24" and m == "tpex":
            return tpex([])                                                  # 還沒公布
        return (twse if m == "twse" else tpex)([row("2330" if m == "twse" else "6488", "x", 0, 1000, 0, 1000 + len(calls))])

    assert D.update_sbl(max_fetch=2, get=get, pause=0) == 2                  # 一次最多 2 天，從最新的開始
    assert {d for _, d in calls} == {"2026-11-24", "2026-11-23"}
    calls.clear()
    assert D.update_sbl(get=get, pause=0) == 1                               # 只補缺的：11/24 上櫃、11/20 兩邊
    assert sorted(calls) == [("tpex", "2026-11-20"), ("tpex", "2026-11-24"), ("twse", "2026-11-20")]
    days = D.load_sbl()
    assert sorted(days) == ["2026-11-20", "2026-11-23", "2026-11-24"] and len(days["2026-11-24"]) == 1
