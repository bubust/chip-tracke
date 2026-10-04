"""觀察清單：Supabase 為唯一來源，刪掉的不會被本地資料推回去。python -m pytest tests/test_watchlist_sync.py -q"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient


def test_deleted_stock_not_resurrected(tmp_path, monkeypatch):
    import server
    import supabase_store as sb
    cloud = {"2330": {"stock_id": "2330", "name": "台積電", "added_at": "2026-10-01", "note": ""}}
    monkeypatch.setattr(sb, "_enabled", lambda: True)
    monkeypatch.setattr(sb, "wl_list", lambda: list(cloud.values()))
    monkeypatch.setattr(sb, "wl_add", lambda sid, name="", added_at="", note="", memo="": cloud.setdefault(sid, {"stock_id": sid, "name": name, "added_at": added_at, "note": note}) is not None)
    monkeypatch.setattr(sb, "wl_delete", lambda sid: cloud.pop(sid, None) is not None or True)
    monkeypatch.setattr(sb, "cd_delete_stock", lambda sid: True)
    # 本地（這台機器）還留著一支已經在別台刪掉的 1519
    c = server.get_conn()
    c.execute("DELETE FROM watchlist")
    c.execute("INSERT INTO watchlist (stock_id, name, added_at, note) VALUES ('1519','華城','2026-09-01','')")
    c.commit(); c.close()
    client = TestClient(server.app)
    r = client.get("/api/watchlist/summary").json()
    ids = [x["stock_id"] for x in (r["items"] if isinstance(r, dict) else r)]
    assert ids == ["2330"] and "1519" not in cloud          # 不再推回雲端，本地也被清掉
    client.post("/api/watchlist", json={"stock_id": "2408", "name": "南亞科"})
    client.delete("/api/watchlist/2330")
    r = client.get("/api/watchlist/summary").json()
    ids = [x["stock_id"] for x in (r["items"] if isinstance(r, dict) else r)]
    assert ids == ["2408"]
