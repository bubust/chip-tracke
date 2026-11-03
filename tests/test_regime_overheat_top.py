"""B91：總經頁最上面的過熱／恐慌（/api/regime/today 附日期、前一筆）：python -m pytest tests/test_regime_overheat_top.py -q"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import regime.db as rdb
import regime.router as rr


def _setup(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(rdb, "DB_PATH", tmp_path / "regime.db")
    with rdb.db() as c:
        c.executescript(rdb.SCHEMA)
        c.executemany("INSERT INTO market_daily (date, series, value) VALUES (?,?,?)", rows)


def test_latest_and_prev(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [("2026-11-02", "OVERHEATING_INDEX", 0.414), ("2026-11-03", "OVERHEATING_INDEX", 0.3867),
                                   ("2026-10-31", "PANIC_INDEX", 0.70), ("2026-11-03", "PANIC_INDEX", 0.7447),
                                   ("2026-11-02", "PANIC_INDEX", None)])
    d = rr._get_overheating_today()
    assert d["overheating"] == 0.3867 and d["overheating_date"] == "2026-11-03" and d["overheating_prev"] == 0.414
    assert d["panic"] == 0.7447 and d["panic_date"] == "2026-11-03" and d["panic_prev"] == 0.70   # 空值那天跳過


def test_empty_and_single(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [("2026-11-03", "PANIC_INDEX", 0.5)])
    d = rr._get_overheating_today()
    assert d["overheating"] is None and d["overheating_date"] is None and d["overheating_prev"] is None
    assert d["panic"] == 0.5 and d["panic_prev"] is None


def test_db_error_returns_nones(monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(rr, "db", boom)
    d = rr._get_overheating_today()
    assert d == {"overheating": None, "panic": None, "overheating_date": None, "panic_date": None,
                 "overheating_prev": None, "panic_prev": None}
