"""PLAN-B82：掃描結果帶資料日期／伺服器時間、18:00 掃完補抓三大法人、前端新鮮度與版面（靜態檢查）"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scan_data_date_picks_latest_valid():
    import server
    res = {"S1": [{"last_date": "20261021"}, {"last_date": "20261022"}], "S2": [{"last_date": "bad"}, {}, None],
           "S5": [{"last_date": 20261020}]}
    assert server._scan_data_date(res) == "20261022"
    assert server._scan_data_date({}) is None
    assert server._scan_data_date(None) is None


def test_tw_now_iso_is_naive_taiwan_time():
    import server
    s = server._tw_now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s)


def test_screen_endpoints_have_data_date_and_server_now(monkeypatch):
    import server
    import yahoo_price
    st = {"running": False, "finished_at": "2026-10-23T18:03:29", "yahoo_ok": 1946}
    monkeypatch.setattr(yahoo_price, "get_scan_status", lambda: dict(st))
    monkeypatch.setattr(yahoo_price, "get_scan_results", lambda: {"S1": [{"stock_id": "1101", "last_date": "20261022"}]})
    out = server.api_screen_status()
    assert out["data_date"] == "20261022" and out["finished_at"] == st["finished_at"] and out["server_now"]
    import json
    body = json.loads(server.api_screen_results().body)
    assert body["data_date"] == "20261022" and body["server_now"] and body["finished_at"] == st["finished_at"]
    # 掃描中：結果是半套的 → 不給資料日期
    st["running"] = True
    assert server.api_screen_status()["data_date"] is None


def test_scan_step1_refreshes_inst_after_scan(monkeypatch):
    """18:00 掃描跑完再補一次最近 3 天三大法人（全市場排行一定是當天的）"""
    import sys, types
    import server
    import yahoo_price
    calls = []
    monkeypatch.setattr(yahoo_price, "get_scan_status", lambda: {"running": False})

    async def fake_scan(**kw):
        calls.append("scan")
    monkeypatch.setattr(yahoo_price, "run_market_scan", fake_scan)
    monkeypatch.setattr(server, "_load_strategy_params", lambda: {})
    import price_cache

    async def fake_update(**kw):
        calls.append("price")
    monkeypatch.setattr(price_cache, "update_price_cache", fake_update)
    monkeypatch.setattr(price_cache, "init_price_db", lambda: None)
    import chip_course
    monkeypatch.setattr(chip_course, "refresh_inst", lambda n=3: calls.append(("inst", n)) or {"fetched": 1, "messages": []})
    for mod, fn in (("best_routes", ("push_best_signals", "push_best_exits")), ("link_routes", ("refresh_all",)),
                    ("crash_routes", ("push_crash",)), ("course_live", ("nightly",))):
        fake = types.ModuleType(mod)
        for f in fn:
            setattr(fake, f, lambda *a, **k: [])
        monkeypatch.setitem(sys.modules, mod, fake)
    server._scan_step1()
    assert calls[:2] == ["price", "scan"] and ("inst", 3) in calls


def test_scan_step1_inst_failure_does_not_break(monkeypatch):
    import sys, types
    import server
    import yahoo_price
    monkeypatch.setattr(yahoo_price, "get_scan_status", lambda: {"running": False})

    async def fake_scan(**kw):
        return None
    monkeypatch.setattr(yahoo_price, "run_market_scan", fake_scan)
    monkeypatch.setattr(server, "_load_strategy_params", lambda: {})
    import price_cache

    async def fake_update(**kw):
        return None
    monkeypatch.setattr(price_cache, "update_price_cache", fake_update)
    monkeypatch.setattr(price_cache, "init_price_db", lambda: None)
    import chip_course

    def boom(n=3):
        raise RuntimeError("TWSE down")
    monkeypatch.setattr(chip_course, "refresh_inst", boom)
    pushed = []
    for mod, fn in (("best_routes", ("push_best_signals", "push_best_exits")), ("link_routes", ("refresh_all",)),
                    ("crash_routes", ("push_crash",)), ("course_live", ("nightly",))):
        fake = types.ModuleType(mod)
        for f in fn:
            setattr(fake, f, lambda *a, _f=f, **k: pushed.append(_f) or [])
        monkeypatch.setitem(sys.modules, mod, fake)
    server._scan_step1()
    assert "push_best_signals" in pushed and "nightly" in pushed     # 法人補抓失敗，後面的推播照跑


def _html():
    return (ROOT / "dashboard.html").read_text(encoding="utf-8")


def test_dashboard_layout_tiles_and_no_old_cards():
    s = _html()
    for k in ("crash", "course", "f825", "opt"):
        assert f'class="scr-tile" data-k="{k}"' in s
    for old in ('id="crash-card"', 'id="course-card"', 'id="fixed825-card"', 'id="quality-card"'):
        assert old not in s
    assert 'id="screen-info-panel"' in s and 'aria-controls="screen-info-panel"' in s
    assert 'id="strat-verdict"' in s


def test_dashboard_freshness_wiring():
    """舊 v1／狀態列文字不再當真；一定跟伺服器比；切回頁面會檢查"""
    s = _html()
    assert "chip_tracker_screen_v2" in s
    assert "localStorage.setItem('chip_scan_badge'" not in s          # 狀態列不再存只有時間的文字
    assert "_savedScreenTotal === 0" not in s                         # 舊邏輯：本機有就不看伺服器
    assert "_screenSyncFromServer(true)" in s
    assert re.search(r"addEventListener\('visibilitychange'[^\n]*_screenFreshCheck\(\)", s)
    assert "cache: 'no-store'" in s
    assert "server_now" in s and "_twParts" in s


def test_market_meta_says_daily_update():
    s = _html()
    assert "每天 18:00 自動更新（證交所約 16:00 公布）" in s
    assert "_mktFreshCheck" in s
