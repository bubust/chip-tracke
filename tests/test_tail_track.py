"""🎯 尾盤追蹤：python -m pytest tests/test_tail_track.py -q"""
import asyncio, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tail_track as tt

MSG = """⏰ 假跌破：收盤前還成立　13:10（9 檔）
• 1809 中釉 47.6（+8.8%）站回 MA10 44.11，10/19 跌破　（早上已通知）
• 3231 緯創 188.0（+4.4%）站回 MA10 185.3，10/19 跌破　🆕
⚠ 盤中出現過、現在不成立：2354 鴻準、2357 華碩
現在買＝尾盤進場；13:10 的價格不是收盤價。"""


def test_parse_message():
    xs = tt.parse_message(MSG)
    assert [x["stock_id"] for x in xs] == ["1809", "3231"]
    assert xs[0] == {"stock_id": "1809", "name": "中釉", "price": 47.6, "ma10": 44.11, "broke_md": (10, 19)}


def test_evaluate_stop_and_returns():
    row = {"id": 1, "stock_id": "1809", "entry_date": "2026-10-20", "entry_price": 100.0, "zone": "watch", "zone_manual": 0}
    bars = [("2026-10-20", 99, 101, 98, 100.5), ("2026-10-21", 101, 110, 100, 108), ("2026-10-22", 105, 106, 91, 93)]
    r = tt.evaluate(row, bars, None, 8)
    assert r["hit"] == ("2026-10-22", 92.0) and r["days"] == 2 and r["ret_pct"] == -7.0
    assert r["max_up_pct"] == 10.0 and r["max_down_pct"] == -9.0
    # 跳空開在停損線下 → 用開盤價
    r2 = tt.evaluate(row, bars[:2] + [("2026-10-22", 90, 91, 88, 89)], None, 8)
    assert r2["hit"] == ("2026-10-22", 90)
    # 盤中即時價（今天還沒進 price_daily）
    r3 = tt.evaluate(row, bars[:2], {"date": "2026-10-23", "open": 100, "high": 101, "low": 95, "close": 96}, 8)
    assert r3["hit"] is None and r3["price"] == 96 and r3["days"] == 2


def test_db_flow(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setattr(tt, "DB_PATH", p)
    tt.init_db(p)
    c = sqlite3.connect(p)
    assert c.execute("SELECT COUNT(*) FROM tail_track").fetchone()[0] == 9         # 10/20 清單補進來
    tt.init_db(p)
    assert c.execute("SELECT COUNT(*) FROM tail_track").fetchone()[0] == 9         # 只補一次
    n = tt.add_from_fbd("20261021", [{"stock_id": "2330", "name": "台積電", "price": 1000, "ma10": 990, "broke_date": "20261020"},
                                     {"stock_id": "2330", "name": "台積電", "price": 1000}])
    assert n == 1
    monkeypatch.setattr(tt, "_bars", lambda sids, since: {"2330": [("2026-10-21", 1000, 1000, 990, 995), ("2026-10-22", 990, 995, 900, 905)]})
    monkeypatch.setattr(tt, "_ma10", lambda *a: None)

    async def live(sids):
        return {}
    out = asyncio.run(tt.build_list(p, live_fn=live, bf=False))
    row = next(r for r in out["rows"] if r["stock_id"] == "2330")
    assert row["zone"] == "stop" and row["stop_date"] == "2026-10-22" and row["stop_price"] == 920.0 and row["stop_ret_pct"] == -8.0
    assert c.execute("SELECT zone FROM tail_track WHERE stock_id='2330'").fetchone()[0] == "stop"   # 有存回去
    c.close()


def test_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    p = tmp_path / "a.db"
    monkeypatch.setattr(tt, "DB_PATH", p)
    tt.init_db(p, seed=False)
    app = FastAPI(); app.include_router(tt.router)
    cl = TestClient(app)
    assert cl.post("/api/tail", json={"stock_id": "2330", "entry_price": 1000, "entry_date": "2026-10-20", "name": "台積電"}).json()["ok"]
    assert cl.post("/api/tail", json={"stock_id": "2330", "entry_price": 1000, "entry_date": "2026-10-20", "name": "台積電"}).status_code == 400
    r = cl.post("/api/tail/import", json={"text": MSG, "date": "2026-10-20"}).json()
    assert r == {"ok": True, "found": 2, "added": 2}
    c = sqlite3.connect(p)
    tid = c.execute("SELECT id FROM tail_track WHERE stock_id='1809'").fetchone()[0]
    assert cl.put(f"/api/tail/{tid}", json={"zone": "stop"}).json()["ok"]
    assert c.execute("SELECT zone, zone_manual FROM tail_track WHERE id=?", (tid,)).fetchone() == ("stop", 1)
    assert cl.put("/api/tail/settings/stop", json={"stop_pct": 10}).json()["stop_pct"] == 10
    assert cl.delete(f"/api/tail/{tid}").json()["ok"]
    assert c.execute("SELECT COUNT(*) FROM tail_track").fetchone()[0] == 2
    c.close()


# ── B91：日線結構、13:15 大盤、補算 ─────────────────────────────────────────────
def test_migration_adds_columns_to_old_table(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE tail_track (id INTEGER PRIMARY KEY AUTOINCREMENT, stock_id TEXT NOT NULL, name TEXT, entry_date TEXT NOT NULL, "
              "entry_price REAL NOT NULL, ma10 REAL, broke_date TEXT, source TEXT, note TEXT, zone TEXT DEFAULT 'watch', "
              "zone_manual INTEGER DEFAULT 0, stop_date TEXT, stop_price REAL, created_at TEXT, UNIQUE (stock_id, entry_date))")
    c.execute("INSERT INTO tail_track (stock_id, entry_date, entry_price) VALUES ('2330', '2026-10-20', 1000)")
    c.commit(); c.close()
    tt.init_db(p, seed=False)
    tt.init_db(p, seed=False)                                                     # 第二次不會重複 ALTER
    c = sqlite3.connect(p)
    cols = {r[1] for r in c.execute("PRAGMA table_info(tail_track)")}
    assert {"struct_ok", "struct", "struct_eod", "struct_eod_info"} <= cols
    assert c.execute("SELECT struct_ok FROM tail_track").fetchone() == (None,)    # 舊資料＝NULL（之後補算）
    assert c.execute("SELECT name FROM sqlite_master WHERE name='tail_mkt'").fetchone()
    c.close()


def test_add_from_fbd_with_struct_and_mkt(tmp_path):
    p = tmp_path / "s.db"
    tt.init_db(p, seed=False)
    items = [{"stock_id": "2330", "name": "台積電", "price": 1000, "struct_ok": True, "struct": {"ok": True, "reason": ""}},
             {"stock_id": "2317", "name": "鴻海", "price": 200, "struct_ok": False, "struct": {"ok": False, "reason": "低點跌破前低"}}]
    mkt = {"snap": {"x": 1}, "feats": {"x": 43000.0, "chg": 0.01, "M4": "多頭"}, "verdict": {"label": "good"}, "checked_at": "13:15"}
    assert tt.add_from_fbd("20261103", items, db_path=p, mkt=mkt) == 2
    c = sqlite3.connect(p)
    assert dict(c.execute("SELECT stock_id, struct_ok FROM tail_track").fetchall()) == {"2330": 1, "2317": 0}
    assert c.execute("SELECT source FROM tail_track LIMIT 1").fetchone()[0] == "13:15 假跌破"
    assert c.execute("SELECT src, verdict, checked_at FROM tail_mkt WHERE date='2026-11-03'").fetchone() == ("live", "good", "13:15")
    # 補算不會蓋掉 13:15 當下存的
    assert not tt.save_mkt("2026-11-03", {"feats": {"x": 1}, "verdict": {"label": "bad"}}, "補算", db_path=p)
    # 沒有特徵（大盤抓不到）＝不存
    assert not tt.save_mkt("2026-11-04", {"snap": None, "feats": None}, "live", db_path=p)
    c.close()


def test_backfill_struct_eod_and_market(tmp_path, monkeypatch):
    from datetime import datetime
    p = tmp_path / "b.db"
    tt.init_db(p, seed=False)
    tt.add("2330", 100, "2026-10-30", "台積電", db_path=p)                       # 舊資料：結構、大盤都沒有
    tt.add("2317", 50, "2026-11-03", "鴻海", db_path=p, struct={"ok": True, "reason": ""})   # 今天 13:15 加的
    # 鋸齒上漲（高點、低點都墊高）的日 K；2026-11-03 還沒進 price_daily
    import numpy as np
    n = 80
    c_ = np.linspace(50, 100, n) + 2 * np.sin(np.arange(n) * 2 * np.pi / 14)
    days = [f"2026-{(7 + i // 28):02d}-{(i % 28) + 1:02d}" for i in range(n - 1)] + ["2026-10-30"]
    monkeypatch.setattr(tt, "_hl_until", lambda sid, d, n=260: (days, list(c_ * 1.01), list(c_ * 0.99)) if sid == "2330"
                        else (days, list(c_ * 1.01), list(c_ * 0.99)))
    calls = []

    def mkt_fn(d):
        calls.append(d)
        if d == "2026-10-30":
            return {"snap": {"x": 1}, "feats": {"x": 45000.0, "chg": -0.02, "M4": "空頭"}, "verdict": {"label": "neutral"}, "checked_at": "13:15"}
        return None
    # 13:20：今天的收盤後結構、今天的大盤補算都還不做
    r = tt.backfill(p, now=datetime(2026, 11, 3, 13, 20, tzinfo=tt.TW), mkt_fn=mkt_fn, pause=0)
    assert r == {"struct": 1, "eod": 1, "mkt": 1, "mkt_fail": 0} and calls == ["2026-10-30"]
    c = sqlite3.connect(p)
    assert c.execute("SELECT struct_ok, struct_eod FROM tail_track WHERE stock_id='2330'").fetchone() == (1, 1)
    assert c.execute("SELECT struct_ok, struct_eod FROM tail_track WHERE stock_id='2317'").fetchone() == (1, None)
    # 15:00：今天的大盤補算失敗 → 記次數；5 次以後不再試
    for k in range(6):
        tt.backfill(p, now=datetime(2026, 11, 3, 15, 0, tzinfo=tt.TW), mkt_fn=mkt_fn, pause=0)
    assert c.execute("SELECT fails FROM tail_mkt WHERE date='2026-11-03'").fetchone()[0] == tt.MKT_MAX_FAILS
    assert calls.count("2026-11-03") == tt.MKT_MAX_FAILS
    # 補算丟例外也不當掉
    def boom(d):
        raise TimeoutError("twse")
    c.execute("DELETE FROM tail_mkt WHERE date='2026-11-03'"); c.commit()
    r = tt.backfill(p, now=datetime(2026, 11, 3, 15, 0, tzinfo=tt.TW), mkt_fn=boom, pause=0)
    assert r["mkt_fail"] == 1
    c.close()


def test_build_list_has_mkt_struct_and_research(tmp_path, monkeypatch):
    p = tmp_path / "l.db"
    tt.init_db(p, seed=False)
    tt.add("2330", 100, "2026-10-30", "台積電", db_path=p, struct={"ok": False, "reason": "高沒有過前高"})
    tt.save_mkt("2026-10-30", {"feats": {"x": 45000.0, "chg": -0.02, "M2": "開低走低", "M4": "空頭", "M5": "都跌破"},
                               "verdict": {"label": "neutral"}}, "補算", db_path=p)
    monkeypatch.setattr(tt, "_bars", lambda sids, since: {})
    monkeypatch.setattr(tt, "_ma10", lambda *a: None)
    import tail_market as TM
    rule = {"family": "M4", "family_name": "大盤日線結構", "bucket": "空頭", "side": "bad", "pass": True, "oos": {"n": 99, "win": .2, "mean": -.02}}
    monkeypatch.setattr(TM, "load_research", lambda path=None: {"rules": [rule], "generated": "x", "families": {}})

    async def live(sids):
        return {}
    out = asyncio.run(tt.build_list(p, live_fn=live, bf=False))
    r = out["rows"][0]
    assert r["struct_ok"] == 0 and r["struct"]["reason"] == "高沒有過前高"
    assert r["mkt"]["label"] == "bad" and r["mkt"]["text"] == "⚠ 不適合" and "日線空頭" in r["mkt"]["desc"]   # 用現在的研究重算
    assert out["research"]["rules"] == [rule]
