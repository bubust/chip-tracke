"""持有模式：成本價 API＋持股盯盤推播（PLAN-POSITIONS.md）：python -m pytest tests/test_positions.py -q
用本機 DB 的一筆測試股 TST1（跑完刪掉），_levels_for／Telegram 都換成假的，不連網、不發訊息。"""
import os, sys
from datetime import datetime, timezone, timedelta
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient

SID = "TST1"
TODAY = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")


@pytest.fixture
def env(monkeypatch):
    import server
    state = {"price": 85.0, "high": 86.0, "date": TODAY, "prev_stop": 90.0, "prev_target": 120.0, "sent": [], "tg_ok": True}

    def fake_levels(sid, fresh=False):
        return {"stock_id": sid, "name": "測試股", "price": state["price"], "high": state["high"], "date": state["date"],
                "stop": {"price": state["price"] - 6, "basis": "support", "label": "支撐 − 0.5×ATR"},
                "support": {"price": state["price"] - 3, "kind": "swing", "label": "波段低點", "date": TODAY},
                "struct_support": None, "target": 130.0, "rr": 1.0, "downside_pct": -7.0,
                "prev": {"date": "x", "stop": state["prev_stop"], "target": state["prev_target"]}}

    async def fake_send(text):
        state["sent"].append(text)
        return state["tg_ok"]

    monkeypatch.setattr(server, "_levels_for", fake_levels)
    monkeypatch.setattr(server, "tg_send", fake_send)
    monkeypatch.setattr(server, "tg_creds", lambda: ("token", "chat"))
    c = server.get_conn()
    c.execute("DELETE FROM watchlist WHERE stock_id=?", (SID,))
    c.execute("DELETE FROM push_log WHERE stock_id=?", (SID,))
    c.execute("INSERT INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)", (SID, "測試股", "2026-10-01", ""))
    c.commit(); c.close()
    yield server, state
    c = server.get_conn()
    c.execute("DELETE FROM watchlist WHERE stock_id=?", (SID,))
    c.execute("DELETE FROM push_log WHERE stock_id=?", (SID,))
    c.commit(); c.close()


def test_cost_endpoint_set_validate_clear(env):
    server, state = env
    state["price"] = 100.0
    client = TestClient(server.app)
    r = client.post(f"/api/watchlist/{SID}/cost", json={"cost": 105.5}).json()
    assert r["ok"] and r["cost"] == 105.5 and r["cost_at"]
    assert client.post(f"/api/watchlist/{SID}/cost", json={"cost": 1055}).status_code == 400      # 打錯小數點
    assert client.post(f"/api/watchlist/{SID}/cost", json={"cost": "abc"}).status_code == 400
    assert client.post("/api/watchlist/NOPE9/cost", json={"cost": 10}).status_code == 404
    lv = client.get(f"/api/levels/{SID}").json()
    assert lv["entry"]["kind"] == "cost" and lv["entry"]["price"] == 105.5
    assert client.post(f"/api/watchlist/{SID}/cost", json={"cost": None}).json()["cost"] is None
    server_added = server._added_prices
    try:
        server._added_prices = lambda rows: {r["stock_id"]: (95.0, "20261001") for r in rows}
        e = client.get(f"/api/levels/{SID}").json()["entry"]
        assert e["kind"] == "added" and e["price"] == 95.0 and e["floor"] == 85.5      # 觀察模式：加入價 −10%
    finally:
        server._added_prices = server_added


def _set_cost(server, cost):
    c = server.get_conn(); c.execute("UPDATE watchlist SET cost=? WHERE stock_id=?", (cost, SID)); c.commit(); c.close()


def test_positions_warn_once_close_confirm_and_clear(env):
    server, state = env
    _set_cost(server, 100.0)                                   # 底線 90；昨天停損 90；現價 85 → 跌破
    items = server.check_positions("intraday")
    assert [i["type"] for i in items] == ["stop_warn"] and items[0]["key"] == f"pos:stop_warn:{TODAY}"
    assert "⚠️" in state["sent"][0] and "盤中跌破停損" in state["sent"][0] and "TST1" in state["sent"][0]
    assert server.check_positions("intraday") == []            # 同一天不重發
    items = server.check_positions("close")
    assert [i["type"] for i in items] == ["stop_close"] and "🛑" in state["sent"][-1]
    assert server.check_positions("close") == []


def test_positions_close_recovers_sends_clear(env):
    server, state = env
    _set_cost(server, 100.0)
    server.check_positions("intraday")                          # 盤中 85 跌破
    state["price"], state["high"] = 92.0, 93.0                  # 收盤站回 90 之上
    items = server.check_positions("close")
    assert [i["type"] for i in items] == ["stop_clear"] and "預警解除" in state["sent"][-1]


def test_positions_target_once_across_phases_and_dry_run(env):
    server, state = env
    _set_cost(server, 100.0)
    state["price"], state["high"], state["prev_target"] = 119.0, 121.0, 120.0
    dry = server.check_positions("intraday", dry=True)
    assert [i["type"] for i in dry] == ["target"] and state["sent"] == []        # 試算不發
    assert [i["type"] for i in server.check_positions("intraday")] == ["target"]
    assert server.check_positions("close") == []                                 # 盤中發過、收盤不重發


def test_positions_failed_send_retries_and_skips_non_trading_day(env):
    server, state = env
    _set_cost(server, 100.0)
    state["tg_ok"] = False
    assert server.check_positions("intraday")[0]["sent"] is False
    state["tg_ok"] = True
    assert server.check_positions("intraday")[0]["sent"] is True                 # 失敗的下次重試
    state["date"] = "20200101"                                                   # 最新 K 棒不是今天（假日）
    c = server.get_conn(); c.execute("DELETE FROM push_log WHERE stock_id=?", (SID,)); c.commit(); c.close()
    assert server.check_positions("close") == []


def test_positions_ignores_stocks_without_cost(env):
    server, state = env
    assert server.check_positions("close") == []


def test_positions_status_records_last_run(env):
    server, state = env
    import json
    old = server.settings_get("positions_last")
    try:
        _set_cost(server, 100.0)
        server.check_positions("intraday", dry=True)                     # 試算不記錄
        before = server.settings_get("positions_last")
        server.check_positions("intraday")
        last = json.loads(server.settings_get("positions_last"))
        assert last["phase"] == "intraday" and last["held"] >= 1 and last["notified"] == 1 and before == old
        st = TestClient(server.app).get("/api/positions/status").json()
        assert st["last"]["phase"] == "intraday" and "running" in st and "next" in st
    finally:
        server.settings_set("positions_last", old or "null")
