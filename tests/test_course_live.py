"""PLAN-COURSE 正式站：漲停打開盤中偵測（只推一次）、出貨日／漲停候選／當沖名單計算、二次處置候選、API。
python -m pytest tests/test_course_live.py -q（暫存 DB、假報價、假推播，不連網）"""
import os
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import course2 as C  # noqa: E402
import course_live as L  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "c.db"

    def conn():
        c = sqlite3.connect(str(path))
        c.row_factory = sqlite3.Row
        return c
    c = conn()
    c.execute("CREATE TABLE push_log (id INTEGER PRIMARY KEY, stock_id TEXT, signal_emoji TEXT, signal_title TEXT, pushed_at TEXT, ok INT)")
    c.execute("CREATE TABLE watchlist (stock_id TEXT, name TEXT, cost REAL)")
    c.commit(); c.close()
    sent = []

    def fake_send(key, text):
        sent.append((key, text))
        x = conn()
        x.execute("INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES ('COURSE','📋',?,?,1)", (key, datetime.now().isoformat()))
        x.commit(); x.close()
        return True
    monkeypatch.setattr(L, "_conn", conn)
    monkeypatch.setattr(L, "_send", fake_send)
    L._LIVE.update(day=None, opened={}, checked=None, cands=0)
    return conn, sent


def _cand(sid="1234", close=100.0, vol=50.0, yoy=35.0):
    return {"stock_id": sid, "name": "測試", "streak": 2, "close": close, "limit_next": C.limit_up_price(close), "vol": vol,
            "revenue": {"ym": "202609", "yoy": yoy, "cum_yoy": 10.0}}


def test_limit_tick_pushes_once(db):
    conn, sent = db
    L.save("limit", "20261008", {"date": "20261008", "candidates": [_cand(), _cand("5678")], "opened_close": []})
    now = datetime(2026, 10, 9, 10, 15)
    q = {"1234": {"date": "20261009", "open": 110.0, "high": 110.0, "low": 104.0, "close": 106.0, "volume": 400.0},   # 打開、量 8 倍
         "5678": {"date": "20261009", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "volume": 400.0}}   # 還鎖著
    new = L.limit_tick(now, quotes_fn=lambda sids, day: q)
    assert [x["stock_id"] for x in new] == ["1234"] and len(sent) == 1 and "漲停打開" in sent[0][1]
    assert L.limit_tick(now, quotes_fn=lambda sids, day: q) == [] and len(sent) == 1        # 同一天不再推
    L._LIVE.update(day=None, opened={})                                                     # 程式重啟也不重推（push_log）
    L.limit_tick(now, quotes_fn=lambda sids, day: q)
    assert len(sent) == 1
    assert L.limit_tick(datetime(2026, 10, 9, 14, 0), quotes_fn=lambda s, d: q) == []      # 收盤後不檢查
    assert L.live_status()["opened"][0]["stock_id"] == "1234"


def test_limit_tick_needs_volume(db):
    conn, sent = db
    L.save("limit", "20261008", {"date": "20261008", "candidates": [_cand(vol=500.0)], "opened_close": []})
    q = {"1234": {"date": "20261009", "open": 110.0, "high": 110.0, "low": 104.0, "close": 106.0, "volume": 400.0}}
    assert L.limit_tick(datetime(2026, 10, 9, 10, 15), quotes_fn=lambda s, d: q) == []      # 量 < 昨量 × 3


def _panel(n=200, seed=3):
    rng = np.random.default_rng(seed)
    S = 3
    c = 50 * np.exp(np.cumsum(rng.normal(0.002, 0.02, (n, S)), axis=0))
    o = c * (1 + rng.normal(0, 0.005, (n, S)))
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    v = np.full((n, S), 1000.0)
    # 第 0 檔：最後 3 天連續跳空漲停
    for i in (n - 3, n - 2, n - 1):
        lim = C.limit_up_price(float(c[i - 1, 0]))
        o[i, 0] = h[i, 0] = l[i, 0] = c[i, 0] = lim
        v[i, 0] = 80
    # 第 1 檔：高檔下跌出量
    c[:-1, 1] = np.r_[np.full(n - 61, 40.0), np.linspace(40, 80, 60)]       # 最近 60 天漲 1 倍（高檔）
    o[:-1, 1] = c[:-1, 1] * 0.995
    h[:-1, 1], l[:-1, 1] = c[:-1, 1] * 1.01, c[:-1, 1] * 0.99
    c[-1, 1] = c[-2, 1] * 0.96; o[-1, 1] = c[-2, 1]; h[-1, 1] = o[-1, 1] * 1.005; l[-1, 1] = c[-1, 1] * 0.995
    v[-1, 1] = 3000
    dates = [f"2026{(i // 28) % 12 + 1:02d}{i % 28 + 1:02d}" for i in range(n)]
    return {"dates": sorted(dates), "ids": ["1111", "2222", "3333"], "names": {"1111": "漲停", "2222": "出貨", "3333": "普通"},
            "o": o.astype(np.float32), "h": h.astype(np.float32), "l": l.astype(np.float32), "c": c.astype(np.float32), "v": v.astype(np.float32)}


def test_calc_limit_and_dist(db):
    P = _panel()
    lim = L.calc_limit(P)
    assert [x["stock_id"] for x in lim["candidates"]] == ["1111"] and lim["candidates"][0]["streak"] == 3
    d = L.calc_dist(P)
    hit = [x for x in d["items"] if x["stock_id"] == "2222" and x["date"] == P["dates"][-1]]
    assert hit and hit[0]["type_name"] == "下跌出量"


def test_calc_daytrade_filters(db):
    P = _panel()
    out = L.calc_daytrade(P, futs={"1111", "2222", "3333"}, taiex={"20261001": 100.0, "20261002": 101, "20261003": 102, "20261006": 103, "20261007": 110})
    assert out["market"]["side"] == "多"
    assert all(x["stock_id"] != "1111" for x in out["long"])       # 一字漲停、量縮：量不到 1.5 倍
    assert all(x["stock_id"] != "2222" for x in out["long"])


def test_push_nightly_market_once(db):
    conn, sent = db
    day = "20261008"
    L.save("market", day, {"date": day, "dist_day": True, "taiex": 20000, "d_point": 20100, "overheat": [{"date": day, "ratio": 0.55}]})
    L.push_nightly(day)
    L.push_nightly(day)
    assert sum(1 for k, _ in sent if k.startswith("market:")) == 1


def test_second_disposal_candidates(monkeypatch):
    import disposal
    monkeypatch.setattr(disposal, "_closes", lambda sid, upto, n=6: [10, 11, 12, 13, 14, 15] if sid == "1111" else [10, 11, 10, 12, 13, 14])
    disp = [{"stock_id": "1111", "name": "甲", "start": "20261001", "end": "20261005", "times": "第一次處置"},
            {"stock_id": "2222", "name": "乙", "start": "20261001", "end": "20261005", "times": "第一次處置"},
            {"stock_id": "3333", "name": "丙", "start": "20261001", "end": "20261005", "times": "第二次處置"}]
    tdays = ["20261001", "20261002", "20261005", "20261006", "20261007", "20261008"]
    out = disposal.second_candidates(disp, tdays)
    assert [x["stock_id"] for x in out] == ["1111"] and out[0]["status"] == "出關第 3 天"


def test_course_api_smoke():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    r = c.get("/api/course/today")
    assert r.status_code == 200 and "live" in r.json()
    assert c.get("/api/course/dist").status_code == 200
    assert c.get("/api/course/dist/abc").status_code == 400
    j = c.get("/api/course/research").json()
    assert "strategies" in j and "S_LIMIT_OPEN" in j["strategies"]
