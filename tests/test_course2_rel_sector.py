"""2026-10-04：上課筆記第二份策略、市場關聯台指期挑契約、產業輪動日期轉換"""
import numpy as np
import pandas as pd

import scanner  # noqa: F401  先載入 scanner，scanner_course 才拿得到共用函式
import scanner_course as sc
from relationship.fetcher import _pick_tx
from sector.prices import _roc_to_ymd


def _df(closes, opens=None, highs=None, lows=None, vols=None):
    n = len(closes)
    c = np.asarray(closes, float)
    return pd.DataFrame({
        "date": [f"2026{i:04d}" for i in range(n)],
        "open": opens if opens is not None else c,
        "high": highs if highs is not None else c * 1.01,
        "low": lows if lows is not None else c * 0.99,
        "close": c,
        "volume": vols if vols is not None else [1000.0] * n,
    })


def test_kdj_range_and_extremes():
    up = _df(np.linspace(10, 30, 60))
    k, d, j = sc.kdj(up)
    assert k[-1] > 80 and d[-1] > 80                     # 一路漲 → 高檔
    down = _df(np.linspace(30, 10, 60))
    k, d, j = sc.kdj(down)
    assert k[-1] < 20 and d[-1] < 20 and j[-1] < k[-1]   # 一路跌 → 低檔
    assert np.allclose(j, 3 * k - 2 * d)


def test_breakbottom_signal_and_fail():
    closes = list(np.linspace(100, 75, 70))
    o = [x * 1.005 for x in closes]
    h = [x * 1.01 for x in closes]
    l = [x * 0.99 for x in closes]
    # 昨天長黑收最低
    closes[-2], o[-2], h[-2], l[-2] = 70.0, 74.5, 74.6, 69.9
    # 今天守住昨天低點
    closes[-1], o[-1], h[-1], l[-1] = 71.5, 70.5, 72.0, 70.2
    df = _df(closes, o, h, l)
    r = sc.screen_breakbottom({"T": df})
    assert r and r[0]["stop"] == 69.9
    df2 = df.copy()
    df2.loc[len(df2) - 1, "low"] = 69.0                  # 今天又破底 → 失效
    assert sc.screen_breakbottom({"T": df2}) == []


def test_new_strategies_registered():
    for k in ("S_KDJ_LOW", "S_BREAKBOTTOM", "S_NBREAK", "S_VOLROLL", "S_KDJ_HIGH", "S_KDJ_DIV"):
        assert k in scanner.PRICE_STRATEGY_FNS and k in scanner.STRATEGY_PARAMS_SCHEMA
    assert {"S_KDJ_HIGH", "S_KDJ_DIV"} <= scanner.SHORT_STRATEGIES


def test_pick_tx_uses_highest_volume_month_and_sums_oi():
    rows = {"2026-10-01": [("202610", 1, 2, 0.5, 100.0, 0.5, 30000.0, 90000.0),
                           ("202611", 1, 2, 0.5, 101.0, 0.6, 800.0, 1500.0)]}
    out = _pick_tx(rows)
    assert out[0]["tx_contract"] == "202610" and out[0]["tx_close"] == 100.0
    assert out[0]["tx_chg_pct"] == 0.5 and out[0]["total_oi"] == 91500.0


def test_roc_date():
    assert _roc_to_ymd("1151002") == "20261002"
    assert _roc_to_ymd("") == "" and _roc_to_ymd("2026-10-02") == ""


def test_sector_mapping_merges_aliases_and_prefers_specific_latest():
    from sector.universe import build_mapping
    rows = [
        {"stock_id": "2330", "industry_category": "電子工業", "type": "twse", "date": "2026-10-04"},
        {"stock_id": "2330", "industry_category": "半導體業", "type": "twse", "date": "2026-10-04"},
        {"stock_id": "6015", "industry_category": "金融業", "type": "tpex", "date": "2026-10-04"},
        {"stock_id": "2881", "industry_category": "金融保險", "type": "twse", "date": "2026-10-04"},
        {"stock_id": "6195", "industry_category": "貿易百貨", "type": "tpex", "date": "2023-06-29"},
        {"stock_id": "6195", "industry_category": "居家生活類", "type": "tpex", "date": "2026-10-04"},
        {"stock_id": "710553", "industry_category": "所有證券", "type": "twse", "date": "2026-10-04"},
        {"stock_id": "7777", "industry_category": "半導體業", "type": "emerging", "date": "2026-10-04"},
    ]
    m = build_mapping(rows)
    assert m == {"2330": "半導體業", "6015": "金融保險", "2881": "金融保險", "6195": "居家生活"}
