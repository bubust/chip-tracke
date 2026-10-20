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
    out = asyncio.run(tt.build_list(p, live_fn=live))
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
