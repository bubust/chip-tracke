"""PLAN-LINK／BEST2 網站模組：連動股相關係數、民國日期、大跌買點門檻"""
import numpy as np
import pandas as pd
import pytest

import linkage
import disposal
import crash_routes


def test_corr_matrix_matches_numpy():
    rng = np.random.default_rng(1)
    R = rng.normal(size=(60, 5))
    R[:, 1] = R[:, 0] * 0.8 + rng.normal(size=60) * 0.2
    got = linkage._corr_matrix(R)
    want = np.corrcoef(R.T)
    assert np.allclose(got, want, atol=1e-9)


def test_corr_matrix_handles_halt_and_flat():
    R = np.random.default_rng(2).normal(size=(60, 3))
    R[5:10, 0] = np.nan          # 停牌幾天
    R[:, 2] = 0.0                # 完全沒動 → 相關 NaN
    m = linkage._corr_matrix(R)
    assert np.isfinite(m[0, 1]) and np.isnan(m[2, 0])


def test_roc_date():
    assert disposal._roc("115/10/09") == "20261009"
    assert disposal._roc("114.01.03") == "20250103"
    assert disposal._roc("") == ""


def test_crash_today_state(monkeypatch):
    import best_strategy as bs
    idx = pd.bdate_range("2026-01-01", periods=80).strftime("%Y%m%d")
    vals = np.r_[np.full(71, 100.0), np.linspace(100, 84, 9)]        # 前一天 −14%、今天 −16%＝今天第一次跌破 15%
    monkeypatch.setattr(bs, "taiex_series", lambda: pd.Series(vals, index=idx))
    monkeypatch.setattr(crash_routes, "_bias_count", lambda: 120)
    st = crash_routes.today_state()
    assert st["deep"]["T1_dd15"] and st["deep"]["T3_bias100"]
    assert st["dd"] == pytest.approx(-0.16, abs=1e-6)
    assert "T1_dd15" in st["deep_first_today"]
    vals2 = np.full(80, 100.0)
    monkeypatch.setattr(bs, "taiex_series", lambda: pd.Series(vals2, index=idx))
    monkeypatch.setattr(crash_routes, "_bias_count", lambda: 3)
    st2 = crash_routes.today_state()
    assert not any(st2["deep"].values()) and st2["deep_first_today"] == []


def test_pool_excludes_recent_ex_rights_gap():
    idx = pd.bdate_range("2026-01-01", periods=130).strftime("%Y%m%d")
    close = pd.DataFrame({"1111": np.linspace(50, 60, 130), "2222": np.r_[np.full(100, 90.0), np.full(30, 30.0)]}, index=idx)
    vol = pd.DataFrame(1000.0, index=idx, columns=close.columns)
    vol.attrs["open"] = close.copy()
    p = linkage._pool(close, vol)
    assert bool(p["1111"]) and not bool(p["2222"])      # 2222 第 100 根 90→30（配股除權）→ 60 根內不進股票池
