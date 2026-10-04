"""千張大戶比例（集保 OpenAPI 1-5）：python -m pytest tests/test_tdcc.py -q"""
import os, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tdcc_chip

# 2026-10-02 台積電實際資料（GitHub Actions 抓回）
_2330 = [288051941, 855860031, 376217285, 213728529, 142265507, 192135542, 126120924, 92531953, 284154857,
         289013087, 368717442, 283883740, 235281628, 200128136, 21984287365, 7900, 25932370067]


def _rows(sid, shares):
    return [{"證券代號": sid + "  ", "﻿資料日期": "20261002", "持股分級": str(i + 1), "股數": str(v),
             "人數": "1", "占集保庫存數比例%": "0"} for i, v in enumerate(shares)]


def test_parse_matches_official_pct():
    d, m = tdcc_chip._parse_openapi_rows(_rows("2330", _2330))
    assert d == "20261002" and abs(m["2330"] - 84.77) < 0.015  # 官方「占集保庫存數比例%」分級 15 = 84.77（官方無條件捨去）
    assert sum(_2330[:15]) - _2330[15] == _2330[16]          # 分級 1~15 加總 − 16（差異數調整）= 17（合計）


def test_fix_old_values():
    t15, t16, t17 = _2330[14], _2330[15], _2330[16]
    old_api = round((t15 + t16 + t17) / (sum(_2330)) * 100, 2)   # 舊公式
    assert old_api == 92.39
    assert abs(tdcc_chip.fix_value(old_api) - 84.77) <= 0.02
    assert tdcc_chip.fix_value(184.77) == 84.77                    # 本機匯入舊值（15~17 的 % 相加）
    assert tdcc_chip.fix_value(30.0) == 30.0


def test_migration_runs_once(tmp_path, monkeypatch):
    monkeypatch.setattr(tdcc_chip, "DB_PATH", tmp_path / "c.db")
    monkeypatch.setattr(tdcc_chip, "_fixed", False)
    c = sqlite3.connect(tmp_path / "c.db")
    c.execute("CREATE TABLE tdcc_holding (stock_id TEXT, date TEXT, kpct REAL, PRIMARY KEY (stock_id, date))")
    c.execute("INSERT INTO tdcc_holding VALUES ('2330', '20260925', 92.39)")
    c.commit(); c.close()
    tdcc_chip._conn().close()
    monkeypatch.setattr(tdcc_chip, "_fixed", False)
    tdcc_chip._save("20261002", {"2330": 84.80})
    h = tdcc_chip.get_stock_tdcc_history("2330")
    assert h[0]["kpct"] == 84.80 and h[1]["kpct"] == 84.78 and h[0]["change"] == 0.02
