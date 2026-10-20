"""B74 大盤解析：引擎、支撐壓力、特徵、預判、AI 圓桌、資料解析、總經修正、觀察清單加速。
python -m pytest tests/test_b74_wave.py -q（不連網，全部 mock）"""
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import engine as E, levels as LV, features as F, forecast as FC  # noqa: E402


# ── ZigZag ───────────────────────────────────────────────────────────────────
def _series(points, n_between=10):
    """折線 → 日 K（高低＝收盤 ±0.2%）"""
    c = []
    for a, b in zip(points[:-1], points[1:]):
        c += list(np.linspace(a, b, n_between, endpoint=False))
    c.append(points[-1])
    c = np.array(c, dtype=float)
    return c * 1.002, c * 0.998, c


def test_zigzag_confirms_after_reversal_only():
    h, l, c = _series([100, 130, 110, 150, 140], 10)
    piv = E.zigzag(h, l, 0.06)
    kinds = [p["t"] for p in piv]
    assert kinds[:3] == ["L", "H", "L"]
    for p in piv:
        assert p["ci"] > p["i"]                       # 確認一定在極值之後
        assert c[p["ci"]] != 0
    # 因果：截到某一天重算，確認過的轉折一樣
    t = 25
    piv_t = E.zigzag(h[: t + 1], l[: t + 1], 0.06)
    assert [p for p in piv if p["ci"] <= t] == piv_t


def test_state_at_tentative_is_running_extreme():
    h, l, c = _series([100, 130, 110, 150], 10)
    piv = E.zigzag(h, l, 0.06)
    conf, tent = E.state_at(piv, h, l, len(c) - 1)
    assert tent["t"] == "H" and tent["ci"] is None
    assert tent["p"] == pytest.approx(h.max())


# ── 數浪 ─────────────────────────────────────────────────────────────────────
def _pts(prices, start="L"):
    t = start
    out = []
    for i, p in enumerate(prices):
        out.append({"i": i * 10, "p": float(p), "t": t, "ci": i * 10 + 3})
        t = "H" if t == "L" else "L"
    out[-1]["ci"] = None
    return out


def test_textbook_impulse_counted():
    # 0=100 1=120 2=108(回 0.6) 3=140(1.6 倍) 4=132(回 0.25) 5=152（進行中）
    cnt = E.count_waves(_pts([100, 120, 108, 140, 132, 152]))
    p, _ = E.primary_alternate(cnt)
    assert p["kind"] == "impulse" and p["dir"] == 1 and p["current"] == "5"
    assert p["invalid"] == 132 and p["invalid_side"] == "below"
    assert [x["label"] for x in p["labels"]] == ["0", "1", "2", "3", "4", "5"]


def test_hard_rules_reject():
    # 第 4 浪跌進第 1 浪價格區（114 < 120）→ 這個起點不能是推動浪
    bad4 = E.count_waves(_pts([100, 120, 108, 140, 114, 150]))
    assert not any(c["kind"] == "impulse" and c["start"] == 0 and len(c["labels"]) == 6 for c in bad4)
    # 第 2 浪跌破起點
    bad2 = E.count_waves(_pts([100, 120, 95, 140]))
    assert not any(c["kind"] == "impulse" and c["start"] == 0 for c in bad2)
    # 第 3 浪最短（1 浪 30、3 浪 15、5 浪進行中已 20）
    bad3 = E.count_waves(_pts([100, 130, 120, 135, 131, 152]))
    assert not any(c["kind"] == "impulse" and c["start"] == 0 and len(c["labels"]) == 6 for c in bad3)


def test_down_impulse_symmetric():
    up = E.count_waves(_pts([100, 120, 108, 140, 132]))
    dn = E.count_waves(_pts([-x + 300 for x in [100, 120, 108, 140, 132]], start="H"))
    pu, _ = E.primary_alternate(up)
    pd_, _ = E.primary_alternate(dn)
    assert pu["current"] == pd_["current"] and pu["kind"] == pd_["kind"]
    assert pd_["dir"] == -1 and pd_["invalid_side"] == "above"


def test_correction_flat_vs_zigzag():
    flat = E.count_waves(_pts([200, 170, 203, 180], start="H"))       # B 回到 A 起點 1.1 倍 → 平台型
    zig = E.count_waves(_pts([200, 170, 188, 180], start="H"))        # B 回 0.6 → 鋸齒型
    f = [c for c in flat if c["kind"] == "correction" and c["start"] == 0][0]
    z = [c for c in zig if c["kind"] == "correction" and c["start"] == 0][0]
    assert f["corr_kind"] == "flat" and z["corr_kind"] == "zigzag"
    # B 超過 A 的 1.38 倍 → 淘汰
    too = E.count_waves(_pts([200, 170, 215, 190], start="H"))
    assert not any(c["kind"] == "correction" and c["start"] == 0 for c in too)


def test_zero_length_wave_rejected_not_crash():
    cnt = E.count_waves(_pts([100, 100, 90, 120]))          # 第 1 浪長度 0（手動資料）→ 不當成推動浪、不會除以零
    assert not any(c["kind"] == "impulse" and c["start"] == 0 for c in cnt)


def test_fib_retrace_values():
    lv = {x["ratio"]: x["price"] for x in E.fib_retrace(100, 200)}
    assert lv[0.5] == 150 and lv[0.618] == pytest.approx(138.2)


# ── 支撐壓力 ─────────────────────────────────────────────────────────────────
def test_zones_merge_with_width_cap():
    cands = [{"type": "pivot", "price": p, "label": str(p)} for p in (100, 104, 108, 112, 116)]
    zs = LV.make_zones(cands, price=130, atr_v=10)      # 每個差 4 ≤ 5，但整區最寬 10
    assert len(zs) >= 2
    assert all(z["hi"] - z["lo"] <= 10 for z in zs)


def test_zone_type_multi_and_pick_limit():
    cands = [{"type": "pivot", "price": 100, "label": "a"}, {"type": "ma60", "price": 101, "label": "b"},
             {"type": "round", "price": 90, "label": "c"}, {"type": "fib", "price": 120, "label": "d"}]
    zs = LV.make_zones(cands, price=110, atr_v=10, hold={"multi": {"rate": 0.4}})
    z100 = [z for z in zs if z["lo"] == 100][0]
    assert z100["type"] == "multi" and z100["hold"]["rate"] == 0.4 and z100["side"] == "support"
    p = LV.pick(zs, 110, "swing", n=3)
    assert len(p["support"]) <= 3 and p["resistance"][0]["price"] == 120


def test_build_no_resistance_note():
    h, l, c = _series([100, 110, 105, 120, 130, 140, 150, 160, 170], 15)
    an = {d: E.analyze(c, h, l, c, d) for d in ("small", "mid", "big")}
    out = LV.build(h, l, c, len(c) - 1, an, atr_v=2.0)
    for k in ("short", "swing"):
        assert "support" in out[k] and "note" in out[k]


# ── 特徵、預判 ───────────────────────────────────────────────────────────────
def test_streak_counts_trading_rows():
    s = F.streak([1, 2, -1, -3, -2, 0, 5])
    assert list(s) == [1, 2, -1, -2, -3, 0, 1]


def test_align_prev_is_strictly_before():
    tw = pd.Series(["2026-10-19", "2026-10-20"])
    us = pd.DataFrame({"date": ["2026-10-16", "2026-10-19", "2026-10-20"], "c": [1.0, 2.0, 3.0]})
    assert list(F.align_prev(tw, us, "c")) == [1.0, 2.0]       # 台股 10/20 用美股 10/19（前一晚），不用 10/20


def test_chips_from_finmind():
    inst = pd.DataFrame([{"date": "2026-10-20", "name": "Foreign_Investor", "buy": 3e10, "sell": 1e10},
                         {"date": "2026-10-20", "name": "Foreign_Dealer_Self", "buy": 0, "sell": 1e9},
                         {"date": "2026-10-20", "name": "Investment_Trust", "buy": 2e9, "sell": 1e9}])
    fut = pd.DataFrame([{"date": "2026-10-20", "institutional_investors": "外資", "long_open_interest_balance_volume": 1000,
                         "short_open_interest_balance_volume": 5000}])
    mg = pd.DataFrame([{"date": "2026-10-20", "name": "MarginPurchaseMoney", "TodayBalance": 6.4e11}])
    d = F.chips_from_finmind(inst, fut, mg).iloc[0]
    assert d["f_net"] == pytest.approx(190) and d["t_net"] == pytest.approx(10)
    assert d["fut_f_oi"] == -4000 and d["margin_amt"] == pytest.approx(6400)


def _feat(n=400, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    tw = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=n).strftime("%Y-%m-%d"), "o": c, "h": c * 1.01, "l": c * 0.99, "c": c})
    return F.build(tw)


def test_analog_uses_only_known_past_and_falls_back():
    f = _feat()
    t = 300
    a = FC.analog(f, t, ["above_ma60", "dd_b"], horizon=20, min_n=40, start=60)
    assert a["n"] > 0 and a["n"] <= t - 20 - 60 + 1          # 只用 t−20 以前的日子
    big = FC.analog(f, t, ["above_ma60", "dd_b"], horizon=20, min_n=10_000, start=60)
    assert big["fallback"] and big["used"] == []
    f["xx"] = np.nan
    u = FC.analog(f, t, ["xx", "above_ma60"], horizon=20, min_n=5, start=60)
    assert u["unavailable"] == ["xx"] and u["used"] == ["above_ma60"]   # 今天沒資料的條件只跳過它


def test_wilson():
    lo, hi = FC.wilson(50, 100)
    assert 0.39 < lo < 0.41 and 0.59 < hi < 0.61


# ── 資料解析 ─────────────────────────────────────────────────────────────────
def test_parse_yahoo_drops_unfinished_today():
    from wave import data as D
    ts0 = 1760918400            # 2025-10-20 00:00 UTC
    j = {"chart": {"result": [{"meta": {"gmtoffset": 0, "currentTradingPeriod": {"regular": {"start": ts0 + 3600, "end": ts0 + 7 * 3600}}},
                               "timestamp": [ts0 - 86400 + 3600, ts0 + 3600],
                               "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1.0, 2.0], "volume": [0, 0]}]}}]}}
    rows = D.parse_yahoo(j, now_ts=ts0 + 2 * 3600)       # 還沒收盤
    assert [r[0] for r in rows] == ["2025-10-19"]
    rows = D.parse_yahoo(j, now_ts=ts0 + 8 * 3600)       # 收盤後
    assert [r[0] for r in rows] == ["2025-10-19", "2025-10-20"]


def test_parse_twse_hist_and_bfi82u():
    from wave import data as D
    rows = D.parse_twse_hist({"stat": "OK", "data": [["115/10/01", "47,961.98", "48,353.49", "47,893.42", "48,353.49"]]})
    assert rows == [("2026-10-01", 47961.98, 48353.49, 47893.42, 48353.49, None)]
    v = D.parse_bfi82u({"stat": "OK", "data": [["外資及陸資(不含外資自營商)", "1", "2", "-79,539,692,396"], ["外資自營商", "0", "0", "0"],
                                                ["投信", "0", "0", "18,758,508,430"]]})
    assert v == pytest.approx(-795.4, abs=0.01)


# ── AI 圓桌 ──────────────────────────────────────────────────────────────────
@pytest.fixture
def wave_db(tmp_path, monkeypatch):
    from wave import data as D
    monkeypatch.setattr(D, "DB_PATH", tmp_path / "wave.db")
    D.init_db()
    return D


def _snap():
    z = {"price": 45936, "lo": 45882, "hi": 46000, "type_name": "多重重疊", "sources": [{"label": "前高", "price": 45882}],
         "hold": {"rate": 0.38, "placebo": 0.35, "pass": False}}
    r = {**z, "price": 46974, "lo": 46949, "hi": 47000, "sources": [{"label": "整數", "price": 47000}]}
    return {"ok": True, "asof": {"date": "2026-10-20"}, "price": 46293, "prev_close": 46822, "chg_pct": -1.13, "atr": 787,
            "scenario": {"lines": ["主要劇本：C 浪", "x"]}, "levels": {"short": {"support": [z], "resistance": [r]}, "swing": {"support": [z], "resistance": [r]}},
            "waves": {"mid": {"primary": {"invalid": 49969, "targets": [{"price": 41135}], "labels": []}, "pivots": [], "fib": None}},
            "forecast": {"h20": {"lo_px": 44737, "mid_px": 46840, "hi_px": 48628, "p_up": 0.59}}, "chips": {}, "global": {}, "context": {}, "research": {}}


def test_flag_numbers():
    from wave import panel as P
    allowed = P.allowed_levels(_snap())
    bad = P.flag_numbers({"x": "看 45,936 與 41,135，跌破 43,000 再說"}, allowed)
    assert bad == [43000.0]


def test_extract_json_with_think():
    from wave import panel as P
    assert P.extract_json('<think>嗯</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_panel_one_fails_others_continue(wave_db, monkeypatch):
    from wave import panel as P
    ps = [{"id": "a", "name": "A", "kind": "openai", "base": "x", "key": "k", "models": ["ma"]},
          {"id": "b", "name": "B", "kind": "openai", "base": "x", "key": "k", "models": ["mb"]},
          {"id": "c", "name": "C", "kind": "openai", "base": "x", "key": "k", "models": ["mc"]}]
    monkeypatch.setattr(P, "providers", lambda: ps)

    def fake_ask(p, prompt, post=None):
        if p["id"] == "c":
            raise RuntimeError("429 rate limit")
        if "主持人" in prompt:
            return {"model": p["models"][0], "json": {"summary": "偏空 看 45,936", "stance": "偏空"}, "tokens": 10}
        if "第二輪" in prompt:
            return {"model": p["models"][0], "json": {"agree": [], "disagree": [], "stance": "偏空", "view": "v"}, "tokens": 10}
        return {"model": p["models"][0], "json": {"stance": "偏空", "short": "看 99,999", "swing": "s"}, "tokens": 10}
    monkeypatch.setattr(P, "ask", fake_ask)
    r = P.run(_snap(), "manual", news_fn=lambda post=None: {"items": []})
    assert r["mode"] == "roundtable" and len(r["participants"]) == 2
    assert set(r["round2"]) == {"a", "b"} and r["moderator"]["summary"].startswith("偏空")
    assert [f["id"] for f in r["failed"]] == ["c"]
    assert r["flagged"] == []                   # 99,999 超過 80,000，不檢查
    lt = P.latest()
    assert lt["result"]["mode"] == "roundtable"


def test_panel_single_and_cap(wave_db, monkeypatch):
    from wave import panel as P
    real_ask = P.ask
    ps = [{"id": "a", "name": "A", "kind": "openai", "base": "x", "key": "k", "models": ["ma"]}]
    monkeypatch.setattr(P, "providers", lambda: ps)
    monkeypatch.setattr(P, "ask", lambda p, prompt, post=None: {"model": "ma", "json": {"stance": "盤整", "summary": "s"}, "tokens": 5})
    r = P.run(_snap(), "auto", news_fn=lambda post=None: {"items": []})
    assert r["mode"] == "single" and r["round2"] == {}
    # 每日上限：這個模型今天已經用超過 → 不呼叫、丟 OverflowError
    monkeypatch.setenv("PANEL_DAILY_TOKENS", "100")
    P.add_usage("mz", 200)
    called = []
    with pytest.raises(OverflowError):
        real_ask({"id": "z", "kind": "openai", "base": "x", "key": "k", "models": ["mz"]}, "hi",
                 post=lambda *a, **k: called.append(1))
    assert called == []


def test_panel_ask_model_error_raises_runtime(wave_db, monkeypatch):
    from wave import panel as P

    class R:
        status_code = 413

        def json(self):
            return {"error": {"message": "too large"}}
    with pytest.raises(RuntimeError):
        P.ask({"id": "z", "kind": "openai", "base": "x", "key": "k", "models": ["m1", "m2"]}, "hi", post=lambda *a, **k: R())


# ── 推播 ─────────────────────────────────────────────────────────────────────
def test_push_lines(monkeypatch, wave_db):
    from wave import router as WR, panel as P
    s = _snap()
    s["waves"]["mid"]["primary"].update(text="上升推動浪・第 4 浪", invalid_side="below")
    s["waves"]["mid"]["alternate"] = {"text": "A-B-C 修正"}
    s["global"] = {"sox_overnight": {"date": "2026-10-19", "sox_ret": 1.61, "tw_expect": 0.46, "sd": 1.01}}
    monkeypatch.setattr(P, "latest", lambda: {"result": None})
    lines = WR.push_lines(s)
    txt = "\n".join(lines)
    assert "46,293" in txt and "第 4 浪" in txt and "撐 45,936" in txt and "壓 46,974" in txt and "+0.46%" in txt
    assert "不是投資建議" in txt
    assert WR.push_lines({"ok": False}) == []


# ── 總經修正 ─────────────────────────────────────────────────────────────────
def test_iso_date_and_normalize():
    from regime.db import iso_date, normalize_dates, SCHEMA
    assert iso_date("20260923") == iso_date("2026/09/23") == iso_date("2026-09-23") == "2026-09-23"
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("CREATE TABLE regime_meta (key TEXT PRIMARY KEY, value TEXT)")
    ins = "INSERT INTO market_daily(date,series,value,source,updated_at) VALUES(?,?,?,?,?)"
    c.execute(ins, ("20260923", "TAIEX", 1.0, "Y", "2026-09-24 01:00"))
    c.execute(ins, ("2026-09-23", "TAIEX", 2.0, "Y", "2026-09-23 01:00"))     # 舊的
    c.execute(ins, ("20260922", "OTC", 3.0, "Y", "x"))
    c.execute(ins, ("20260922", "BREADTH_50MA", 47.1, "PRICE_DAILY", "x"))      # 舊定義 → 刪
    c.execute(ins, ("2026-09-24", "BREADTH_50MA", 33.5, "TWSE_MI", "x"))      # 舊版（含權證）→ 刪、重抓
    normalize_dates(c)
    rows = {(r["date"], r["series"]): r["value"] for r in c.execute("SELECT * FROM market_daily")}
    assert rows == {("2026-09-23", "TAIEX"): 1.0, ("2026-09-22", "OTC"): 3.0}
    c.execute(ins, ("2026-10-20", "BREADTH_50MA", -40.2, "TWSE_MI", "x"))
    normalize_dates(c)                                                          # 第二次不會再刪
    assert c.execute("SELECT COUNT(*) FROM market_daily WHERE series='BREADTH_50MA'").fetchone()[0] == 1


def test_mi_index_parser_new_labels_uses_stock_column():
    from regime.fetcher import _parse_mi_index_ad
    data = {"stat": "OK", "tables": [{"title": "漲跌證券數合計", "fields": ["類型", "整體市場", "股票"],
                                       "data": [["上漲(漲停)", "6,922(42)", "269(8)"], ["下跌(跌停)", "8,171(85)", "701(0)"], ["持平", "1,297", "104"]]}]}
    assert _parse_mi_index_ad(data) == (269, 701, 104)


# ── 觀察清單加速 ─────────────────────────────────────────────────────────────
def test_summary_calls_yahoo_only_for_missing(monkeypatch):
    import asyncio
    import server
    import supabase_store as sb
    import yahoo_price as yp
    monkeypatch.setattr(sb, "wl_list", lambda: None)
    c = server.get_conn()
    c.execute("DELETE FROM watchlist")
    for sid in ("2330", "9999"):
        c.execute("INSERT INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)", (sid, sid, "2026-10-01", ""))
    c.commit()
    c.close()
    asked = []
    monkeypatch.setattr(yp, "local_prices_for_stocks", lambda ids, min_rows=60: {"2330": {"close": 1.0, "change_pct": 0.0, "bb_score": 0, "stage": {}}})

    async def fake_yahoo(lst):
        asked.extend(s for s, _ in lst)
        return {}
    monkeypatch.setattr(yp, "fetch_prices_for_stocks", fake_yahoo)

    async def no_rt(ids, mkt):
        return {}
    monkeypatch.setattr(server, "_fetch_rt_quotes", no_rt)

    async def no_mis(ids, mkt):
        return {}
    monkeypatch.setattr(server, "_fetch_mis_prices", no_mis)

    async def no_fm(ids):
        return {}
    monkeypatch.setattr(server, "_fetch_finmind_prices", no_fm)
    r = asyncio.run(server.api_watchlist_summary())
    assert asked == ["9999"]
    assert {x["stock_id"] for x in r["items"]} == {"2330", "9999"}
