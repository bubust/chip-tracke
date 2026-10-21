"""B75：台指期連續月、逐筆檔、分 K 彙總、盤別、鉅亨解析、轉折點、超短線價位、綜合研判、融資增減、API。
python -m pytest tests/test_b75_futures.py -q（不連網，全部 mock）"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import composite as CP, engine as E, futdata as FD, keylevel as KL, levels as LV  # noqa: E402

TW = timezone(timedelta(hours=8))


def ts(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=TW).timestamp())


@pytest.fixture
def wave_db(tmp_path, monkeypatch):
    from wave import data as D
    monkeypatch.setattr(D, "DB_PATH", tmp_path / "wave.db")
    D.init_db()
    return D


# ── 連續月（§3.2）────────────────────────────────────────────────────────────
def _fm(rows):
    cols = ["date", "contract_date", "trading_session", "open", "max", "min", "close", "volume", "open_interest"]
    return pd.DataFrame(rows, columns=cols)


def test_select_continuous_roll_uses_same_contract_ref_close():
    df = _fm([
        # 9/16 結算日：日盤 09 月量最大（夜盤也是 09 月）
        ("2026-09-15", "202609", "position", 100, 101, 99, 100, 900, 50),
        ("2026-09-15", "202610", "position", 110, 111, 109, 110, 100, 60),
        ("2026-09-16", "202609", "after_market", 100, 101, 99, 100.5, 400, 0),
        ("2026-09-16", "202609", "position", 100, 102, 99, 101, 800, 10),
        ("2026-09-16", "202610", "position", 111, 112, 110, 112, 700, 90),
        ("2026-09-16", "202609/202610", "position", 1, 1, 1, 1, 99999, 0),     # 價差：排除
        ("2026-09-16", "202609W4", "position", 1, 1, 1, 1, 99999, 0),          # 週契約：排除
        # 9/17：夜盤（9/16 15:00 開始）已經是 10 月 → 分母要用 10 月 9/16 的日盤收 112，不是 09 月的 101
        ("2026-09-17", "202610", "after_market", 112, 114, 111, 113, 500, 0),
        ("2026-09-17", "202610", "position", 113, 115, 112, 114, 900, 95),
    ])
    sel = FD.select_continuous(df)
    d16 = sel[sel.date == "2026-09-16"]
    assert set(d16.contract) == {"202609"} and set(d16.sess) == {"day", "night"}
    n17 = sel[(sel.date == "2026-09-17") & (sel.sess == "night")].iloc[0]
    assert n17.contract == "202610" and n17.ref_close == 112
    nr = FD.night_returns(sel)
    assert nr[nr.date == "2026-09-17"].night_ret.iloc[0] == pytest.approx(113 / 112 - 1)
    # 夜盤的 oi 不存（夜盤沒有結算未平倉）
    assert pd.isna(n17.oi)


def test_full_bars_open_from_night_close_from_day_and_skip_unfinished():
    fd = pd.DataFrame([
        {"date": "2026-10-20", "sess": "night", "contract": "202610", "o": 100, "h": 105, "l": 95, "c": 101, "v": 10, "oi": None, "ref_close": 99},
        {"date": "2026-10-20", "sess": "day", "contract": "202610", "o": 101, "h": 103, "l": 98, "c": 102, "v": 20, "oi": 5, "ref_close": None},
        {"date": "2026-10-21", "sess": "night", "contract": "202610", "o": 103, "h": 104, "l": 100, "c": 103, "v": 7, "oi": None, "ref_close": 102},
    ])
    fb = FD.full_bars(fd)
    assert list(fb.date) == ["2026-10-20"]          # 10/21 日盤還沒收 → 不出
    r = fb.iloc[0]
    assert (r.o, r.h, r.l, r.c, r.v) == (100, 105, 95, 102, 30)


# ── 期交所逐筆檔（§3.5）──────────────────────────────────────────────────────
TICKS = """成交日期,商品代號,到期月份(週別),成交時間,成交價格,成交數量(B+S),近月價格,遠月價格,開盤集合競價
20261019,TX     ,202610     ,150000,46842,74,-,-,*
20261019,TX     ,202610     ,150230,46850,10,-,-,
20261019,TX     ,202610     ,150459,46830,6,-,-,
20261019,TX     ,202611     ,150100,46900,2,-,-,
20261019,TX     ,202610/202611,150100,50,4,-,-,
20261019,MTX    ,202610     ,150100,1,4,-,-,
20261020,TX     ,202610     ,084500,46700,20,-,-,*
20261020,TX     ,202610     ,134500,46400,8,-,-,
"""


def _zip(txt):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Daily_2026_10_20.csv", txt.encode("cp950"))
    return b.getvalue()


def test_parse_taifex_ticks_bins_volume_and_month():
    agg = FD.parse_taifex_ticks(io.StringIO(TICKS))
    assert set(agg) == {"202610", "202611"}            # 價差、小台不算
    b = agg["202610"][ts(2026, 10, 19, 15, 0)]
    assert b == [46842, 46850, 46830, 46830, 45.0]     # 量 ÷2：(74+10+6)/2
    rows = FD.select_tick_month(agg)
    assert all(r[0] % 300 == 0 for r in rows)
    assert rows[0][0] == ts(2026, 10, 19, 15, 0)


def test_fetch_taifex_day_streams_zip_and_404():
    class R:
        def __init__(self, content, code=200):
            self.content, self.status_code = content, code
    rows = FD.fetch_taifex_day(datetime(2026, 10, 20).date(), get=lambda u: R(_zip(TICKS)))
    assert len(rows) == 3
    with pytest.raises(FileNotFoundError):
        FD.fetch_taifex_day(datetime(2026, 10, 20).date(), get=lambda u: R(b"<html>no</html>"))


# ── 分 K 彙總與盤別（§4.1、§5）──────────────────────────────────────────────
def _five(sym, start, n, px=100.0):
    return [(start + 300 * k, px + k, px + k + 1, px + k - 1, px + k + 0.5, 1) for k in range(n)]


def test_agg_twii_60m_anchor_and_closing_auction_merged():
    rows = _five("TWII", ts(2026, 10, 20, 9, 0), 54)
    rows.append((ts(2026, 10, 20, 13, 30), 200, 201, 199, 200, 5))        # 13:30 收盤撮合那根
    b60 = FD.agg_bars(rows, "TWII", 60)
    assert [FD.tw_dt(b["time"]).strftime("%H:%M") for b in b60] == ["09:00", "10:00", "11:00", "12:00", "13:00"]
    assert b60[-1]["close"] == 200 and b60[-1]["high"] == 201
    b30 = FD.agg_bars(rows, "TWII", 30)
    assert len(b30) == 9 and FD.tw_dt(b30[-1]["time"]).strftime("%H:%M") == "13:00"


def test_agg_tx_day_and_night_anchors():
    day = _five("TX", ts(2026, 10, 20, 8, 45), 60)
    night = _five("TX", ts(2026, 10, 20, 15, 0), 168)
    b60 = FD.agg_bars(day + night, "TX", 60)
    hrs = [FD.tw_dt(b["time"]).strftime("%H:%M") for b in b60]
    assert hrs[:5] == ["08:45", "09:45", "10:45", "11:45", "12:45"]
    assert hrs[5] == "15:00" and hrs[-1] == "04:00" and len(b60) == 5 + 14
    assert len(FD.agg_bars(day + night, "TX", 30)) == 10 + 28


def test_session_and_in_session_boundaries():
    assert FD.session_of("TX", ts(2026, 10, 21, 0, 30))[0] == "night"
    assert FD.session_of("TX", ts(2026, 10, 21, 7, 0)) is None
    fri_night = datetime(2026, 10, 23, 23, 0, tzinfo=TW)
    sat_early = datetime(2026, 10, 24, 4, 50, tzinfo=TW)
    sun = datetime(2026, 10, 25, 20, 0, tzinfo=TW)
    mon_early = datetime(2026, 10, 26, 0, 30, tzinfo=TW)
    assert FD.in_session("TX", fri_night) and FD.in_session("TX", sat_early)
    assert not FD.in_session("TX", sun) and not FD.in_session("TX", mon_early)
    assert FD.in_session("TX", datetime(2026, 10, 21, 8, 46, tzinfo=TW)) and not FD.in_session("TWII", datetime(2026, 10, 21, 8, 46, tzinfo=TW))
    assert not FD.in_session("TX", datetime(2026, 10, 21, 14, 30, tzinfo=TW))


# ── 鉅亨 ─────────────────────────────────────────────────────────────────────
def test_parse_cnyes_hist_and_quote():
    j = {"statusCode": 200, "data": {"t": [300, 0], "o": [2, 1], "h": [3, 2], "l": [1, 0], "c": [2.5, 1.5], "v": [5, 4]}}
    assert FD.parse_cnyes_hist(j) == [(0, 1, 2, 0, 1.5, 4), (300, 2, 3, 1, 2.5, 5)]
    q = FD.parse_cnyes_quote({"data": [{"6": 47054.0, "21": 46384.0, "12": 47288.0, "13": 46136.0, "19": 46490.0, "200007": 1792545286}]})
    assert q["price"] == 47054 and q["ref"] == 46384
    assert FD.parse_cnyes_quote({"data": [{"6": "-"}]}) is None


def test_save_bars5_only_completed(wave_db):
    rows = [(1000, 1, 2, 0, 1, 1), (1300, 1, 2, 0, 1, 1)]
    assert FD.save_bars5("TX", rows, "T", now_ts=1599) == 1      # 1300 那根到 1600 才收完
    assert [r[0] for r in FD.load_bars5("TX")] == [1000]


# ── 轉折點（§2）─────────────────────────────────────────────────────────────
def _path(points, n=6):
    c = []
    for a, b in zip(points[:-1], points[1:]):
        c += list(np.linspace(a, b, n, endpoint=False))
    c.append(points[-1])
    c = np.array(c, float)
    return c * 1.001, c * 0.999, c


def test_key_level_up_leg_takes_nearest_k3_low_below_price():
    # 一路上漲中間有小回檔 → 上漲段：轉弱點＝現價下方最近的 k3 低點
    h, l, c = _path([100, 130, 124, 140, 135, 150], 8)
    piv = E.zigzag(h, l, 0.15)
    an = E.analyze(h, h, l, c, "small", piv=piv)
    t = len(c) - 1
    atr = float(E.atr(h, l, c)[-1])
    cands = KL.candidates(an, h, l, c, t, atr)
    assert cands["dir"] == 1 and cands["K3"]["side"] == "below"
    lows = [p["p"] for p in LV.k3_pivots(h, l, t) if p["t"] == "L"]
    assert cands["K3"]["price"] == max(x for x in lows if x <= c[t] - 0.5 * atr)
    k = KL.pick(cands, "K3", float(c[t]), atr)
    assert k["kind"] == "轉弱點" and k["dist_pct"] < 0


def test_key_level_down_leg_and_fallback_to_k2():
    h, l, c = _path([100, 160, 150], 10)          # 大漲後小跌：下跌段，起點＝高點；之後沒有 k3 高點 → K2
    piv = E.zigzag(h, l, 0.05)
    an = E.analyze(h, h, l, c, "small", piv=piv)
    cands = KL.candidates(an, h, l, c, len(c) - 1, float(E.atr(h, l, c)[-1]))
    assert cands["dir"] == -1 and cands["K3"]["side"] == "above"
    assert cands["K3"]["price"] == pytest.approx(cands["K2"]["price"])
    k = KL.pick(cands, "K3", float(c[-1]), 1.0, wave_invalid={"price": 50.0, "side": "below"})
    assert k["kind"] == "轉強點" and k["wave_invalid"] == 50


def test_follow_through():
    c = np.array([100, 100, 98.0, 96, 95, 94, 93])
    h, l = c + 0.5, c - 0.5
    atr = np.full(len(c), 2.0)
    assert KL.follow_through(h, l, c, atr, 99.5, "below", 0, 6) == 1      # 收 < 98.5 確認、再到 96.5 以下
    c2 = np.array([100, 100, 98.0, 99, 100, 101, 101])
    assert KL.follow_through(c2 + 0.5, c2 - 0.5, c2, atr, 99.5, "below", 0, 6) == 0
    assert KL.follow_through(h, l, c, atr, 80, "below", 0, 6) is None


# ── 超短線價位（§4.3）────────────────────────────────────────────────────────
def test_build_ultra_window_and_daily_sources():
    h, l, c = _path([46000, 47000, 46500, 47300, 47100], 10)
    piv = E.zigzag(h, l, 0.005)
    an = E.analyze(h, h, l, c, "intra", piv=piv)
    lv = LV.build_ultra(h, l, c, len(c) - 1, an, 120.0, 47100.0, daily={"prev_h": 47250, "prev_l": 46600, "prev_c": 47000, "ma20": 46000})
    for z in lv["support"]:
        assert z["price"] < 47100 and z["price"] >= 47100 * 0.97
    for z in lv["resistance"]:
        assert z["price"] > 47100 and z["price"] <= 47100 * 1.03
    labels = [s["label"] for z in lv["support"] + lv["resistance"] for s in z["sources"]]
    assert any("昨天" in x for x in labels)


def test_intraday_degree_not_in_daily_degrees():
    assert "intra" not in E.DEGREES and E.deg_cfg("intra") is E.INTRA


# ── 綜合研判、融資（§6）──────────────────────────────────────────────────────
def test_state_of_polarity_and_direction_only_passed():
    r = {"edges": [-0.1, 0.1], "polarity": -1, "kind": "terc", "pass": True}
    assert CP.state_of("retail", 0.3, r) == -1          # 通過：用研究 polarity（反向）→ 偏空
    assert CP.state_of("retail", -0.3, r) == 1
    assert CP.state_of("retail", 0.0, r) == 0
    # 沒通過：用市場一般解讀（外資選擇權偏多部位減少＝偏空），不套研究的 polarity
    r2 = {"edges": [-0.1, 0.1], "polarity": -1, "kind": "terc", "pass": False}
    assert CP.state_of("opt_chg1", -0.3, r2) == -1 and CP.state_of("margin_chg5", -0.3, r2) == 1
    reg = {"kind": "reg", "alpha": 0.0, "beta": 0.5, "polarity": 1}
    assert CP.state_of("night_ret", 0.01, reg) == 1 and CP.state_of("night_ret", 0.001, reg) == 0
    d = CP.direction([("a", 1, True), ("b", -1, False), ("c", 1, True)])
    assert d["score"] == 2 and d["used"] == ["a", "c"]
    assert CP.direction([("b", -1, False)])["score"] is None


def test_margin_block_streak_hist_pending():
    ch = pd.DataFrame({"date": [f"2026-10-{d:02d}" for d in range(1, 11)], "margin_amt": [100, 101, 102, 101, 100, 99, 98, 99, 100, 97]})
    m = CP.margin_block(ch, today="2026-10-11")
    assert m["amt"] == 97 and m["chg1"] == -3 and m["streak"] == -1 and m["chg5"] == pytest.approx(97 - 100)
    assert len(m["hist"]) == 9 and m["hist"][-1]["chg"] == -3 and "pending" in m
    ch2 = ch.copy()
    ch2.loc[ch2.index[-1], "margin_amt"] = 103
    assert CP.margin_block(ch2)["streak"] == 3


def test_composite_build_no_lookahead_in_z_and_targets():
    n = 120
    tw = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=n).strftime("%Y-%m-%d"),
                       "o": np.linspace(100, 120, n), "h": np.linspace(101, 121, n), "l": np.linspace(99, 119, n), "c": np.linspace(100.5, 120.5, n)})
    fd = pd.DataFrame([{"date": d, "sess": "day", "contract": "x", "o": 1, "h": 1, "l": 1, "c": c + (5 if i == n - 1 else 0), "v": 1, "oi": 1, "ref_close": None}
                       for i, (d, c) in enumerate(zip(tw.date, tw.c))])
    df = CP.build(tw, fd)
    # 最後一天價差突然變大：z 要用「前 60 天」算 → 很大的正值（如果把當天算進平均會被稀釋）
    assert df.basis_z.iloc[-1] > 5
    # fwdo5 從隔天開盤起算
    assert df.fwdo5.iloc[0] == pytest.approx(tw.c.iloc[5] / tw.o.iloc[1] - 1)


def test_fut_chips_retail_ratio_and_option_sign():
    mtx = pd.DataFrame([{"date": "2026-10-20", "contract_date": "202610", "trading_session": "position", "open_interest": 100},
                        {"date": "2026-10-20", "contract_date": "202611", "trading_session": "position", "open_interest": 100},
                        {"date": "2026-10-20", "contract_date": "202610", "trading_session": "after_market", "open_interest": 999}])
    inst = pd.DataFrame([{"date": "2026-10-20", "long_open_interest_balance_volume": 20, "short_open_interest_balance_volume": 60}])
    txo = pd.DataFrame([
        {"date": "2026-10-20", "institutional_investors": "外資", "call_put": "買權", "long_open_interest_balance_amount": 100, "short_open_interest_balance_amount": 40},
        {"date": "2026-10-20", "institutional_investors": "外資", "call_put": "賣權", "long_open_interest_balance_amount": 30, "short_open_interest_balance_amount": 10},
        {"date": "2026-10-20", "institutional_investors": "自營商", "call_put": "買權", "long_open_interest_balance_amount": 999, "short_open_interest_balance_amount": 0}])
    r = FD.fut_chips_from_finmind(mtx, inst, txo).iloc[0]
    assert r.mtx_oi == 200 and r.retail_ratio == pytest.approx((60 - 20) / 200)
    assert r.opt_f_bull == pytest.approx((100 - 40) - (30 - 10))


# ── API、快取、圓桌 ─────────────────────────────────────────────────────────
def test_snapshot_rejects_bad_sym_and_caches_per_sym(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from wave import router as WR, service as S
    calls = []
    monkeypatch.setattr(S, "compute", lambda sym, live=None, rows=None: calls.append(sym) or {"ok": True, "sym": sym})
    monkeypatch.setattr(S.FD, "in_session", lambda sym, now=None: False)
    for s in S.SYMS:
        S._cache[s].update(t=0.0, data=None, session=None)
    app = FastAPI()
    app.include_router(WR.router)
    cl = TestClient(app)
    assert cl.get("/api/wave/snapshot?sym=XX").status_code == 400
    assert cl.get("/api/wave/snapshot?sym=TX").json()["sym"] == "TX"
    assert cl.get("/api/wave/snapshot").json()["sym"] == "TWII"
    assert cl.get("/api/wave/snapshot?sym=TX").json()["sym"] == "TX"      # 快取：不再算
    assert calls == ["TX", "TWII"]


def test_last_good_kinds_per_sym(wave_db):
    from wave import service as S
    with wave_db.db() as c:
        c.execute("INSERT INTO wave_snapshot(day,kind,created_at,json) VALUES('2026-10-20','close','x',?)", (json.dumps({"ok": True, "sym": "TWII"}),))
        c.execute("INSERT INTO wave_snapshot(day,kind,created_at,json) VALUES('2026-10-21','TX:live','x',?)", (json.dumps({"ok": True, "sym": "TX"}),))
    assert S.last_good("TWII")["sym"] == "TWII" and S.last_good("TX")["sym"] == "TX"


def test_panel_allowed_levels_include_tx_ultra_key():
    from wave import panel as P
    z = {"price": 47000, "lo": 46990, "hi": 47010, "sources": [{"price": 47000}]}
    base = {"price": 47100, "prev_close": 46900, "levels": {"short": {"support": [z], "resistance": []}, "swing": {"support": [], "resistance": []},
                                                            "ultra": {"support": [{**z, "price": 46800}], "resistance": []}},
            "waves": {}, "forecast": {}, "key": {"short": {"price": 49969, "wave_invalid": 39385}}}
    snap = {**base, "tx": {**base, "ok": True, "price": 47222, "basis": {"twii": 47186}}}
    al = P.allowed_levels(snap)
    for v in (46800, 49969, 39385, 47222, 47186):
        assert v in al
    assert P.flag_numbers({"x": "看 46,800 和 39,385"}, al) == []


def test_intraday_bars_partial_flag(wave_db):
    from wave import intraday as I
    start = ts(2026, 10, 21, 9, 0)
    FD.save_bars5("TWII", _five("TWII", start, 18), "T", now_ts=start + 18 * 300)     # 09:00～10:25
    out = I.bars("TWII", 60, now_ts=start + 90 * 60)                                  # 10:30：10:00 那根還沒收
    assert len(out) == 2 and out[0].get("partial") is None and out[-1].get("partial") is True
    assert I.bars("TWII", 60, now_ts=start + 121 * 60)[-1].get("partial") is None


def test_agg_nan_volume_and_full_bars_missing_night_hl():
    rows = [(ts(2026, 10, 20, 9, 0), 1, 2, 0, 1, float("nan")), (ts(2026, 10, 20, 9, 5), 1, 2, 0, 1, 3)]
    assert FD.agg_bars(rows, "TWII", 60)[0]["volume"] == 3
    fd = pd.DataFrame([
        {"date": "2026-10-20", "sess": "night", "contract": "x", "o": 100, "h": None, "l": float("nan"), "c": 101, "v": 1, "oi": None, "ref_close": 99},
        {"date": "2026-10-20", "sess": "day", "contract": "x", "o": 101, "h": 103, "l": 98, "c": 102, "v": 2, "oi": 5, "ref_close": None}])
    r = FD.full_bars(fd).iloc[0]
    assert (r.o, r.h, r.l) == (100, 103, 98)
