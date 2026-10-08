"""停損滾動修正（PLAN-STOP.md，B55）：python -m pytest tests/test_stop_roll.py -q"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from price_levels import (StructLows, entry_stop, raise_candidate, rolling_stop, roll_label, atr_series,
                          pivots, recent_high, compute_levels)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "stop_3481.csv")


def qunchuang():
    return pd.read_csv(FIX, dtype={"date": str})


def make(closes, spread=0.01):
    n = len(closes)
    d = pd.bdate_range("2025-01-01", periods=n).strftime("%Y%m%d")
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": d, "open": c, "high": c * (1 + spread), "low": c * (1 - spread), "close": c, "volume": [1000] * n})


def naive_lows(h, l, c, j, look, K=3):
    """研究版（research/levels/stop_roll.py）的寫法：每天整段重算"""
    out = set()
    for i in range(max(K, look), j - K + 1):
        if l[i] < l[i - K:i].min() and c[i + 1:i + K + 1].min() >= l[i]:
            out.add(i)
    hs = [i for i in pivots(h[:j + 1], K, "high") if i >= look]
    rh = recent_high(h[:j + 1], K)
    if rh is not None and rh >= look and rh not in hs:
        hs.append(rh)
    bounds = sorted(hs) + [j]
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a >= 2:
            out.add(a + 1 + int(l[a + 1:b].argmin()))
    return sorted(out, reverse=True)


def test_struct_lows_incremental_equals_naive():
    for seed in range(6):
        rng = np.random.default_rng(seed)
        c = 50 * np.exp(np.cumsum(rng.normal(0.002, 0.025, 320)))
        h, l = c * (1 + rng.uniform(0, 0.02, 320)), c * (1 - rng.uniform(0, 0.02, 320))
        S = StructLows(h, l, c)
        for j in range(5, 320, 7):
            assert S.at(j) == naive_lows(h, l, c, j, max(0, j + 1 - 250)), (seed, j)


def test_struct_lows_never_uses_first_three_bars_or_today():
    c = np.array([10, 9, 8, 7.5, 8, 9, 10, 9.5, 9.0, 9.6, 10.2, 10.0])
    h, l = c * 1.01, c * 0.99
    lows = StructLows(h, l, c).at(len(c) - 1)
    assert all(i >= 3 for i in lows if i in StructLows(h, l, c).swing)
    assert len(c) - 1 not in lows


def test_qunchuang_rolls_up_to_platform_low():
    """群創：9/23 加入（收 49.6）停損 46.25（9/14 低點）；9/29 低點 48.55 之後漲到 56.2（>2.5ATR）→ 10/02 上修到 48.55"""
    df = qunchuang()
    idx = df.index[df["date"] == "20260923"][0]
    r = rolling_stop(df, int(idx), "added")
    assert r["entry_date"] == "20260923" and r["entry_stop"] == 46.25 and r["entry_basis"] == "struct"
    raises = [e for e in r["history"] if e["kind"] == "raise"]
    assert raises and raises[-1]["date"] == "20261002" and raises[-1]["price"] == 48.55 and raises[-1]["low_date"] == "20260929"
    assert r["price"] == 48.55 and r["prev"] == 48.55 and r["breached"] is None and not r["frozen"]
    lab = roll_label(r, "added")
    assert "09/23 加入 46.25" in lab and "10/02 上修 48.55（09/29 平台低點）" in lab and "只上不下" in lab
    # 如果今天才買：支撐 50.7 離現價不到 1ATR → 停損放在下一個結構低點 48.55
    lv = compute_levels(df)
    assert lv["stop"]["basis"] == "struct" and lv["stop"]["price"] == 48.55 and "太近" in lv["stop"]["label"]


def test_rolling_only_moves_up_until_breach():
    for seed in range(12):
        rng = np.random.default_rng(100 + seed)
        c = 50 * np.exp(np.cumsum(rng.normal(0.003, 0.02, 200)))
        df = make(list(c), spread=0.015)
        r = rolling_stop(df, 120, "cost", trace=True)
        s = r["stops"]
        assert all(b >= a - 1e-12 for a, b in zip(s, s[1:])), seed
        if r["frozen"]:
            k = next(i for i, e in enumerate(r["history"]) if e["kind"] == "breach")
            assert all(e["kind"] != "raise" for e in r["history"][k:])


def test_breach_holding_freezes_observe_restarts():
    df = qunchuang().copy()
    idx = int(df.index[df["date"] == "20260923"][0])
    n = len(df)
    # 最後一天收盤砸到 47（跌破 48.55）
    df.loc[n - 1, ["close", "low"]] = [47.0, 46.9]
    held = rolling_stop(df, idx, "cost")
    assert held["frozen"] and held["breached"]["date"] == df["date"].iloc[-1] and held["price"] == 48.55
    assert held["prev"] == 48.55                         # 盯盤：今天收盤 < 昨天的停損 → 會發
    watch = rolling_stop(df, idx, "added")
    assert not watch["frozen"] and watch["breached"]["date"] == df["date"].iloc[-1]
    assert watch["active_date"] == df["date"].iloc[-1] and watch["price"] < 47.0
    assert [e["kind"] for e in watch["history"]][-2:] == ["breach", "restart"]


def test_entry_bases_atr_and_trail():
    # 一路漲、沒有結構低點離現價 ≥1ATR → atr
    df = make(list(np.linspace(10, 20, 40)), spread=0.0)
    c, h, l = (df[k].values.astype(float) for k in ("close", "high", "low"))
    atr = atr_series(h, l, c)
    ma = {k: pd.Series(c).rolling(k).mean().values for k in (5, 10, 20)}
    e = entry_stop(c, l, atr, ma[5], ma[10], ma[20], StructLows(h, l, c).at(39), 39)
    assert e["basis"] in ("atr", "trail")
    # 前低遠＋強勢 → trail（沿用 20 日線 −1ATR）
    closes = list(np.linspace(20, 10, 20)) + list(np.linspace(10, 30, 40))
    lv = compute_levels(make(closes))
    assert lv["stop"]["basis"] == "trail" and lv["support"]["kind"] == "ma10"


def test_raise_candidate_needs_rally_and_distance():
    df = qunchuang()
    c, h, l = (df[k].values.astype(float) for k in ("close", "high", "low"))
    atr = atr_series(h, l, c)
    S = StructLows(h, l, c)
    j929 = int(df.index[df["date"] == "20260929"][0])
    j1001 = int(df.index[df["date"] == "20261001"][0])
    j1002 = int(df.index[df["date"] == "20261002"][0])
    assert raise_candidate(c, h, l, atr, S.at(j1001), j1001) != j929     # 9/29 右邊還不滿 3 根：還不能用
    assert raise_candidate(c, h, l, atr, S.at(j1002), j1002) == j929


def test_server_apply_roll_entry_index_and_payload():
    import server
    df = qunchuang()
    lv = compute_levels(df)
    lv["prev"] = {"stop": 1.0, "target": lv.get("target")}
    out = server._apply_roll(lv, df, "20260927", "added")     # 週六加入 → 用 9/24（前一個交易日）
    assert out["roll"]["entry_date"] == "20260924"
    assert out["stop"]["basis"] == "roll" and out["stop_today"]["basis"] == "struct"
    assert out["stop"]["price"] == 48.55 and out["prev"]["stop"] == 48.55        # 盯盤跟「昨天的滾動停損」比
    assert out["prev"]["target"] == lv["prev"]["target"]
    assert lv["stop"]["basis"] == "struct"                    # 快取裡的不能被改
    early = server._apply_roll(lv, df, "20200101", "cost")     # 早於資料 → 從第 0 根（最多往回 250 根）
    assert early["roll"]["entry_date"] == df["date"].iloc[0]
