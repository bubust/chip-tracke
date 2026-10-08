"""best_strategy.py（PLAN-BEST）：出場規則、交易計畫、訊號、大盤濾網"""
import numpy as np
import pandas as pd
import pytest

import best_strategy as bs


def _df(closes, vol=1000.0, start="2025-01-01"):
    d = pd.bdate_range(start, periods=len(closes)).strftime("%Y%m%d")
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": d, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": vol})


def test_exit_rule_parse():
    assert bs.exit_rule("E1_5d") == {"kind": "time", "max": 5}
    assert bs.exit_rule("E2_ma5rsi_10d") == {"kind": "ma5", "max": 10}
    assert bs.exit_rule("E3_t1.5_s2_40d") == {"kind": "atr", "tgt": 1.5, "stp": 2.0, "max": 40}
    assert bs.exit_rule("E4_ma20") == {"kind": "ma20", "max": 60}
    assert bs.exit_rule("E5_roll_20d") == {"kind": "roll", "max": 20}
    with pytest.raises(ValueError):
        bs.exit_rule("X")


def test_plan_signal_only_atr():
    A = bs._arrays(_df(np.linspace(50, 60, 200)))
    i = A["n"] - 1
    p = bs.plan_for(A, i, None, bs.exit_rule("E3_t1_s3_20d"))
    a = A["atr"][i]
    assert p["status"] == "signal"
    assert p["stop"] == round(A["c"][i] - 3 * a, 2)
    assert p["target"] == round(A["c"][i] + 1 * a, 2)
    assert p["last_day"] > A["date"][i]


def test_plan_target_hit_then_exit_next_open():
    c = list(np.full(150, 50.0)) + [50.0, 50.0, 50.2, 53.0, 53.5]
    A = bs._arrays(_df(c))
    t = 150
    p = bs.plan_for(A, t, t + 1, bs.exit_rule("E3_t1_s3_20d"))
    assert p["exit_reason"] == "收盤到停利價"
    assert p["exit_date"] == A["date"][153]
    assert p["exit_today"] is False and p["status"] == "exited"
    p2 = bs.plan_for(bs._arrays(_df(c[:154])), t, t + 1, bs.exit_rule("E3_t1_s3_20d"))
    assert p2["exit_today"] is True


def test_plan_time_exit():
    A = bs._arrays(_df(np.linspace(50, 55, 170)))
    p = bs.plan_for(A, 150, 151, bs.exit_rule("E1_5d"))
    assert p["exit_reason"] == "抱滿 5 天" and p["exit_date"] == A["date"][155]
    assert p["last_day"] == A["date"][156]


def test_signal_b1_rsi_and_pool():
    c = list(np.linspace(40, 80, 230)) + [76, 72, 68]
    A = bs._arrays(_df(c))
    i = A["n"] - 1
    assert A["c"][i] > A["ma200"][i] and A["rsi2"][i] <= 5
    assert bs.signal_at(A, i, "B1_ma200_rsi5")
    assert not bs.signal_at(A, i - 3, "B1_ma200_rsi5")
    A2 = bs._arrays(_df(c, vol=100.0))          # 20 日均量 < 500 張 → 不在股票池
    assert not bs.signal_at(A2, i, "B1_ma200_rsi5")


def test_regime_ok():
    idx = pd.bdate_range("2025-01-01", periods=250).strftime("%Y%m%d")
    tx = pd.Series(np.linspace(100, 200, 250), index=idx)
    assert bs.regime_ok(idx[-1], "tx200", tx) is True
    assert bs.regime_ok(idx[-1], "none", tx) is True
    assert bs.regime_ok(idx[100], "tx200", tx) is None
    down = pd.Series(np.linspace(200, 100, 250), index=idx)
    assert bs.regime_ok(idx[-1], "tx60", down) is False


def test_screen_empty_config_returns_nothing(monkeypatch):
    monkeypatch.setitem(bs.CONFIG, "signal", "")
    assert bs.screen_best({"2330": _df(np.linspace(50, 60, 200))}, {}) == []


def test_routes_status_text_and_source():
    import best_routes as br
    assert br.from_best("🔬 研究候選：負乖離＋破底翻抄底")
    assert br.from_best("🏆 研究最佳")
    assert not br.from_best("S1 雙MACD多")
    assert not br.from_best("")
    t = br.status_text({"status": "exit_today", "exit_reason": "收盤到停利價"})
    assert "明天開盤賣" in t and "停利" in t
    t = br.status_text({"status": "holding", "held_days": 3, "max_days": 20, "stop": 95.5, "target": 104.0, "last_day": "20261106"})
    assert "抱第 3/20 天" in t and "損 95.5" in t and "11/06" in t
    t = br.status_text({"status": "signal", "stop": None, "target": None, "last_day": "20261106"})
    assert "｜｜" not in t


def test_config_names_parse():
    """CONFIG 的訊號／出場名稱要認得（研究結果填錯會在這裡抓到）"""
    bs.exit_rule(bs.CONFIG["exit"])
    A = bs._arrays(_df(np.linspace(50, 60, 200)))
    assert bs.signal_at(A, A["n"] - 1, bs.CONFIG["signal"]) in (True, False)


def test_gap_guard_blocks_signal_after_ex_rights():
    """配股除權（單日 > 10.5% 缺口）之後 60 根不出訊號（6669 緯穎 2026-09 的假抄底）"""
    c = list(np.linspace(40, 80, 230)) + [76, 72, 68]
    A = bs._arrays(_df(c))
    assert bs.signal_at(A, A["n"] - 1, "B1_ma200_rsi5")
    c2 = c[:200] + [x / 3 for x in c[200:]]          # 第 200 根除權 3 倍
    A2 = bs._arrays(_df(c2))
    assert bs.gap_guard(A2, 200) and bs.gap_guard(A2, 259 if A2["n"] > 259 else A2["n"] - 1)
    assert not bs.signal_at(A2, A2["n"] - 1, "B1_ma200_rsi5")
    assert not bs.gap_guard(A, A["n"] - 1)


def test_config_matches_research_summary():
    """網站設定＝研究結果（主推，沒有就最接近的候選），PASSED 也要一致"""
    sm = bs.summary()
    if not sm:
        pytest.skip("沒有 summary.json")
    pick = sm.get("main") or sm.get("candidate")
    assert pick, "summary.json 沒有主推也沒有候選"
    assert pick["combo"] == f"{bs.CONFIG['signal']}|{bs.CONFIG['regime']}|{bs.CONFIG['exit']}"
    assert bs.PASSED == bool(sm.get("main"))


def test_watch_plan_cost_and_added(monkeypatch):
    """觀察清單：沒成本＝訊號隔天開盤進場；有成本＝填成本那天是買進日、訊號在之前；不是這個方法也沒成本＝不算"""
    import best_routes as br
    c = list(np.linspace(40, 80, 230)) + [76, 72, 68, 70, 71, 72]
    df = _df(c)
    monkeypatch.setitem(bs.CONFIG, "signal", "B1_ma200_rsi5")
    monkeypatch.setitem(bs.CONFIG, "exit", "E1_5d")
    d = list(df["date"])
    sig_day = d[232]
    assert br.watch_plan("2330", "S1", sig_day, None, None, df=df) is None
    p = br.watch_plan("2330", "🔬 研究候選", sig_day, None, None, df=df)
    assert p["signal_date"] == sig_day and p["status"] == "holding" and p["held_days"] == 3
    p2 = br.watch_plan("2330", "", None, 69.0, d[233], df=df)
    assert p2["signal_date"] == sig_day and p2["entry_price"] == 69.0 and p2["held_days"] == 3
    df2 = df.assign(date=[f"{x[:4]}-{x[4:6]}-{x[6:]}" for x in df["date"]])
    p3 = br.watch_plan("2330", "🔬 研究候選", f"{sig_day[:4]}-{sig_day[4:6]}-{sig_day[6:]}T21:00:00", None, None, df=df2)
    assert p3["signal_date"] == sig_day
