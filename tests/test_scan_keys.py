"""B72：全市場掃描收結果不能漏策略（以前 STRATEGY_KEYS 手寫清單漏了 S_XIANREN／S_STRONG／S_FIB／S_DBREAK，
KeyError 被吞掉 → 這 4 個永遠 0 檔，同一檔排在後面的策略也一起丟）"""
import asyncio
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_strategy_keys_cover_all_price_strategies():
    import scanner
    import yahoo_price
    missing = [k for k in scanner.PRICE_STRATEGY_FNS if k not in yahoo_price.STRATEGY_KEYS]
    assert missing == []
    for k in ("S_XIANREN", "S_STRONG", "S_FIB", "S_DBREAK", "S_BEST", "S_WARRANT_TOP"):
        assert k in yahoo_price.STRATEGY_KEYS


def test_scan_keeps_every_hit_of_same_stock(monkeypatch, tmp_path):
    """一檔同時中 S_XIANREN、S_BIAS、S_BEST，另一檔中一個沒見過的 key → 全部都要收到"""
    import scanner
    import yahoo_price as yp
    import price_cache
    import chip_course
    import regime.fetcher as rf
    import regime.factor as rfa

    stocks = pd.DataFrame({"stock_id": ["1111", "2222"], "stock_name": ["甲", "乙"], "type": ["twse", "tpex"]})
    df = pd.DataFrame({"date": [f"202610{d:02d}" for d in range(1, 11)], "open": 10.0, "high": 11.0,
                       "low": 9.0, "close": 10.5, "volume": 1000.0})
    hits = {
        "1111": {"S1": None, "S_XIANREN": {"stock_id": "1111", "strategy": "S_XIANREN"},
                 "S_BIAS": {"stock_id": "1111", "strategy": "S_BIAS"},
                 "S_BEST": {"stock_id": "1111", "strategy": "S_BEST"}},
        "2222": {"S_NEW_KEY": {"stock_id": "2222", "strategy": "S_NEW_KEY"},
                 "S_STRONG": {"stock_id": "2222", "strategy": "S_STRONG"}},
    }
    monkeypatch.setattr(yp, "get_stock_list", lambda: stocks)
    monkeypatch.setattr(yp, "_fetch_for_scan", lambda sid, mkt: df)
    monkeypatch.setattr(yp, "_save_scan_cache", lambda r: None)
    monkeypatch.setattr(yp, "refresh_warrant_top", lambda force=True: {"results": [], "note": ""})
    monkeypatch.setattr(yp, "_compute_scan_target", lambda *a: "20261010")
    monkeypatch.setattr(scanner, "scan_one_stock", lambda d, sid, name, **kw: hits[sid])
    monkeypatch.setattr(price_cache, "get_stale_stocks", lambda **kw: set())
    monkeypatch.setattr(price_cache, "DB_PATH", str(tmp_path / "none.db"))
    monkeypatch.setattr(chip_course, "run_all", lambda names, params: {})
    monkeypatch.setattr(rf, "fetch_twse_market_breadth", lambda **kw: None)
    monkeypatch.setattr(rfa, "calculate_factors", lambda: None)

    asyncio.run(yp.run_market_scan({}))
    res = yp._scan_status["results"]
    assert [r["stock_id"] for r in res["S_XIANREN"]] == ["1111"]
    assert [r["stock_id"] for r in res["S_BIAS"]] == ["1111"]
    assert [r["stock_id"] for r in res["S_BEST"]] == ["1111"]
    assert [r["stock_id"] for r in res["S_STRONG"]] == ["2222"]
    assert [r["stock_id"] for r in res["S_NEW_KEY"]] == ["2222"]
    assert res["S1"] == []
