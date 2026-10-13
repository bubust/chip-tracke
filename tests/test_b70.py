"""B70：週 K、月線斜率、AI 兩段式新聞、連動跨產業候選、法人買賣超排行、S_MSLOPE（PLAN-B70.md §6）"""
import datetime
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deep_ai          # noqa: E402
import deep_patterns as dp  # noqa: E402
import market_rank as mr    # noqa: E402


def _daily(dates, base=10.0):
    n = len(dates)
    c = np.linspace(base, base * 1.1, n)
    return pd.DataFrame({"date": dates, "open": c * 0.99, "high": c * 1.01, "low": c * 0.98, "close": c, "volume": [1000] * n})


# ── 週 K ─────────────────────────────────────────────────────────────────────

def test_weekly_bars_holiday_week_and_partial():
    # 10/05～10/08（週四結束，週五放假＝4 天）、10/12～10/13 本週
    df = _daily(["20261005", "20261006", "20261007", "20261008", "20261012", "20261013"])
    ws = dp.weekly_bars(df, today=datetime.date(2026, 10, 13))
    assert [w["days"] for w in ws] == [4, 2]
    assert ws[0]["open"] == pytest.approx(df.open.iloc[0]) and ws[0]["close"] == pytest.approx(df.close.iloc[3])
    assert ws[0]["high"] == pytest.approx(df.high.iloc[:4].max()) and ws[0]["low"] == pytest.approx(df.low.iloc[:4].min())
    assert ws[0]["partial"] is False and ws[1]["partial"] is True
    # 週六看：本週已走完
    assert dp.weekly_bars(df, today=datetime.date(2026, 10, 17))[-1]["partial"] is False
    ch = dp.weekly_chain(df, 4, today=datetime.date(2026, 10, 13))
    assert len(ch) == 2 and ch[0]["chg"] is None and ch[1]["chg"] == round((df.close.iloc[-1] / df.close.iloc[3] - 1) * 100, 2)


def test_weekly_cross_year_and_empty():
    df = _daily(["20251229", "20251230", "20251231", "20260102", "20260105"])
    ws = dp.weekly_bars(df, today=datetime.date(2026, 2, 1))
    assert [w["days"] for w in ws] == [4, 1]                 # 2025-12-29 與 2026-01-02 同一個 ISO 週（2026-W01）
    assert dp.weekly_bars(pd.DataFrame(columns=["date", "open", "high", "low", "close"])) == []
    assert dp.weekly_chain(None) == []


def test_kbar_chain_five_and_new_listing():
    df = _daily([f"202610{d:02d}" for d in range(1, 11)])
    assert len(dp.kbar_chain(df, 5)) == 5
    short = _daily([f"202610{d:02d}" for d in range(1, 16)])      # 新上市 15 根
    assert dp.trend_info(short) is None and dp.month_slope(short.close) is None
    assert len(dp.weekly_chain(short)) >= 1


def test_kbar_w_stat_uses_constants():
    s = dp.kbar_w_stat("大紅K", 0.9)
    assert s["band"] == "hi" and s["x20"] > s["base_x20"] > 0
    assert dp.kbar_w_stat("不存在") is None


# ── 月線斜率 ─────────────────────────────────────────────────────────────────

def test_month_slope_matches_article_example():
    # 商周財富網權證小哥例子：昨天月線 308.5、今天 312.13 → 1.18%
    c = [308.5] * 20 + [308.5 + 20 * (312.13 - 308.5)]
    assert dp.month_slope(c) == 1.18
    assert dp.month_slope([10] * 20) is None
    assert dp.month_slope([10] * 21) == 0.0


def test_screen_mslope():
    import scanner_course as sc
    up = np.r_[np.full(40, 100.0), np.linspace(100, 135, 25)]
    d = pd.DataFrame({"date": [f"d{i}" for i in range(len(up))], "open": up, "high": up * 1.01, "low": up * 0.99,
                      "close": up, "volume": [5000] * len(up)})
    ma = pd.Series(up).rolling(20).mean()
    slope = (ma.iloc[-1] / ma.iloc[-2] - 1) * 100
    bias = (up[-1] / ma.iloc[-1] - 1) * 100
    res = sc.screen_mslope({"1234": d}, {"1234": "測試"}, {"near_pct": 20})
    assert slope > 1 and bias <= 20 and len(res) == 1 and res[0]["mslope"] == round(slope, 2)
    assert sc.screen_mslope({"1234": d}, {}, {"near_pct": 0.5}) == []          # 離月線太遠
    assert "S_MSLOPE" in __import__("scanner").PRICE_STRATEGY_FNS


# ── AI 兩段式新聞 ────────────────────────────────────────────────────────────

def _payload():
    return {"stock_id": "2330", "name": "台積電", "market": "twse", "technical": {"date": "20261013", "close": 100},
            "levels": {}, "verdict": {"ok": False, "reason": "x"}, "patterns": {}, "chip": {"error": "x"},
            "valuation": {}, "news": {"items": [{"date": "2026-10-12", "title": "系統新聞", "publisher": "鉅亨"}]}}


def test_news_digest_filters_old_and_caches(monkeypatch, tmp_path):
    from discuss import ai
    calls = []
    old = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
    new = datetime.date.today().isoformat()

    def fake_call(model, parts, search, key, timeout):
        calls.append(model)
        return {"text": '```json\n{"items": [{"date": "%s", "title": "新", "summary": "s", "source": "a"},'
                        '{"date": "%s", "title": "舊", "summary": "s", "source": "b"}]}\n```' % (new, old),
                "grounding": {"webSearchQueries": ["台積電 法說會"]}}
    monkeypatch.setattr(ai, "api_key", lambda: "k")
    monkeypatch.setattr(ai, "_call", fake_call)
    monkeypatch.setattr(deep_ai, "DB_PATH", tmp_path / "ai.db")
    out = deep_ai.news_digest(_payload())
    assert [x["title"] for x in out["items"]] == ["新"] and out["searched"]
    deep_ai.news_digest(_payload())
    assert len(calls) == 1                                  # 12 小時快取


def test_generate_survives_stage1_failure(monkeypatch, tmp_path):
    from discuss import ai
    seen = {}

    def fake_call(model, parts, search, key, timeout):
        txt = parts[0]["text"]
        if txt.startswith("請用 Google 搜尋"):
            raise RuntimeError("429 quota")
        seen["prompt"] = txt
        return {"text": "結論。\n## 一、K 線\n- 重點\n" + "內容" * 100, "grounding": {}}
    monkeypatch.setattr(ai, "api_key", lambda: "k")
    monkeypatch.setattr(ai, "_call", fake_call)
    monkeypatch.setattr(deep_ai, "DB_PATH", tmp_path / "ai.db")
    monkeypatch.setattr(deep_ai.time, "sleep", lambda s: None)
    out = deep_ai.generate(_payload(), [])
    assert out["news"] == {"items": [], "searched": False}
    assert "800～1,200 字" in seen["prompt"] and "這次沒有查到網路消息" in seen["prompt"] and "系統新聞" in seen["prompt"]
    assert "近 30 天沒有重大新聞" in seen["prompt"]


def test_save_latest_with_news(tmp_path):
    db = tmp_path / "ai.db"
    deep_ai.save("2330", "20261013", {"text": "t", "model": "m", "searched": True, "sources": [], "queries": [],
                                      "news": {"items": [{"date": "2026-10-12", "title": "x"}], "searched": True}}, db)
    assert deep_ai.latest("2330", db)["news"]["items"][0]["title"] == "x"


# ── 連動：跨產業候選 ─────────────────────────────────────────────────────────

def test_follow_candidates_include_cross_sector():
    import linkage
    rng = np.random.default_rng(1)
    base = rng.normal(0, 0.02, 80)
    R = pd.DataFrame({"6505": base, "6501": base * 0.9 + rng.normal(0, 0.005, 80),     # 同產業、高相關
                      "1434": base * 0.8 + rng.normal(0, 0.006, 80),                   # 跨產業、高相關
                      "9999": rng.normal(0, 0.02, 80)})                                # 不相關
    today = R.index[-1]
    R.loc[today] = [0.097, 0.01, 0.028, 0.0]
    pool = pd.Series({"6505": True, "6501": True, "1434": True, "9999": True})
    peers = [{"id": "1434", "corr": 0.723}, {"id": "9999", "corr": 0.1}, {"id": "6501", "corr": 0.9}]
    cand = linkage.follow_candidates("6505", ["6505", "6501"], R, pool, peers, today)
    ids = [c[0] for c in cand]
    assert ids[0] == "6501" and cand[0][2] is True                # 同產業優先
    assert "1434" in ids and dict((c[0], c[2]) for c in cand)["1434"] is False
    assert "9999" not in ids and ids.count("6501") == 1             # 低相關不要、不重複
    R.loc[today, "1434"] = 0.06                                     # 已經漲超過一半 → 不算候選
    assert "1434" not in [c[0] for c in linkage.follow_candidates("6505", ["6505"], R, pool, peers, today)]


# ── 法人買賣超排行 ───────────────────────────────────────────────────────────

def test_market_rank_streak_total_etf():
    dates = ["2026-10-13", "2026-10-12", "2026-10-08", "2026-10-07"]
    by = {
        "2330": {"2026-10-13": (100, 5, -1), "2026-10-12": (50, 5, 0), "2026-10-08": (-10, 5, 0), "2026-10-07": (10, 5, 0)},
        "0050": {"2026-10-13": (900, 0, 0)},
        "030001": {"2026-10-13": (9999, 0, 0)},           # 權證 → 不要
        "6488": {"2026-10-13": (-5, -3, 0), "2026-10-12": (-5, 0, 0)},
        "1101": {"2026-10-12": (100, 0, 0)},              # 最新一天沒資料 → 不要
    }
    rows = {r["stock_id"]: r for r in mr.build_rows(dates, by)}
    assert set(rows) == {"2330", "0050", "6488"}
    r = rows["2330"]
    assert r["total_lots"] == 104 and r["whale_flow_lots"] == 104
    assert r["foreign_streak"] == 2 and r["trust_streak"] == 4           # 外資 10/08 賣超斷掉；投信連 4 天
    assert rows["6488"]["foreign_streak"] == -2 and rows["6488"]["trust_streak"] == -1   # 投信 10/12 是 0 → 斷
    assert r["sum5_total"] == 104 + 55 - 5 + 15
    for x in rows.values():
        x["market"] = "twse"
        x["vol_ratio_pct"] = 1.0
    buy = mr.filter_sort(list(rows.values()), side="buy")
    assert [x["stock_id"] for x in buy] == ["2330"]                       # ETF 預設排除
    assert [x["stock_id"] for x in mr.filter_sort(list(rows.values()), side="buy", etf=True)] == ["0050", "2330"]
    assert [x["stock_id"] for x in mr.filter_sort(list(rows.values()), side="sell")] == ["6488"]
    assert mr.filter_sort(list(rows.values()), market="tpex") == []
    assert mr.build_rows([], {}) == []


def test_market_rank_prices(tmp_path):
    import sqlite3
    db = tmp_path / "cache.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE price_daily (stock_id TEXT, date TEXT, close REAL, volume REAL)")
    c.executemany("INSERT INTO price_daily VALUES (?,?,?,?)", [("2330", "20261013", 110, 2000), ("2330", "20261012", 100, 1500)])
    c.commit(); c.close()
    rows = [{"stock_id": "2330", "total_lots": 100}, {"stock_id": "9999", "total_lots": 5}]
    assert mr.attach_prices(rows, "2026-10-13", db) is True
    assert rows[0]["close"] == 110 and rows[0]["change_pct"] == 10.0 and rows[0]["vol_ratio_pct"] == 5.0
    assert rows[1]["close"] is None and rows[1]["vol_ratio_pct"] is None
    assert mr.attach_prices([{"stock_id": "2330", "total_lots": 1}], "2026-10-14", db) is False


def test_refresh_inst_only_inst(monkeypatch, tmp_path):
    import chip_course as cc
    from test_deep_data import _FakeClient, _patch_refresh
    fake = _FakeClient()
    _patch_refresh(monkeypatch, tmp_path, fake)
    out = cc.refresh_inst(2)
    assert out["fetched"] == 2
    assert not any("MI_MARGN" in u or "margin" in u for u in fake.calls)    # 不抓融資券、集保
    assert cc.inst_series("2449") == [("2026-10-06", -2700146.0, -335000.0, 105747.0)]
    fake2 = _FakeClient()
    _patch_refresh(monkeypatch, tmp_path, fake2)
    cc.refresh_inst(2)
    assert len([u for u in fake2.calls if "fund/T86" in u]) == 1            # 10-06 已抓過不再抓


# ── 觀察清單：_bb_live 快取 20 根後 BB 不變、月斜率 ─────────────────────────────

def test_bb_live_and_mslope_live(monkeypatch):
    import server
    import price_cache
    closes = [100 + i for i in range(30)]
    df = pd.DataFrame({"date": [f"202609{i + 1:02d}" for i in range(30)], "close": closes})
    monkeypatch.setattr(price_cache, "get_stock_ohlcv", lambda sid, days=45: df)
    server._BB_BASE.clear()
    bb = server._bb_live("1234", 131, "20261001")
    arr = closes[-19:] + [131]
    m = sum(arr) / 20
    sd = (sum((v - m) ** 2 for v in arr) / 20) ** 0.5
    assert bb == round((131 - m) / (2 * sd) * 10, 1)
    ms = server._mslope_live("1234", 131, "20261001")
    assert ms == dp.month_slope(closes[-20:] + [131])
    assert server._mslope_live("1234", None, "20261001") is None


def test_news_block_dedupes_system_news():
    d = {"news": {"items": [{"date": "2026-10-12", "title": "群創9月營收月增83.24%、年增197.34%", "publisher": "鉅亨"},
                            {"date": "2026-10-11", "title": "另一則系統新聞", "publisher": "工商"}]}}
    digest = {"items": [{"date": "2026-10-06", "title": "群創9月營收月增83.24%，年增197.34%", "summary": "s", "source": "x"}]}
    txt = deep_ai._news_block(d, digest)
    assert txt.count("83.24") == 1 and "另一則系統新聞" in txt


def test_deep_news_falls_back_without_when(monkeypatch):
    import asyncio
    import email.utils
    import server
    now = datetime.datetime.now(datetime.timezone.utc)
    recent = email.utils.format_datetime(now - datetime.timedelta(days=2))
    old = email.utils.format_datetime(now - datetime.timedelta(days=90))
    rss = ("<rss><channel>"
           f"<item><title>新消息</title><link>https://a</link><pubDate>{recent}</pubDate><source>鉅亨</source></item>"
           f"<item><title>舊消息</title><link>https://b</link><pubDate>{old}</pubDate><source>工商</source></item>"
           "</channel></rss>")
    calls = []

    class Resp:
        def __init__(self, text):
            self.text, self.is_success = text, True

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append(dict(params or {}))
            return Resp("<rss><channel></channel></rss>" if "when:30d" in (params or {}).get("q", "") else rss)
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(server._deep_news("3481", "群創"))
    assert [x["title"] for x in out["items"]] == ["新消息"]                 # 90 天前的被濾掉
    assert calls[0]["q"] == "群創 3481 when:30d" and calls[1]["q"] == "群創 3481"   # 第一次沒結果 → 不帶 when 再查
