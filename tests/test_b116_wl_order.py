"""B116 觀察清單的順序存在伺服器（用戶 11/17：手機版的順序跟電腦版不一樣）
python -m pytest tests/test_b116_wl_order.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


def test_order_roundtrip(monkeypatch):
    store = {}
    monkeypatch.setattr(server, "settings_get", lambda k: store.get(k))
    monkeypatch.setattr(server, "settings_set", lambda k, v: store.__setitem__(k, v))
    c = TestClient(server.app)
    assert c.get("/api/watchlist/order").json() == {"order": []}
    r = c.post("/api/watchlist/order", json={"order": ["3481", "2449", "<b>", "3481", "4583"]})
    assert r.json() == {"ok": True, "n": 3}                                     # 壞代號、重複的拿掉
    assert c.get("/api/watchlist/order").json() == {"order": ["3481", "2449", "4583"]}
    assert c.post("/api/watchlist/order", json={"order": "x"}).status_code == 400
