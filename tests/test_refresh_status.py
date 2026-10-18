"""全系統更新進度：伺服器中途重啟後要顯示「中斷」，不能誤報完成。python -m pytest tests/test_refresh_status.py -q"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_interrupted_after_restart(tmp_path, monkeypatch):
    import server
    f = tmp_path / "refresh_all_status.json"
    st = json.loads(json.dumps(server._refresh_all_status))
    st["running"] = True
    for k in st["steps"]:
        st["steps"][k]["status"] = "pending"
    st["steps"]["watchlist"]["status"] = "done"
    st["steps"]["regime"]["status"] = "done"
    st["steps"]["tdcc"]["status"] = "running"
    f.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(server, "_REFRESH_STATUS_FILE", f)
    server._load_refresh_status()
    s = server._refresh_all_status
    assert s["running"] is False and s["interrupted"] is True
    assert s["steps"]["tdcc"]["status"] == "interrupted" and s["steps"]["positioning"]["status"] == "pending"
    assert s["steps"]["regime"]["status"] == "done"
    server._set_step("tdcc", "done")                         # 每一步都會寫回檔案
    assert json.loads(f.read_text(encoding="utf-8"))["steps"]["tdcc"]["status"] == "done"
