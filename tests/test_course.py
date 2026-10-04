"""上課筆記新增策略：python -m pytest tests/test_course.py -q"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner  # noqa: F401  先載入，登記新策略
from scanner_course import (rsi, weekly, screen_rsi_os, screen_rsi_hot, screen_bias, screen_bb1, screen_wmacd,
                            screen_gap_bottom, screen_limit_open, screen_ma_alldown, COURSE_FNS)
import chip_course as cc


def _df(close, vol=None, gap_at=None):
    n = len(close)
    c = np.asarray(close, float)
    d = pd.bdate_range("2025-01-02", periods=n).strftime("%Y%m%d")
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    v = np.asarray(vol if vol is not None else [1000.0] * n, float)
    return pd.DataFrame({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v})


def test_registered():
    for k in COURSE_FNS:
        assert k in scanner.PRICE_STRATEGY_FNS and k in scanner.STRATEGIES and k in scanner.STRATEGY_PARAMS_SCHEMA
    assert {"S_W60_BREAK", "S_MA_ALLDOWN", "S_DANGER"} <= scanner.SHORT_STRATEGIES
    assert "S_TRUST5" in scanner.STRATEGIES and "S_TRUST5" not in scanner.PRICE_STRATEGY_FNS


def test_rsi_and_weekly():
    r = rsi(pd.Series([10, 11, 12, 13, 14, 15, 16.0]), 6)
    assert r.iloc[-1] > 95
    w = weekly(_df([10.0] * 20))
    assert len(w) == 5 and w["volume"].iloc[0] == 2000 and w["volume"].iloc[1] == 5000


def test_rsi_os_first_hook():
    c = [100.0] * 40 + [100 - 3 * i for i in range(1, 9)] + [80.0]
    res = screen_rsi_os({"1": _df(c)})
    assert len(res) == 1 and res[0]["rsi6"] >= 20
    # 第二次勾起無效
    c2 = [100.0] * 30 + [100 - 3 * i for i in range(1, 8)] + [85.0, 80, 74, 70, 66, 63, 67]
    assert screen_rsi_os({"1": _df(c2)}) == []


def test_rsi_hot_and_bb1():
    c = [50.0] * 70 + [50 * 1.06 ** i for i in range(1, 8)]
    c += [c[-1] * 1.004, c[-1] * 1.006]
    res = screen_rsi_hot({"1": _df(c)}, params={"flat_pct": 4, "ma5_near_pct": 8})
    assert len(res) == 1 and res[0]["hot_days"] >= 3
    assert len(screen_bb1({"1": _df([50.0 + (i % 3) * 0.1 for i in range(60)] + [52, 55, 58, 62, 66])})) == 1


def test_bias():
    c = [100.0] * 80 + [100 * 0.97 ** i for i in range(1, 12)]
    res = screen_bias({"1": _df(c)})
    assert len(res) == 1 and res[0]["bias_min"] <= -20


def test_wmacd_runs_and_alldown():
    c = list(np.linspace(100, 50, 200)) + list(np.linspace(50, 75, 60))
    screen_wmacd({"1": _df(c)})
    c2 = list(np.linspace(50, 100, 80)) + list(np.linspace(100, 80, 15)) + [76.0]
    res = screen_ma_alldown({"1": _df(c2)})
    assert isinstance(res, list)


def test_gap_bottom_and_limit_open():
    c = list(np.linspace(100, 60, 160))
    v = [1000.0] * 160
    v[-3] = 50000
    df = _df(c + [62.0, 66.0], v + [3000, 3000])
    df.loc[len(df) - 1, "low"] = df.loc[len(df) - 2, "high"] * 1.01   # 最後一天向上跳空
    df.loc[len(df) - 1, "open"] = df.loc[len(df) - 1, "low"]
    assert len(screen_gap_bottom({"1": df})) == 1
    c2 = [50.0] * 10 + [55.0, 60.5, 66.55, 68.0]
    d2 = _df(c2, [1000] * 10 + [100, 100, 100, 900])
    d2.loc[11, "open"] = 60.5
    d2.loc[12, "open"] = 66.55
    assert len(screen_limit_open({"1": d2})) == 1


def test_chip_parsers_and_ratios():
    t86 = {"fields": ["證券代號", "證券名稱", "投信買賣超股數"], "data": [["2330", "台積電", "1,000"]]}
    assert cc.parse_t86(t86) == {"2330": 1000.0}
    d, m = cc.parse_tpex_insti([{"Date": "1151002", "SecuritiesCompanyCode": "3141",
                                 "SecuritiesInvestmentTrustCompanies-Difference": "-2000"}])
    assert d == "2026-10-02" and m == {"3141": -2000.0}
    d, rows = cc.parse_tdcc([{"﻿資料日期": "20261002", "證券代號": "2330  ", "持股分級": "15", "人數": "10", "股數": "900"},
                             {"﻿資料日期": "20261002", "證券代號": "2330  ", "持股分級": "1", "人數": "1000", "股數": "100"},
                             {"﻿資料日期": "20261002", "證券代號": "2330  ", "持股分級": "17", "人數": "1010", "股數": "1000"}])
    assert d == "2026-10-02" and len(rows) == 3
    assert cc.holder_ratios({15: 900, 1: 100, 17: 1000}, 50) == (90.0, 10.0)


def test_chip_screens(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "DB_PATH", tmp_path / "course.db")
    c = cc.get_conn()
    days = pd.bdate_range("2026-09-21", periods=8).strftime("%Y-%m-%d")
    for i, d in enumerate(days):
        c.execute("INSERT INTO inst_trust VALUES (?,?,?)", (d, "1111", 5000.0))
        c.execute("INSERT INTO short_bal VALUES (?,?,?)", (d, "1111", 300.0 + (600 if i >= 6 else 0)))
        c.execute("INSERT INTO short_bal VALUES (?,?,?)", (d, "2222", [100, 400, 900, 1000, 900, 800, 700, 600][i]))
    for d, big, small in (("2026-09-18", 40, 30), ("2026-09-25", 41, 29), ("2026-10-02", 42, 28)):
        for t, v in ((15, big), (1, small), (12, 100 - big - small), (17, 100)):
            c.execute("INSERT INTO tdcc_tier VALUES (?,?,?,?,?)", (d, "1111", t, 1, v))
    c.commit()
    up = [50 + i * 0.5 for i in range(80)]
    flat = up + [up[-1] * 1.003, up[-1] * 1.004]
    dfs = {"1111": _df(flat), "2222": _df(up)}
    get = lambda s: dfs.get(s)
    trust = cc._series(c, "inst_trust", "net", "2026-01-01")
    shorts = cc._series(c, "short_bal", "bal", "2026-01-01")
    p = lambda k: {x["key"]: x["default"] for x in cc.CHIP_PARAMS[k]}
    assert [r["stock_id"] for r in cc.screen_trust5(trust, get, {}, p("S_TRUST5"))] == ["1111"]
    assert [r["stock_id"] for r in cc.screen_short_up(shorts, get, {}, p("S_SHORT_UP"))] == ["1111"]
    assert [r["stock_id"] for r in cc.screen_short_ebb(shorts, get, {}, p("S_SHORT_EBB"))] == ["2222"]
    bh = cc.screen_bighold(c, get, {}, p("S_BIGHOLD"))
    assert bh[0]["stock_id"] == "1111" and bh[0]["retail_low"] == "創新低" and bh[0]["big_up_weeks"] == 2
    c.close()
