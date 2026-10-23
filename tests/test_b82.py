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


def test_opt_research_endpoint_reads_json_and_tolerates_missing(tmp_path, monkeypatch):
    import json
    import server
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    server._OPT_RES.update(mtime=None, data={})
    assert server.api_opt_research() == {}
    d = tmp_path / "research" / "b82"
    d.mkdir(parents=True)
    (d / "opt_research.json").write_text(json.dumps({"meta": {"n_tests": 81}, "strategies": {"S10": {"chip": {"passed": False}}}}), encoding="utf-8")
    out = server.api_opt_research()
    assert out["meta"]["n_tests"] == 81 and out["strategies"]["S10"]["chip"]["passed"] is False


def test_frontend_only_uses_passed_research():
    """網站只認 passed:true（_optPassed 過濾、建議行只從 _optPassed 來）"""
    s = _html()
    m = re.search(r"function _optPassed\(strategy\) \{(.*?)\n\}", s, re.S)
    assert m and "x[f].passed" in m.group(1)
    v = re.search(r"function _renderStratVerdict\(s\) \{(.*?)\n\}", s, re.S).group(1)
    assert "_optPassed(s)" in v and "opt" not in v.replace("_optPassed", "").replace("_optRes", "")


# ── PLAN-B82 §4：研究通過的條件上網站（opt_flags）──
def test_opt_passed_rules_only_passed_chip_rev():
    import opt_flags as OF
    R = {"strategies": {
        "S2": {"chip": {"passed": True, "combo": ["C3", "C4"], "desc": "外資連買＋投信連買"}, "rev": {"passed": False, "combo": ["M1"]}},
        "S_FBD": {"chip": {"passed": True, "combo": ["C2", "C3"], "desc": "x"}, "entry": {"passed": True, "variant": "E2"}},
        "S1": {"chip": {"passed": False, "combo": ["C1"]}}}}
    r = OF.passed_rules(R)
    assert set(r) == {"S2", "S_FBD"} and r["S2"] == [{"fam": "chip", "combo": ["C3", "C4"], "desc": "外資連買＋投信連買"}]
    assert all(x["fam"] in ("chip", "rev") for v in r.values() for x in v)      # 進場時機不在這裡處理


def test_opt_chip_flags_pure_streaks_and_margin_lag():
    import opt_flags as OF
    cal = ["20261013", "20261014", "20261015", "20261016", "20261019", "20261020", "20261021", "20261022"]
    inst = {d: {"A": (1000, 500, 0), "B": (1000, -1, 0)} for d in cal}
    inst["20261021"]["A"] = (-5, 500, 0)                  # A 外資前一天賣超 → 沒有連買 3 天
    del inst["20261020"]["B"]                             # B 兩天前沒資料 → 不算
    margin = {d: {"A": 100.0} for d in cal}
    margin["20261022"]["A"] = 10.0                        # 當天融資大減，但 18:00 看不到（用前一天）
    f = OF.chip_flags_pure(cal, inst, margin, {"A": 5.0, "B": 5.0}, ["A", "B"])
    assert "C1" in f["A"] and "C2" in f["A"] and "C3" not in f["A"] and "C4" in f["A"] and "C7" not in f["A"]
    assert "C1" in f["B"] and "C3" not in f["B"] and "C2" not in f["B"]
    assert "C6" in f["A"]                                 # 1.5 張 ≥ 5 張 × 10%


def test_opt_rev_flags_pure_waits_until_published():
    import opt_flags as OF
    rev = {f"2025{m:02d}": {"A": (100.0 + m, 5.0, 3.0)} for m in range(1, 13)}
    rev["202512"] = {"A": (50.0, 5.0, 3.0)}               # 12 月營收偏低（2/19 時看到的最新月份，不是新高）
    rev["202601"] = {"A": (200.0, 25.0, 25.0)}            # 1 月營收創新高，2/20 才算知道
    assert "M4" not in OF.rev_flags_pure("20260219", rev, ["A"])["A"]
    got = OF.rev_flags_pure("20260220", rev, ["A"])["A"]
    assert {"M1", "M2", "M3", "M4", "M5"} <= got


def test_opt_annotate_marks_rows_and_leaves_others(monkeypatch):
    import opt_flags as OF
    monkeypatch.setattr(OF, "research", lambda: {"strategies": {"S2": {"chip": {"passed": True, "combo": ["C3", "C4"], "desc": "d"}}}})
    monkeypatch.setattr(OF, "load_chip", lambda day, sids: (["20261020", "20261021", "20261022"],
                                                           {d: {"A": (1, 1, 0), "B": (1, -1, 0)} for d in ("20261020", "20261021", "20261022")}, {}, {}))
    res = {"S2": [{"stock_id": "A", "last_date": "20261022"}, {"stock_id": "B", "last_date": "20261022"}], "S1": [{"stock_id": "A"}]}
    out = OF.annotate(res)
    assert out["meets"] == 1 and res["S2"][0]["o"]["meets"] == {"chip": True} and res["S2"][1]["o"]["meets"] == {"chip": False}
    assert "o" not in res["S1"][0]


def test_revenue_month_gets_rev_column(tmp_path, monkeypatch):
    import sqlite3
    import course_live
    db = tmp_path / "c.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE revenue_month (ym TEXT, stock_id TEXT, yoy REAL, cum_yoy REAL, PRIMARY KEY (ym, stock_id))")
    c.execute("INSERT INTO revenue_month VALUES ('202609','2330',10,12)")
    c.commit(); c.close()

    def conn():
        x = sqlite3.connect(str(db)); x.row_factory = sqlite3.Row
        return x
    monkeypatch.setattr(course_live, "_conn", conn)
    c = conn(); course_live._init(c); c.commit()
    cols = {r[1] for r in c.execute("PRAGMA table_info(revenue_month)")}
    assert "rev" in cols and c.execute("SELECT yoy FROM revenue_month").fetchone()[0] == 10
    c.close()


def test_frontend_star_rules_include_b82():
    s = _html()
    m = re.search(r"function _starRules\(strategy\) \{(.*?)\n\}", s, re.S)
    assert m and "_optPassed(strategy)" in m.group(1) and "r.o.meets" in m.group(1)
    assert "_starCell(row, _rules)" in s and "同條件隨機挑也有" in s
