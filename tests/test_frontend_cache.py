"""前端檔不能被瀏覽器快取成舊版：python -m pytest tests/test_frontend_cache.py -q"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient


def test_frontend_files_revalidate():
    import server
    client = TestClient(server.app)
    for path in ("/", "/cb/static/cb.js", "/notes/static/notes.js", "/auth-shim.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", path
    # 檔案沒變 → 304，不用重新下載
    etag = client.get("/cb/static/cb.js").headers["etag"]
    assert client.get("/cb/static/cb.js", headers={"If-None-Match": etag}).status_code == 304
    # API 的 JSON 不受影響
    assert "no-cache" not in client.get("/api/auth/status").headers.get("cache-control", "")
