"""PLAN-B73 品質分（quality.py）：F1～F9 各一個合成資料測試、研究（全歷史）＝網站（最近 300 根逐檔讀）、邊界、研究的通過規則"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import quality as Q  # noqa: E402


def _df(c, v=1000.0, n=None, o=None):
    c = np.asarray(c, float)
    n = len(c)
    o = c if o is None else np.asarray(o, float)
    v = np.full(n, v) if np.isscalar(v) else np.asarray(v, float)
    return pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=n).strftime("%Y%m%d"), "open": o, "high": c * 1.01,
                         "low": c * 0.99, "close": c, "volume": v})


def _tab(rows: dict) -> pd.DataFrame:
    return pd.DataFrame({sid: Q.stock_metrics(df).iloc[-1] for sid, df in rows.items()}).T.assign(
        bull=lambda t: t.bull.astype(bool), gap60=lambda t: t.gap60.astype(bool), pool=lambda t: t["pool"].astype(bool))


def _pool(n=30, base=None):
    """股票池 n 檔：價格 50→ 不同漲幅，量 1000 張"""
    base = base or {}
    out = {}
    for i in range(n):
        out[f"{1100 + i}"] = _df(np.linspace(50, 50 * (1 + i / 100), 300))
    out.update(base)
    return out


def test_metrics_basic_and_pool():
    m = Q.stock_metrics(_df(np.linspace(50, 80, 300)))
    last = m.iloc[-1]
    assert bool(last.bull) and last.mslope > 0 and abs(last.pos52 - 1) < 0.05 and bool(last["pool"])
    m2 = Q.stock_metrics(_df(np.linspace(50, 80, 300), v=100.0))           # 量 100 張 → 不在股票池
    assert not bool(m2.iloc[-1]["pool"])
    m3 = Q.stock_metrics(_df(np.linspace(50, 80, 100)))                    # 不到 120 根
    assert not bool(m3.iloc[-1]["pool"])


def test_f1_taiex():
    tx = pd.Series(np.r_[np.full(60, 100.0), [110.0]], index=[f"2025{i:04d}" for i in range(61)])
    assert Q.taiex_above_ma60(tx, tx.index[-1]) is True
    assert Q.taiex_above_ma60(tx.iloc[:30], tx.index[29]) is None
    f = Q.day_flags(_tab(_pool(25)), True, {})
    assert f["F1"].all() and not Q.day_flags(_tab(_pool(25)), None, {})["F1"].any()


def test_f2_f3_f5_f8():
    up = _df(50 * np.cumprod(np.full(300, 1.006)))                      # 每天 +0.6% → 月線斜率 ≈ 0.6%
    down = _df(np.linspace(80, 50, 300))
    hot = _df(np.r_[np.full(280, 50.0), np.linspace(50, 75, 20)])         # 20 天漲 50% → 離月線 > 10%
    f = Q.day_flags(_tab(_pool(25, {"9001": up, "9002": down, "9003": hot})), True, {})
    assert f.at["9001", "F2"] and not f.at["9002", "F2"]
    assert f.at["9001", "F3"] and not f.at["9002", "F3"]
    assert f.at["9001", "F5"] and not f.at["9002", "F5"]
    assert f.at["9001", "F8"] and not f.at["9003", "F8"]


def test_f4_f9_thresholds_from_pool():
    rows = _pool(30)
    rows["9001"] = _df(np.linspace(50, 100, 300), v=100.0)                # 漲最多但不在股票池（量小）→ 仍可跟池子門檻比
    rows["9002"] = _df(np.linspace(50, 50.5, 300), v=50000.0)             # 成交金額最大
    f = Q.day_flags(_tab(rows), True, {})
    assert f.at["9001", "F4"] and not f.at["9002", "F4"]
    assert f.at["9002", "F9"] and not f.at["9001", "F9"]
    assert f.loc[[f"{1100 + i}" for i in range(30)], "F4"].sum() in (9, 10)   # 30 檔裡前 30%


def test_f6_sector_strength():
    rows = {}
    sector = {}
    for s, g in (("A", 0.30), ("B", 0.0), ("C", -0.2)):
        for i in range(4):
            sid = f"{ {'A': 2, 'B': 3, 'C': 4}[s] }{i:03d}".replace(" ", "")
            rows[sid] = _df(np.r_[np.full(280, 50.0), np.linspace(50, 50 * (1 + g), 20)])
            sector[sid] = s
    rows.update(_pool(20))
    rows["9999"] = _df(np.linspace(50, 55, 300))                         # 沒有產業 → 不符合
    f = Q.day_flags(_tab(rows), True, sector)
    assert f.loc[[k for k, v in sector.items() if v == "A"], "F6"].all()
    assert not f.loc[[k for k, v in sector.items() if v != "A"], "F6"].any() and not f.at["9999", "F6"]


def test_f7_volume():
    v = np.full(300, 1000.0); v[-1] = 2000.0
    v2 = np.full(300, 1000.0); v2[-1] = 1200.0
    f = Q.day_flags(_tab(_pool(25, {"9001": _df(np.linspace(50, 60, 300), v=v), "9002": _df(np.linspace(50, 60, 300), v=v2)})), True, {})
    assert f.at["9001", "F7"] and not f.at["9002", "F7"]


def test_edge_nan_zero_and_gap():
    c = np.linspace(50, 60, 300); c[-5] = np.nan
    m = Q.stock_metrics(_df(c))
    assert len(m) == 300                                                  # 不丟例外
    v = np.zeros(300)
    m0 = Q.stock_metrics(_df(np.linspace(50, 60, 300), v=v))
    assert np.isnan(m0.iloc[-1].volr) and not bool(m0.iloc[-1]["pool"])  # 長期 0 量
    o = np.linspace(50, 60, 300); o[-10] = o[-11] * 1.2                  # 開盤跳 20%（除權息之類）→ 60 天內不在股票池
    assert bool(Q.stock_metrics(_df(np.linspace(50, 60, 300), o=o)).iloc[-1].gap60)


def test_live_table_equals_full_history_and_lots_conversion():
    """網站逐檔讀最近 300 根（含「股」單位的舊列，用 lots_volume 換）＝研究用全歷史算出的同一天數字"""
    rng = np.random.default_rng(1)
    full = {}
    for i in range(25):
        c = 50 * np.cumprod(1 + rng.normal(0.0005, 0.02, 600))
        full[f"{2100 + i}"] = _df(c, v=rng.uniform(800, 3000, 600))
    day = full["2100"]["date"].iloc[-1]
    rows = []
    for sid, df in full.items():
        d = df.copy()
        if sid == "2100":
            d.loc[:400, "volume"] = d.loc[:400, "volume"] * 1000          # 舊列存成「股」
        for r in d.itertuples(index=False):
            rows.append((sid, r.date, r.open, r.high, r.low, r.close, r.volume))
    tab, dd = Q.live_table(day, rows_iter=iter(rows))
    assert dd == day and len(tab) == 25
    ref = pd.DataFrame({sid: Q.stock_metrics(df).iloc[-1] for sid, df in full.items()}).T
    for col in ("ret60", "ret20", "turn20", "mslope", "pos52", "volr", "ext", "vol20"):
        assert np.allclose(tab[col].astype(float), ref.loc[tab.index, col].astype(float), equal_nan=True), col
    sec = {sid: "AB"[i % 2] for i, sid in enumerate(full)}
    t1 = tab.assign(bull=tab.bull.astype(bool), gap60=tab.gap60.astype(bool), pool=tab["pool"].astype(bool))
    t2 = ref.assign(bull=ref.bull.astype(bool), gap60=ref.gap60.astype(bool), pool=ref["pool"].astype(bool))
    assert Q.day_flags(t1, True, sec).equals(Q.day_flags(t2.loc[t1.index], True, sec))


def test_annotate_long_only():
    rows = _pool(25, {"9001": _df(np.linspace(50, 80, 300))})
    tab = _tab(rows)
    res = {"S1": [{"stock_id": "9001"}], "S1_SHORT": [{"stock_id": "9001"}], "S_BIGHOLD": [{"stock_id": "0000"}]}
    out = Q.annotate(res, {"S1", "S_BIGHOLD"}, tab=tab, day="20260101", taiex_ok=True, sector_of={})
    q = res["S1"][0]["q"]
    assert out["flagged"] == 1 and "q" not in res["S1_SHORT"][0] and "q" not in res["S_BIGHOLD"][0]
    assert q["date"] == "20260101" and "F2" in q["flags"] and q["score"] <= q["max"]


def test_research_rules():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "b73"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "b72"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "best"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "best2"))
    rq = pytest.importorskip("run_quality")
    adj = rq.bh({"a": 0.01, "b": 0.04, "c": 0.5})
    assert abs(adj["a"] - 0.03) < 1e-9 and abs(adj["b"] - 0.06) < 1e-9 and abs(adj["c"] - 0.5) < 1e-9
    base = {"n": 200, "win": 0.30, "mean": 0.01}
    assert rq.b1_pass({"n": 60, "win": 0.36, "mean": 0.02}, base, 0.05)
    assert not rq.b1_pass({"n": 60, "win": 0.34, "mean": 0.02}, base, 0.05)       # 勝率沒高 5 個百分點
    assert not rq.b1_pass({"n": 40, "win": 0.40, "mean": 0.02}, base, 0.05)       # 樣本外筆數不夠
    assert not rq.b1_pass({"n": 60, "win": 0.40, "mean": 0.02}, base, 0.20)       # 校正後 p 不夠小
    A = pd.DataFrame({"date": ["20240801"] * 10 + ["20240901"] * 10, "ret": [0.1] * 8 + [-0.1] * 2 + [0.1] * 7 + [-0.1] * 3})
    B = pd.DataFrame({"date": ["20240801"] * 10 + ["20240901"] * 10, "ret": [0.1] * 3 + [-0.1] * 7 + [0.1] * 2 + [-0.1] * 8})
    p1, ci1 = rq.month_boot_p(A, B, ("20240701", "20241231"))
    p2, ci2 = rq.month_boot_p(A, B, ("20240701", "20241231"))
    assert p1 == p2 == 0.0 and ci1 == ci2 and ci1[0] > 0                           # 固定種子可重現
