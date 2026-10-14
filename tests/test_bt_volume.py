"""B72 追加：回測進場量能條件（訊號當天量 ≥ 前一天 N 倍）"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_service as S  # noqa: E402
from backtest_engine import ExitConfig, CostConfig  # noqa: E402


def _df(vols):
    n = len(vols)
    c = np.linspace(100, 130, n)
    return pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=n).strftime("%Y%m%d"), "open": c, "high": c * 1.01,
                         "low": c * 0.99, "close": c, "volume": vols})


def test_vol_ratio_mask():
    m = S.vol_ratio_mask(_df([100, 250, 100, 199, 0, 500, np.nan, 300]), 2)
    assert m == [False, True, False, False, False, False, False, False]   # 0、NaN 的前一天不算
    assert S.vol_ratio_mask(_df([1, 2]), 0) is None and S.vol_ratio_mask(_df([1, 2]).drop(columns="volume"), 2) is None


def test_batch_key_unchanged_without_volume():
    ec, cc = ExitConfig(), CostConfig()
    k0 = S.batch_key("S1", {}, 0, ec, cc, 100)
    assert S.batch_key("S1", {}, 0, ec, cc, 100, 0) == k0 != S.batch_key("S1", {}, 0, ec, cc, 100, 2)


def test_run_single_applies_volume_filter(monkeypatch):
    vols = [100.0] * 60
    vols[20] = 300.0                                       # 第 20 天量 3 倍、第 40 天沒放量
    df = _df(vols)
    monkeypatch.setattr(S, "fetch_adjusted_ohlcv", lambda sid, mkt, years: df)
    monkeypatch.setattr(S, "_market_of", lambda sid: "twse")
    sig = [False] * 60
    sig[20] = sig[40] = True
    monkeypatch.setattr(S, "strategy_mask", lambda *a, **k: list(sig))
    ec = ExitConfig(stop="pct", stop_pct=8, trail="none", max_hold=3, take_profit=25)
    r0 = S.run_single("1234", "S1", "fbd", ec, CostConfig(), {})
    r2 = S.run_single("1234", "S1", "fbd", ec, CostConfig(), {}, vol_mult=2)
    d = list(df["date"])
    assert [t["signal_date"] for t in r0["result"]["trades"]] == [d[20], d[40]]
    assert [t["signal_date"] for t in r2["result"]["trades"]] == [d[20]] and r2["vol_mult"] == 2.0
