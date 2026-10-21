"""PLAN-B77 全系統總檢查：記憶體（權證串流、產業增量、拿掉 scipy）、重工作排隊、續跑／補跑、快取、健康頁
python -m pytest tests/test_b77.py -q"""
import asyncio
import json
import math
import os
import random
import sqlite3
import sys
import threading
import time
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── A1 權證合約：ijson 逐筆讀 ＝ json 整包讀 ─────────────────────────────────────

ROWS = [{"權證代號": f"0{i:05d}", "權證簡稱": f"台積電元大{i}購01", "權證類型": "認購" if i % 2 else "認售",
         "類別": "一般型", "標的證券/指數": "台積電", "最新履約價格(元)/履約指數": "1000.0000",
         "最新標的履約配發數量(每仟單位權證)": "10.00", "最後交易日": "1151229", "履約截止日": "1151231",
         "履約開始日": "1141001", "發行單位數量(仟單位)": "5000", "結算方式(詳附註編號說明)": "5", "備註": "測試\r\n第二行"}
        for i in range(50)]


def test_iter_rows_array_and_fields_format(tmp_path):
    from warrant import ingester
    p1 = tmp_path / "a.json"
    p1.write_text(json.dumps(ROWS, ensure_ascii=False), encoding="utf-8")
    assert list(ingester.iter_rows(p1)) == json.loads(p1.read_text(encoding="utf-8"))
    fields = list(ROWS[0].keys())
    p2 = tmp_path / "b.json"
    p2.write_text(json.dumps({"stat": "OK", "fields": fields, "data": [[r[k] for k in fields] for r in ROWS]},
                             ensure_ascii=False), encoding="utf-8")
    assert list(ingester.iter_rows(p2)) == ROWS               # 第二趟有 seek(0)（審查 Gemini 第 3 輪 F1）
    p3 = tmp_path / "c.json"
    p3.write_text(json.dumps({"fields": [], "data": []}), encoding="utf-8")
    assert list(ingester.iter_rows(p3)) == []


class _FakeResp:
    def __init__(self, body: bytes, status=200):
        self.body, self.status_code = body, status
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_falls_back_and_cleans_tmp(tmp_path, monkeypatch):
    from warrant import ingester
    monkeypatch.setattr(ingester, "TMP_DIR", tmp_path / "tmp")
    body = json.dumps(ROWS, ensure_ascii=False).encode("utf-8")
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _FakeResp(b"[]") if url == "u1" else _FakeResp(body)      # 第 1 個網址沒資料 → 換第 2 個
    monkeypatch.setattr(ingester.requests, "get", fake_get)
    p = ingester.download_rows_file(["u1", "u2"], "T")
    assert calls == ["u1", "u2"] and p and p.exists()
    assert len(list((tmp_path / "tmp").iterdir())) == 1                # 失敗那份已刪
    rows = ingester._fetch_rows(["u2"], "T", limit=3)
    assert len(rows) == 3 and rows[0]["權證代號"] == "000000"


def test_download_size_cap(tmp_path, monkeypatch):
    from warrant import ingester
    monkeypatch.setattr(ingester, "TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(ingester, "MAX_DOWNLOAD", 100)
    monkeypatch.setattr(ingester.requests, "get", lambda url, **kw: _FakeResp(json.dumps(ROWS).encode()))
    assert ingester.download_rows_file(["u"], "T") is None              # 超過上限中止
    assert list((tmp_path / "tmp").iterdir()) == []                    # 暫存檔刪掉


def test_ingest_contracts_streaming_writes_rows(tmp_path, monkeypatch):
    from warrant import ingester, db as wdb
    monkeypatch.setattr(wdb, "DB_PATH", tmp_path / "w.db")
    wdb.init_db()
    monkeypatch.setattr(ingester, "TMP_DIR", tmp_path / "tmp")
    body = json.dumps(ROWS, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(ingester.requests, "get", lambda url, **kw: _FakeResp(body))
    monkeypatch.setattr(ingester, "load_sinopac_basic", lambda: {ROWS[0]["權證代號"]: {"underlying_code": "2330", "issuer": "元大"}})
    from warrant import router as wr                   # 正式流程被 router 包一層（排隊＋紀錄）；這裡測裡面那層
    n = wr._orig_ingest()
    assert n == 100                                     # 50 筆 × 證交所、櫃買兩份（同一份假資料）
    with wdb.db() as c:
        assert c.execute("SELECT COUNT(*) FROM warrants").fetchone()[0] == 50
        assert c.execute("SELECT underlying_code FROM warrants WHERE code='000000'").fetchone()[0] == "2330"
    assert list((tmp_path / "tmp").iterdir()) == []    # 用完刪掉
    assert ingester._sinopac_warrant_map == {}          # 永豐對照表用完放掉


# ── A3 拿掉 scipy：erf／Brent ＝ scipy ─────────────────────────────────────────

def test_norm_and_iv_match_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    scipy_opt = pytest.importorskip("scipy.optimize")
    from warrant import calculator as C
    for x in [i / 50 for i in range(-400, 401)]:                        # −8～8（尾端）
        assert abs(C.norm.cdf(x) - scipy_stats.norm.cdf(x)) < 1e-15
        assert abs(C.norm.pdf(x) - scipy_stats.norm.pdf(x)) < 1e-15
    rnd = random.Random(7)
    n = 0
    for _ in range(4000):
        S = rnd.uniform(5, 1000); K = S * rnd.uniform(0.5, 1.6); T = rnd.choice([1 / 365, 3 / 365, 0.02, 0.1, 0.5, 1, 2])
        sig = rnd.uniform(0.02, 3); kind = rnd.choice(["CALL", "PUT"]); N = rnd.choice([0.001, 0.01, 0.1, 1])
        mp = (C.bs_price(S, K, T, 0.015, 0, sig, kind, N) or 0) * rnd.uniform(0.9, 1.1)
        mine = C.implied_vol(mp, S, K, N, T, 0.015, 0, kind)
        intrinsic = max(0, (S - K) if kind == "CALL" else (K - S)) * N
        ref = None
        if mp > intrinsic:
            f = lambda s: (C.bs_price(S, K, T, 0.015, 0, s, kind, N) or 0) - mp
            if f(0.001) * f(20.0) <= 0:
                try:
                    ref = scipy_opt.brentq(f, 0.001, 20.0, xtol=1e-8, maxiter=300)
                except Exception:
                    ref = None
        assert (mine is None) == (ref is None)
        if mine is not None:
            n += 1
            assert abs(mine - ref) < 1e-12
    assert n > 3000


def test_brentq_errors_like_scipy():
    from warrant import calculator as C
    with pytest.raises(ValueError):
        C.brentq(lambda x: x * x + 1, -1, 1)
    opt = pytest.importorskip("scipy.optimize")
    f = lambda x: math.exp(x) - 3.0 - x * x
    with pytest.raises(RuntimeError):                    # 圈數不夠：跟 scipy 一樣丟 RuntimeError
        opt.brentq(f, 0, 3, maxiter=2)
    with pytest.raises(RuntimeError):
        C.brentq(f, 0, 3, maxiter=2)
    assert abs(C.brentq(lambda x: x ** 3 - 2, 0, 2) - 2 ** (1 / 3)) < 1e-11


def test_server_does_not_import_scipy():
    import subprocess
    code = "import sys, os; sys.path.insert(0, os.getcwd()); os.environ.pop('FINMIND_TOKEN', None); import server; print('scipy' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "False", out.stderr[-500:]


# ── A2 產業同步增量 ＝ 全量（最後幾天） ─────────────────────────────────────────

def _mk_cache(path, days, sids):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE price_daily (date TEXT, stock_id TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, name TEXT, PRIMARY KEY (date, stock_id))")
    rnd = random.Random(3)
    for d in days:
        for s in sids:
            px = rnd.uniform(10, 100)
            c.execute("INSERT INTO price_daily VALUES (?,?,?,?,?,?,?,?)", (d, s, px, px * 1.01, px * 0.99, px, rnd.randint(1, 900), ""))
    c.commit()
    c.close()


def test_sector_incremental_equals_full(tmp_path, monkeypatch):
    import chip_tracker_v2
    from sector import db as sdb, prices
    from datetime import date as _d, timedelta as _td
    days = []
    d = _d.today() - _td(days=120)
    while d <= _d.today():
        if d.weekday() < 5:
            days.append(d.strftime("%Y%m%d"))
        d += _td(days=1)
    sids = [f"{1000 + i}" for i in range(30)]
    out = {}
    for mode in ("full", "inc"):
        cache = tmp_path / f"cache_{mode}.db"
        _mk_cache(cache, days, sids)                    # 兩份一模一樣的價格快取
        monkeypatch.setattr(chip_tracker_v2, "DB_PATH", cache)
        monkeypatch.setattr(sdb, "SECTOR_DB_PATH", tmp_path / f"s_{mode}.db")
        sdb.init_db()
        with sdb.db() as c:
            c.executemany("INSERT OR REPLACE INTO stock_sector_map (stock_id, sector_id) VALUES (?, 'S1')", [(s,) for s in sids])
        r1 = prices.sync_from_price_cache(days=200, full=True)
        assert r1["mode"] == "full" and r1["days"] == len(days)
        c = sqlite3.connect(cache)                      # 最後 3 天價格改了（例如收盤後補正）
        c.execute("UPDATE price_daily SET close = close + 1 WHERE date >= ?", (days[-3],))
        c.commit()
        c.close()
        r2 = prices.sync_from_price_cache(days=200, full=(mode == "full"))
        if mode == "inc":
            assert r2["mode"] == "incremental" and r2["days"] < 20
        with sdb.db() as c:
            out[mode] = [tuple(r) for r in c.execute("SELECT * FROM sector_stock_daily ORDER BY date, stock_id").fetchall()]
    assert out["full"] == out["inc"] and len(out["full"]) == len(days) * len(sids)


# ── A4 重工作排隊 ───────────────────────────────────────────────────────────────

def test_heavy_reentrant_logged_and_blocks_others(tmp_path, monkeypatch):
    import jobs
    monkeypatch.setattr(jobs, "LOG_FILE", tmp_path / "job_log.jsonl")
    order = []
    with jobs.heavy("outer"):
        with jobs.heavy("inner"):                       # 同一條執行緒重入（全系統更新裡的庫藏股）
            order.append("inner")
        t = threading.Thread(target=lambda: jobs.run_heavy("other", lambda: order.append("other")))
        t.start()
        time.sleep(0.3)
        assert order == ["inner"]                       # 另一條執行緒要等
    t.join(5)
    assert order == ["inner", "other"]
    recs = jobs.recent(10)
    kinds = [(r["kind"], r.get("name")) for r in recs]
    assert ("start", "outer") in kinds and ("end", "outer") in kinds and ("end", "other") in kinds
    assert ("start", "inner") not in kinds              # 重入不另外記
    assert jobs.recently_ok("other") and not jobs.recently_ok("nope")


def test_heavy_refuses_event_loop_and_times_out(tmp_path, monkeypatch):
    import jobs
    monkeypatch.setattr(jobs, "LOG_FILE", tmp_path / "job_log.jsonl")

    async def on_loop():
        with jobs.heavy("x"):
            pass
    with pytest.raises(RuntimeError):
        asyncio.run(on_loop())                          # 審查 Gemini F2
    hold = threading.Event()
    release = threading.Event()

    def holder():
        with jobs.heavy("holder"):
            hold.set()
            release.wait(5)
    t = threading.Thread(target=holder)
    t.start()
    hold.wait(5)
    with pytest.raises(jobs.QueueTimeout):
        with jobs.heavy("late", wait_limit=0.2):
            pass
    release.set()
    t.join(5)
    assert any(r.get("kind") == "skip" and r.get("name") == "late" for r in jobs.recent(20))


def test_on_boot_finds_interrupted_job_and_cleans_tmp(tmp_path, monkeypatch):
    import jobs
    monkeypatch.setattr(jobs, "LOG_FILE", tmp_path / "job_log.jsonl")
    monkeypatch.setattr(jobs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path / "tmp")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "TWSE_1.json").write_text("[]")
    lines = [{"t": "2026-10-21 19:59:00", "kind": "start", "name": "refresh_all"},
             {"t": "2026-10-21 20:00:00", "kind": "start", "name": "warrant_ingest"}]
    (tmp_path / "job_log.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    rec = jobs.on_boot()
    assert rec["interrupted"] == ["refresh_all", "warrant_ingest"]
    assert list((tmp_path / "tmp").iterdir()) == []
    assert jobs.boots(5)[-1]["interrupted"] == ["refresh_all", "warrant_ingest"]
    assert jobs.on_boot()["interrupted"] == []          # 下一次開機：上一筆是 boot，不重複算


# ── B1 全系統更新續跑 ───────────────────────────────────────────────────────────

def _fake_steps(calls, fail=None):
    def mk(k):
        def f():
            calls.append(k)
            if k == fail:
                raise RuntimeError("boom")
        return f
    import server
    return lambda: [(k, mk(k)) for k in server._refresh_all_status["steps"]]


def test_refresh_resume_skips_done_and_crash_twice(tmp_path, monkeypatch):
    import server, jobs
    monkeypatch.setattr(server, "_REFRESH_STATUS_FILE", tmp_path / "st.json")
    monkeypatch.setattr(jobs, "LOG_FILE", tmp_path / "job_log.jsonl")
    keys = list(server._refresh_all_status["steps"])
    # 上次：前 6 步完成、權證跑到一半重開（第 2 次了）
    st = json.loads(json.dumps(server._refresh_all_status))
    st.update(running=True, started_at=datetime.now().isoformat(), crash={"warrant": 1})
    for i, k in enumerate(keys):
        st["steps"][k]["status"] = "done" if i < 6 else ("running" if k == "warrant" else "pending")
    (tmp_path / "st.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    server._load_refresh_status()
    s = server._refresh_all_status
    assert s["interrupted"] and s["crash"]["warrant"] == 2 and s["steps"]["warrant"]["status"] == "interrupted"
    assert json.loads((tmp_path / "st.json").read_text(encoding="utf-8"))["crash"]["warrant"] == 2    # 存回去
    assert server._refresh_recent_interrupted()
    calls = []
    monkeypatch.setattr(server, "_refresh_steps", _fake_steps(calls))
    server._do_system_refresh(resume=True)
    assert calls == keys[7:]                                         # 完成的不重跑、權證略過
    assert s["steps"]["warrant"]["status"] == "skipped" and "記憶體" in s["steps"]["warrant"]["reason"]
    assert all(s["steps"][k]["status"] == "done" for k in keys[7:])
    assert s["running"] is False and s["crash"] == {}


def test_refresh_full_run_resets_and_marks_errors(tmp_path, monkeypatch):
    import server, jobs
    monkeypatch.setattr(server, "_REFRESH_STATUS_FILE", tmp_path / "st.json")
    monkeypatch.setattr(jobs, "LOG_FILE", tmp_path / "job_log.jsonl")
    calls = []
    monkeypatch.setattr(server, "_refresh_steps", _fake_steps(calls, fail="tdcc"))
    server._do_system_refresh(resume=False)
    s = server._refresh_all_status
    assert calls == list(s["steps"])
    assert s["steps"]["tdcc"]["status"] == "error" and s["steps"]["cb"]["status"] == "done"
    assert all("sec" in v for v in s["steps"].values())
    assert jobs.recently_ok("treasury")                              # 18:40 排程看到剛做過就跳過
    assert not server._refresh_recent_interrupted()


# ── B2 18:00 掃描補跑時間表 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("now,fin,att,need,day", [
    ("2026-10-21 20:05", "2026-10-20T23:50:29", 0, True, "2026-10-21"),    # 今天（週三）晚上沒跑
    ("2026-10-21 20:05", "2026-10-21T18:12:00", 0, False, "2026-10-21"),   # 已經跑完
    ("2026-10-21 20:05", None, 0, True, "2026-10-21"),
    ("2026-10-21 20:05", "2026-10-20T23:50:29", 2, False, "2026-10-21"),   # 補過 2 次不再補
    ("2026-10-22 01:30", "2026-10-21T15:00:00", 0, True, "2026-10-21"),    # 半夜：補前一個平日
    ("2026-10-26 02:00", "2026-10-23T18:30:00", 0, False, "2026-10-23"),   # 週一凌晨：週五已跑
    ("2026-10-26 02:00", "2026-10-22T18:30:00", 0, True, "2026-10-23"),
    ("2026-10-21 10:00", None, 0, False, None),                            # 白天不補
    ("2026-10-24 19:00", None, 0, False, None),                            # 週六晚上不補
])
def test_need_scan_catchup(now, fin, att, need, day):
    import server
    assert server.need_scan_catchup(datetime.strptime(now, "%Y-%m-%d %H:%M"), fin, att) == (need, day)


# ── C1 指數快取單飛 ─────────────────────────────────────────────────────────────

def test_indices_single_flight(monkeypatch):
    import server
    n = {"calls": 0}

    async def fake():
        n["calls"] += 1
        await asyncio.sleep(0.2)
        return {"taiex": {"name": "加權指數", "price": 1.0, "change_pct": 0.1}}
    monkeypatch.setattr(server, "_indices_fetch", fake)
    monkeypatch.setattr(server, "_IDX", {"t": 0.0, "data": None})
    monkeypatch.setattr(server, "_IDX_LOCK", None)

    async def go():
        rs = await asyncio.gather(*[server._indices_get() for _ in range(5)])
        again = await server._indices_get()
        return rs, again
    rs, again = asyncio.run(go())
    assert n["calls"] == 1 and all(r["taiex"]["price"] == 1.0 for r in rs) and again["taiex"]["price"] == 1.0


def test_indices_failure_keeps_last(monkeypatch):
    import server
    async def bad():
        return {"taiex": {"name": "加權指數", "price": None, "change_pct": None}}
    monkeypatch.setattr(server, "_indices_fetch", bad)
    monkeypatch.setattr(server, "_IDX", {"t": 0.0, "data": {"taiex": {"name": "加權指數", "price": 9.0, "change_pct": 1}}})
    monkeypatch.setattr(server, "_IDX_LOCK", None)
    d = asyncio.run(server._indices_get(force=True))
    assert d["taiex"]["price"] == 9.0 and d.get("_stale") is True


@pytest.mark.parametrize("hm,wd,ttl", [((10, 0), 2, 8), ((14, 30), 2, 60), ((20, 0), 2, 8), ((3, 0), 3, 8), ((12, 0), 5, 60), ((3, 0), 0, 60)])
def test_idx_ttl(hm, wd, ttl):
    import server
    base = datetime(2026, 10, 19)            # 週一
    from datetime import timedelta
    now = (base + timedelta(days=wd)).replace(hour=hm[0], minute=hm[1])
    assert server._idx_ttl(now) == ttl


# ── C3／C4 過期先回舊資料 ───────────────────────────────────────────────────────

def test_swr_serves_stale_then_refreshes(tmp_path):
    from swr import SWR
    n = {"v": 0}

    def build():
        n["v"] += 1
        time.sleep(0.2)
        return {"v": n["v"]}
    s = SWR("t", ttl=0.05, builder=build, persist=tmp_path / "x.json")
    assert s.get() == {"v": 1}                     # 沒資料：當場算
    time.sleep(0.1)
    t = time.time()
    assert s.get() == {"v": 1} and time.time() - t < 0.05     # 過期：馬上回舊的
    time.sleep(0.4)
    assert s.data == {"v": 2}                      # 背景更新好了
    s2 = SWR("t", ttl=60, builder=build, persist=tmp_path / "x.json")
    assert s2.data == {"v": 2}                     # 重開機讀存檔
    # 單飛：同時很多執行緒過期 → 只算一次
    s3 = SWR("t3", ttl=0.0, builder=build)
    s3.set({"v": 0})
    before = n["v"]
    for _ in range(5):
        s3.refresh_async()
    time.sleep(0.5)
    assert n["v"] - before == 1


# ── D1 籌碼型策略錯誤看得到 ─────────────────────────────────────────────────────

def test_chip_course_records_errors(monkeypatch):
    import chip_course
    monkeypatch.setattr(chip_course, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(chip_course, "screen_trust5", lambda *a: (_ for _ in ()).throw(ValueError("壞掉")))
    chip_course.run_all({}, {}, do_refresh=False)
    assert "S_TRUST5" in chip_course.last_errors and "壞掉" in chip_course.last_errors["S_TRUST5"]


def test_bighold_skips_incomplete_week(tmp_path, monkeypatch):
    """審查 Gemini B-F1：中間某週集保資料不完整（合計 0）→ 以前 min() 碰到 None 丟 TypeError、S_BIGHOLD 整個 0 檔"""
    import chip_course
    import pandas as pd
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE tdcc_tier (date TEXT, sid TEXT, tier INT, shares REAL)")
    weeks = ["2026-09-25", "2026-10-02", "2026-10-09", "2026-10-16"]
    for i, d in enumerate(weeks):
        if d == "2026-10-02":
            c.execute("INSERT INTO tdcc_tier VALUES (?, '2330', 17, 0)", (d,))          # 這週壞掉
            continue
        big, retail = 600 + i * 10, 200 - i * 10
        for tier, sh in ((15, big), (1, retail), (17, 1000)):
            c.execute("INSERT INTO tdcc_tier VALUES (?, '2330', ?, ?)", (d, tier, sh))
    df = pd.DataFrame({"date": ["20261016"] * 10, "close": [100.0] * 10, "volume": [1.0] * 10, "high": [101.0] * 10, "low": [99.0] * 10})
    out = chip_course.screen_bighold(c, lambda sid: df, {"2330": "台積電"}, {"retail_lots": 50, "min_big_chg": 0.1, "min_price": 10})
    assert [r["stock_id"] for r in out] == ["2330"]


# ── D3 健康頁 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("now,exp", [("2026-10-21 20:00", "2026-10-21"), ("2026-10-21 17:00", "2026-10-20"),
                                     ("2026-10-24 12:00", "2026-10-23"), ("2026-10-26 08:00", "2026-10-23")])
def test_expected_day(now, exp):
    import health
    assert health.expected_day(datetime.strptime(now, "%Y-%m-%d %H:%M")).isoformat() == exp


def test_health_daily_rule():
    import health
    from datetime import date
    assert health._daily("k", "x", "20261021", date(2026, 10, 21), "")["ok"]
    w = health._daily("k", "x", "2026-10-20 18:40", date(2026, 10, 21), "")
    assert not w["ok"] and "休市" in w["note"]
    assert not health._daily("k", "x", None, date(2026, 10, 21), "")["ok"]


def test_endpoints_healthz_tdcc_regime_multi():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    assert c.get("/healthz").text == "ok"
    r = c.get("/api/tdcc/trends?ids=2330,abc$,0050").json()
    assert set(r["trends"]) == {"2330", "0050"}
    m = c.get("/regime/api/regime/series_multi?names=TAIEX,OTC&days=2").json()
    assert set(m) == {"TAIEX", "OTC"} and isinstance(m["TAIEX"], list)
    h = c.get("/api/system/health").json()
    assert "summary" in h and isinstance(h["items"], list) and h["items"]
