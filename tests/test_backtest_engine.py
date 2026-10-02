"""PLAN-BACKTEST §6 單元測試：python -m pytest tests/test_backtest_engine.py -q"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import (ExitConfig, CostConfig, simulate, compute_stats,
                             wilder_atr, adjust_ohlcv, summary_sentence)

NO_STOPS = dict(stop="none", trail="none", max_hold=0)


def make_df(rows, start="2024-01-01"):
    """rows: list of (open, high, low, close) 或 close；回傳含 date 的 df"""
    dates = pd.bdate_range(start, periods=len(rows)).strftime("%Y%m%d")
    recs = []
    for d, r in zip(dates, rows):
        if isinstance(r, (int, float)):
            r = (r, r * 1.01, r * 0.99, r)
        o, h, l, c = r
        recs.append({"date": d, "open": o, "high": h, "low": l, "close": c, "volume": 1000})
    return pd.DataFrame(recs)


def flat(n, px=100.0, rng=1.0):
    """n 根平盤 K 線（high/low ± rng），ATR ≈ 2*rng"""
    return [(px, px + rng, px - rng, px) for _ in range(n)]


def mask_at(n, *idx):
    m = [False] * n
    for i in idx:
        m[i] = True
    return m


# 1. 跳空跌破停損 → 以開盤價出場
def test_gap_below_stop_exits_at_open():
    rows = flat(20) + [(100, 101, 99, 100), (90, 91, 88, 89)]
    df = make_df(rows)
    cfg = ExitConfig(stop="pct", stop_pct=5, trail="none", max_hold=0)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert len(trades) == 1
    t = trades[0]
    assert t["entry_price"] == 100 and t["exit_reason"] == "停損"
    assert t["exit_price"] == 90            # 開盤價，不是 95 停損價


def test_intraday_stop_exits_at_stop_price():
    rows = flat(20) + [(100, 101, 99, 100), (99, 100, 94, 99)]
    df = make_df(rows)
    cfg = ExitConfig(stop="pct", stop_pct=5, trail="none", max_hold=0)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert trades[0]["exit_price"] == 95 and trades[0]["exit_reason"] == "停損"


# 2. 同日觸及停損與停利 → 記為停損
def test_same_day_stop_and_tp_counts_as_stop():
    rows = flat(20) + [(100, 101, 99, 100), (100, 115, 90, 100)]
    df = make_df(rows)
    cfg = ExitConfig(stop="pct", stop_pct=5, trail="none", max_hold=0, take_profit=10)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert trades[0]["exit_reason"] == "停損"
    assert trades[0]["exit_price"] == 95


# 3. 持倉中重複訊號不新增交易
def test_no_pyramiding_while_in_position():
    n = 40
    df = make_df(flat(n))
    m = [False] * n
    for i in range(20, 30):
        m[i] = True
    cfg = ExitConfig(**{**NO_STOPS, "max_hold": 15})
    trades, open_t, _ = simulate(df, m, "long", cfg, CostConfig(0))
    assert len(trades) == 1 and open_t is None
    # 出場（第 35 根收盤）之後才能再進場：在第 35 根給訊號 → 第 36 根開盤進場
    m2 = list(m); m2[35] = True
    trades2, open2, _ = simulate(df, m2, "long", cfg, CostConfig(0))
    assert trades2[0]["exit_date"] == df["date"][35]
    assert open2 is not None and open2["entry_date"] == df["date"][36]


# 4. 成本扣除：無漲跌來回報酬 = −0.585%
def test_cost_deducted_flat_trade():
    df = make_df(flat(30))
    cfg = ExitConfig(**{**NO_STOPS, "max_hold": 3})
    trades, _, _ = simulate(df, mask_at(30, 20), "long", cfg, CostConfig())
    assert trades[0]["gross_return"] == 0
    assert trades[0]["return"] == pytest.approx(-0.00585)


# 5. 未平倉不計入勝率
def test_open_trade_excluded_from_stats():
    rows = flat(20) + [100, 101, 102, 103, 104, 150]
    df = make_df(rows)
    cfg = ExitConfig(**NO_STOPS)
    trades, open_t, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert trades == [] and open_t["status"] == "open"
    assert open_t["return"] > 0
    assert compute_stats(trades + [open_t]) == {"count": 0}


# 6. 移動停損只上移不下移
def test_trailing_stop_only_moves_up():
    up = [(100 + k, 101 + k, 99 + k, 100.5 + k) for k in range(10)]        # 漲到 ~110
    down = [(108, 109, 107.5, 108), (107.6, 108, 107.2, 107.5)]            # 小回檔，不夠觸發
    crash = [(107, 107.5, 100, 101)]
    rows = flat(20) + up + down + crash
    df = make_df(rows)
    cfg = ExitConfig(stop="none", trail="pct", trail_pct=3, max_hold=0)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    t = trades[0]
    assert t["exit_reason"] == "移動停損"
    peak = max(r[1] for r in up + down)
    assert t["exit_price"] == pytest.approx(round(peak * 0.97, 2))


# 7. 做空方向停損/停利對稱
def test_short_stop_and_take_profit():
    rows = flat(20) + [(100, 101, 99, 100), (101, 106, 100, 104)]
    df = make_df(rows)
    cfg = ExitConfig(stop="pct", stop_pct=5, trail="none", max_hold=0, take_profit=10)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "short", cfg, CostConfig(0))
    assert trades[0]["exit_reason"] == "停損" and trades[0]["exit_price"] == 105
    assert trades[0]["gross_return"] == pytest.approx(-0.05)

    rows = flat(20) + [(100, 101, 99, 100), (95, 96, 89, 90)]
    df = make_df(rows)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "short", cfg, CostConfig(0))
    assert trades[0]["exit_reason"] == "停利" and trades[0]["exit_price"] == 90
    assert trades[0]["gross_return"] == pytest.approx(0.10)

    # 做空跳空開高越過停損 → 開盤價
    rows = flat(20) + [(100, 101, 99, 100), (108, 109, 107, 108)]
    df = make_df(rows)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "short", cfg, CostConfig(0))
    assert trades[0]["exit_price"] == 108


# 8. 漲停鎖死不進場；跌停鎖死時多單出場順延到下一個可成交日開盤
def test_limit_up_locked_entry_skipped():
    rows = flat(20) + [(110, 110, 110, 110)]        # 前收 100 → 漲停 110 一價到底
    df = make_df(rows)
    trades, open_t, info = simulate(df, mask_at(len(df), 19), "long",
                                    ExitConfig(**NO_STOPS), CostConfig(0))
    assert trades == [] and open_t is None and info["blocked_entries"] == 1


def test_limit_down_locked_exit_deferred():
    rows = flat(20) + [(100, 101, 99, 100), (90, 90, 90, 90), (81, 81, 81, 81), (75, 80, 74, 78)]
    df = make_df(rows)
    cfg = ExitConfig(stop="pct", stop_pct=5, trail="none", max_hold=0)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    t = trades[0]
    assert t["exit_date"] == df["date"][23] and t["exit_price"] == 75


def test_short_limit_down_locked_entry_skipped():
    rows = flat(20) + [(90, 90, 90, 90)]
    df = make_df(rows)
    trades, open_t, info = simulate(df, mask_at(len(df), 19), "short",
                                    ExitConfig(**NO_STOPS), CostConfig(0))
    assert trades == [] and open_t is None and info["blocked_entries"] == 1


# 10. 上市不到 20 根：ATR NaN 時不交易、不報錯
def test_short_history_no_trades_no_error():
    df = make_df(flat(10))
    trades, open_t, info = simulate(df, [True] * 10, "long", ExitConfig(), CostConfig())
    assert trades == [] and open_t is None and info["first_date"] is None
    df = make_df(flat(18))
    trades, open_t, _ = simulate(df, [True] * 18, "long", ExitConfig(), CostConfig())
    # 第 14 根（index 13）起 ATR 才有值，早於此的訊號不能進場
    assert open_t is None or open_t["signal_date"] >= df["date"][13]


# 11. 除息日：還原價無跳空不觸發停損；同資料原始價會觸發
def test_ex_dividend_uses_adjusted_prices():
    rows = flat(20, 100, 0.5) + [(100, 100.5, 99.5, 100), (93, 93.5, 92.5, 93), (93, 93.5, 92.5, 93)]
    df = make_df(rows)
    # 第 21 根除息 7 元：之前的 adjclose = close × 0.93
    adj = [r[3] * 0.93 for r in rows[:21]] + [r[3] for r in rows[21:]]
    df["adjclose"] = adj
    cfg = ExitConfig(stop="pct", stop_pct=5, trail="none", max_hold=0)
    raw_trades, _, _ = simulate(df.drop(columns="adjclose"), mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert raw_trades and raw_trades[0]["exit_reason"] == "停損"
    adj_df = adjust_ohlcv(df)
    trades, open_t, _ = simulate(adj_df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert trades == [] and open_t is not None
    assert open_t["entry_price"] == 100        # 顯示的是當天實際成交價


# 12. ATR 與手算 Wilder 一致
def test_wilder_atr_matches_manual():
    rng = np.random.default_rng(0)
    c = 100 + np.cumsum(rng.normal(0, 1, 60))
    h = c + rng.uniform(0.1, 2, 60)
    l = c - rng.uniform(0.1, 2, 60)
    atr = wilder_atr(h, l, c, 14)
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])) for i in range(1, 60)]
    manual = [float("nan")] * 13 + [sum(tr[:14]) / 14]
    for i in range(14, 60):
        manual.append((manual[-1] * 13 + tr[i]) / 14)
    assert np.isnan(atr[:13]).all()
    assert np.allclose(atr[13:], manual[13:], atol=1e-6)


def test_atr_stop_and_max_hold_defaults():
    df = make_df(flat(100, 100, 1.0))
    trades, _, _ = simulate(df, mask_at(100, 20), "long", ExitConfig(), CostConfig(0))
    # 平盤 ATR=2 → 停損 96 打不到；移動停損 101-5=96 也打不到 → 第 60 天收盤到期
    assert trades[0]["exit_reason"] == "天數到期" and trades[0]["hold_days"] == 60
    assert trades[0]["stop_price"] == pytest.approx(96, abs=0.01)


def test_exit_ma_exits_next_open():
    rows = flat(20) + [(100, 101, 99, 100), (100, 101, 99, 100), (99, 99.5, 95, 96), (97, 98, 96, 97)]
    df = make_df(rows)
    cfg = ExitConfig(stop="none", trail="none", max_hold=0, exit_ma=5)
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert trades[0]["exit_reason"] == "破MA5"
    assert trades[0]["exit_date"] == df["date"][23] and trades[0]["exit_price"] == 97


def test_entry_close_mode():
    rows = flat(20) + [(100, 101, 99, 102)]
    df = make_df(rows)
    cfg = ExitConfig(**{**NO_STOPS, "max_hold": 1, "entry": "close"})
    trades, _, _ = simulate(df, mask_at(len(df), 19), "long", cfg, CostConfig(0))
    assert trades[0]["entry_date"] == df["date"][19] and trades[0]["exit_price"] == 102


def test_compute_stats_metrics():
    def t(r, d):
        return {"return": r, "exit_date": d, "entry_date": d, "hold_days": 5,
                "exit_reason": "停損" if r < 0 else "停利", "status": "closed"}
    trades = [t(0.10, "20240101"), t(-0.05, "20240102"), t(-0.05, "20240103"), t(0.04, "20240104")]
    s = compute_stats(trades)
    assert s["count"] == 4 and s["win_rate"] == 0.5
    assert s["expectancy"] == pytest.approx(0.01)
    assert s["payoff_ratio"] == pytest.approx(0.07 / 0.05, abs=1e-3)
    assert s["profit_factor"] == pytest.approx(0.14 / 0.10, abs=1e-3)
    assert s["max_consec_losses"] == 2
    assert s["max_drawdown"] == pytest.approx(0.95 * 0.95 - 1, abs=1e-4)
    assert s["low_sample"] is True
    assert "4 筆交易" in summary_sentence(s, {"first_date": "20200101", "last_date": "20250101",
                                              "buy_hold_return": 0.5})


# 9. mask 快取命中時，只改出場參數不會重新呼叫 screen 函式
def test_mask_cache_hit_skips_screen(tmp_path):
    from backtest_service import MaskStore, strategy_mask
    calls = []

    def fake_screen(df, key, params=None, min_vol_ratio=0.0):
        calls.append(key)
        return mask_at(len(df), 20)

    df = adjust_ohlcv(make_df(flat(100)))
    store = MaskStore(tmp_path / "bt.db")
    m1 = strategy_mask(df, "2330", "S1", {"a": 1}, 0.0, store=store, persist=True, compute_fn=fake_screen)
    t1, _, _ = simulate(df, m1, "long", ExitConfig(), CostConfig())
    # 新的 MaskStore（模擬重啟，記憶體快取清空）→ 從 SQLite 讀到
    store2 = MaskStore(tmp_path / "bt.db")
    m2 = strategy_mask(df, "2330", "S1", {"a": 1}, 0.0, store=store2, compute_fn=fake_screen)
    t2, _, _ = simulate(df, m2, "long", ExitConfig(max_hold=10), CostConfig())
    assert calls == ["S1"] and m1 == m2
    assert t1[0]["hold_days"] == 60 and t2[0]["hold_days"] == 10
    # 策略參數改變 → 重新計算
    strategy_mask(df, "2330", "S1", {"a": 2}, 0.0, store=store2, compute_fn=fake_screen)
    assert calls == ["S1", "S1"]
    # 資料改變（回溯修正）→ hash 不同 → 重新計算
    df2 = df.copy(); df2.loc[50, "close"] = 101.0
    strategy_mask(df2, "2330", "S1", {"a": 1}, 0.0, store=store2, compute_fn=fake_screen)
    assert len(calls) == 3
