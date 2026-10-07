"""深度分析資料來源（PLAN-DEEP2 §4）：python -m pytest tests/test_deep_data.py -q
fixtures/ 是 2026-10-06 真實回應的節錄"""
import json, os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chip_course as cc
import deep_data as dd
from cb.parser import parse_twse_margin_both, parse_tpex_margin_both

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fx(name):
    return json.load(open(os.path.join(FX, name), encoding="utf-8"))


# ── 解析 ─────────────────────────────────────────────────────────────────────

def test_parse_t86_inst():
    m = cc.parse_t86_inst(fx("t86_20261006.json"))
    assert m["2449"] == (-2700146.0, -335000.0, 105747.0)       # 京元：外資、投信、自營商
    assert m["4583"] == (250.0, 0.0, -208.0)
    assert "9999" not in m                                       # 壞列丟掉
    assert cc.parse_t86_inst({"fields": ["證券代號"], "data": [["1"]]}) == {}
    assert cc.parse_t86_inst({"stat": "很抱歉，沒有符合條件的資料!", "total": 0}) == {}   # 假日


def test_parse_tpex_insti_daily():
    d, m = cc.parse_tpex_insti_daily(fx("tpex_insti_20261006.json"))
    assert d == "2026-10-06"
    assert m["3105"] == (-2443493.0, -23400.0, -126320.0)        # 穩懋
    assert m["6488"] == (-518347.0, 106000.0, 103667.0)
    assert "8888" not in m                                        # 合計對不上 → 丟掉
    j = fx("tpex_insti_20261006.json")
    j["tables"][0]["fields"][13] = "改名了"
    assert cc.parse_tpex_insti_daily(j) == (None, {})             # 欄位變了 → 不解析
    assert cc.parse_tpex_insti_daily({"tables": [{"date": "115/10/04", "fields": [], "data": []}]}) == (None, {})


def test_parse_margin_both():
    m = parse_twse_margin_both(fx("mi_margn_20261006.json"))
    assert m["2449"] == (26935.0, 243.0) and m["4583"] == (2714.0, 1.0)
    j = fx("mi_margn_20261006.json")
    for t in j["tables"]:
        if t.get("groups"):
            t["groups"][1]["span"] = 5                            # 欄位組變了 → 不解析
    assert parse_twse_margin_both(j) == {}
    assert parse_tpex_margin_both(fx("tpex_margin_20261006.json"))["6488"] == (17671.0, 670.0)


# ── refresh 端對端（假的 HTTP）────────────────────────────────────────────────

class _Resp:
    def __init__(self, j):
        self._j = j

    def json(self):
        return self._j


class _FakeClient:
    """只有 2026-10-06 有資料，10-05 當假日（官方回空）"""
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        p = params or {}
        if "fund/T86" in url:
            return _Resp(fx("t86_20261006.json") if p.get("date") == "20261006" else {"stat": "很抱歉", "total": 0})
        if "insti/dailyTrade" in url:
            if p.get("date") == "2026/10/06":
                return _Resp(fx("tpex_insti_20261006.json"))
            return _Resp({"tables": [{"date": "115/10/05", "fields": [], "data": []}]})
        if "MI_MARGN" in url:
            return _Resp(fx("mi_margn_20261006.json") if p.get("date") == "20261006" else {"stat": "x"})
        if "tpex_3insti_daily_trading" in url:
            return _Resp([])
        raise RuntimeError("unexpected " + url)

    def post(self, url, data=None, **kw):
        self.calls.append(url)
        if "margin/balance" in url and (data or {}).get("date") == "2026/10/06":
            return _Resp(fx("tpex_margin_20261006.json"))
        return _Resp({"tables": []})


def _patch_refresh(monkeypatch, tmp_path, fake):
    import cb.fetcher as cf
    import httpx
    monkeypatch.setattr(cc, "DB_PATH", tmp_path / "course.db")
    monkeypatch.setattr(cc, "_weekdays_back", lambda n: [date(2026, 10, 6), date(2026, 10, 5)])
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    monkeypatch.setattr(cf, "client", lambda: fake)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no tdcc in test")))


def test_refresh_writes_inst_and_margin(monkeypatch, tmp_path):
    fake = _FakeClient()
    _patch_refresh(monkeypatch, tmp_path, fake)
    cc.refresh()
    ser = cc.inst_series("2449")
    assert ser == [("2026-10-06", -2700146.0, -335000.0, 105747.0)]
    assert cc.inst_series("6488") == [("2026-10-06", -518347.0, 106000.0, 103667.0)]
    assert cc.margin_series("2449") == [("2026-10-06", 26935.0, 243.0)]
    assert cc.margin_series("6488") == [("2026-10-06", 17671.0, 670.0)]
    c = cc.get_conn()
    assert c.execute("SELECT net FROM inst_trust WHERE sid='6488' AND date='2026-10-06'").fetchone()[0] == 106000.0
    assert c.execute("SELECT bal FROM short_bal WHERE sid='2449' AND date='2026-10-06'").fetchone()[0] == 243.0
    logged = set(c.execute("SELECT kind, date, market FROM fetch_log"))
    c.close()
    assert ("inst", "2026-10-06", "twse") in logged and ("inst", "2026-10-06", "tpex") in logged
    assert not any(d == "2026-10-05" for _, d, _ in logged)         # 假日不記，下次再試

    # 第二次：10-06 已抓過不再抓、10-05（假日）會再試
    fake2 = _FakeClient()
    _patch_refresh(monkeypatch, tmp_path, fake2)
    cc.refresh()
    t86 = [u for u in fake2.calls if "fund/T86" in u]
    assert len(t86) == 1


# ── 官方整包表 ───────────────────────────────────────────────────────────────

def test_build_index_requires_field():
    import pytest
    with pytest.raises(ValueError):
        dd.build_index([{"Code": "1"}], "Code", "PEratio")
    with pytest.raises(ValueError):
        dd.build_index([], "Code", "PEratio")
    assert dd.build_index([{"Code": "2330 ", "PEratio": "20"}], "Code", "PEratio") == {"2330": {"Code": "2330 ", "PEratio": "20"}}


def test_table_keeps_last_good_copy_on_failure(monkeypatch):
    calls = {"n": 0}

    def fake(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"Code": "2330", "PEratio": "20.5"}]
        raise RuntimeError("down")
    monkeypatch.setattr(dd, "_get_json", fake)
    monkeypatch.setattr(dd, "_cache", {})
    assert dd.table("pe_twse")["2330"]["PEratio"] == "20.5"
    dd._cache["pe_twse"]["t"] -= 10 * 3600                         # 過期 → 重抓失敗
    assert dd.table("pe_twse")["2330"]["PEratio"] == "20.5"         # 沿用舊的
    n = calls["n"]
    assert dd.table("pe_twse")["2330"]["PEratio"] == "20.5" and calls["n"] == n   # 負快取，不馬上重抓


def _inject(monkeypatch, tables):
    monkeypatch.setattr(dd, "_cache", {k: {"t": 9e18, "idx": v} for k, v in tables.items()})


def test_revenue_income_valuation(monkeypatch):
    _inject(monkeypatch, {
        "pe_twse": {"4583": {"Date": "1151006", "Code": "4583", "PEratio": "30.88", "DividendYield": "2.40", "PBratio": "3.36"}},
        "pe_tpex": {},
        "rev_twse": {"4583": {"資料年月": "11508", "營業收入-當月營收": "261171", "營業收入-上月比較增減(%)": "-16.24",
                              "營業收入-去年同月增減(%)": "23.632", "累計營業收入-當月累計營收": "2333762",
                              "累計營業收入-前期比較增減(%)": "15.97", "備註": "-"}},
        "rev_tpex": {},
        "inc_twse": {"4583": {"年度": "115", "季別": "2", "營業收入": "2000000", "營業毛利（毛損）淨額": "922665.00",
                              "營業利益（損失）": "606107.00", "淨利（淨損）歸屬於母公司業主": "546086.00", "基本每股盈餘（元）": "6.81"}},
        "inc_tpex": {},
        "co_twse": {"4583": {"公司簡稱": "台灣精銳", "實收資本額": "802000000", "已發行普通股數或TDR原股發行股數": "80200000"}},
        "co_tpex": {},
    })
    monkeypatch.setattr(dd, "peer_ids", lambda sid: ("電機機械", []))
    r = dd.revenue("4583")
    assert r["ym"] == "2026-08" and r["yoy"] == 23.6 and r["ytd_yoy"] == 16.0 and r["mom"] == -16.2 and r["note"] is None
    i = dd.income("4583")
    assert i["eps"] == 6.81 and i["year"] == 2026 and i["season"] == 2 and i["gross_margin"] == 46.1
    v = dd.valuation("4583", 416.0)
    assert v["per"] == 30.88 and v["pbr"] == 3.36 and v["dividend_yield"] == 2.4 and v["date"] == "2026-10-06"
    assert v["shares"] == 0.802 and v["market_cap"] == round(416 * 80200000 / 1e8, 1) and v["capital"] == 8.02
    assert dd.revenue("0050") is None and dd.valuation("0050", 100) == {"etf": True}
    assert dd.income("9999") is None                                # 查不到（金融業等）


def test_peer_median_needs_five(monkeypatch):
    _inject(monkeypatch, {"pe_twse": {str(i): {"Code": str(i), "PEratio": str(10 + i), "Date": "1151006"} for i in range(1, 7)},
                          "pe_tpex": {}})
    assert dd.peer_pe_median(["1", "2", "3", "4"]) == (None, 4)
    med, n = dd.peer_pe_median(["1", "2", "3", "4", "5", "6", "x"])
    assert n == 6 and med == 13.5


# ── 籌碼 ─────────────────────────────────────────────────────────────────────

def test_streak():
    assert dd._streak([1, -1, 2, 3, 4]) == 3
    assert dd._streak([1, 2, -1, -2]) == -2
    assert dd._streak([1, 2, 0]) == 0
    assert dd._streak([]) == 0


def test_finmind_inst_names():
    rows = [{"date": "2026-10-06", "name": "Foreign_Investor", "buy": 1000, "sell": 400},
            {"date": "2026-10-06", "name": "Foreign_Dealer_Self", "buy": 999, "sell": 0},   # 不算（跟 T86 一致）
            {"date": "2026-10-06", "name": "Investment_Trust", "buy": 0, "sell": 24000},
            {"date": "2026-10-06", "name": "Dealer_self", "buy": 100, "sell": 0},
            {"date": "2026-10-06", "name": "Dealer_Hedging", "buy": 50, "sell": 0}]
    assert dd.finmind_inst(rows) == [("2026-10-06", 600.0, -24000.0, 150.0)]


def test_chip_local_then_finmind(monkeypatch):
    local = [(f"2026-09-{d:02d}", 1000.0 * d, -2000.0, 0.0) for d in range(10, 30)]
    monkeypatch.setattr(cc, "inst_series", lambda sid, n=20: local)
    monkeypatch.setattr(cc, "margin_series", lambda sid, n=6: [("2026-09-24", 100.0, 5.0), ("2026-09-29", 130.0, 2.0)])
    monkeypatch.setattr(dd, "_finmind", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不該打 FinMind")))
    c = dd.chip("2449")
    assert c["source"].startswith("證交所") and c["days"] == 20 and len(c["daily"]) == 10
    assert c["trust"]["streak"] == -20 and c["trust"]["d5"] == -10 and c["foreign"]["d1"] == 29
    assert c["margin"]["margin_chg"] == 30.0 and c["margin"]["short_chg"] == -3.0

    monkeypatch.setattr(cc, "inst_series", lambda sid, n=20: local[:2])
    monkeypatch.setattr(dd, "_finmind", lambda *a, **k: [{"date": f"2026-09-{d:02d}", "name": "Foreign_Investor",
                                                            "buy": 2000, "sell": 0} for d in range(10, 20)])
    c = dd.chip("6488")
    assert c["source"] == "FinMind" and c["days"] == 10

    monkeypatch.setattr(cc, "inst_series", lambda sid, n=20: [])
    monkeypatch.setattr(dd, "_finmind", lambda *a, **k: None)                 # 402 額度用完
    assert "error" in dd.chip("6488")
