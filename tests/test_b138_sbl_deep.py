"""B138 個股深度分析 → 籌碼加「🔻 借券賣出（張）」（用戶 11/27：「個股分析要有借券資料，我之前不是有讓你做嗎？？我怎麼找不到」）
B128 做的是總經頁（全市場加總）、B129 只換網址沒接畫面；這次用 B128 存的逐檔資料（sbl_stock）接到個股。
python -m pytest tests/test_b138_sbl_deep.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deep_data as DD  # noqa: E402
from wave import data as D  # noqa: E402


def test_sbl_summary():
    rows = [(f"2026-11-{d:02d}", 100_000.0, 50_000.0, 1_000_000.0 + k * 200_000) for k, d in enumerate((20, 21, 24, 25, 26, 27))]
    s = DD.sbl_summary(rows)
    assert s["bal"] == 2000 and s["d1"] == 200 and s["d5"] == 1000 and s["d20"] is None and s["dall"] == 1000 and s["span"] == 5
    assert (s["sell"], s["ret"], s["streak"], s["date"]) == (100, 50, 5, "2026-11-27")
    assert len(s["series"]) == 6 and s["series"][0] == {"date": "2026-11-20", "bal": 1000, "sell": 100, "ret": 50}
    assert DD.sbl_summary([]) is None


def test_load_sbl_one(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "DB_PATH", tmp_path / "wave.db")
    D.init_db()
    with D.db() as c:
        c.executemany("INSERT INTO sbl_stock(date,sid,mkt,name,prev,sell,ret,adj,bal) VALUES(?,?,?,?,?,?,?,?,?)",
                      [("2026-11-26", "3481", "twse", "群創", 0, 1000, 0, 0, 5000), ("2026-11-27", "3481", "twse", "群創", 5000, 2000, 500, 0, 6500),
                       ("2026-11-27", "2330", "twse", "台積電", 0, 1, 1, 0, 9)])
    assert D.load_sbl_one("3481") == [("2026-11-26", 1000.0, 0.0, 5000.0), ("2026-11-27", 2000.0, 500.0, 6500.0)]
    assert D.load_sbl_one("9999") == []


def test_deep_ai_line():
    import deep_ai
    ch = {"sbl": DD.sbl_summary([("2026-11-26", 0, 0, 1_000_000), ("2026-11-27", 300_000, 0, 1_300_000)])}
    txt = deep_ai._data_block({"stock_id": "3481", "name": "群創", "chip": ch}, [])
    assert "借券賣出餘額 1,300 張" in txt and "今天借券賣出 300 張" in txt
