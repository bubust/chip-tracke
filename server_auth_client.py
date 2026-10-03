"""
本機腳本推資料到網站時的登入（treasury_sync.py、tdcc_local.py 共用）。
密碼讀環境變數 CHIP_ADMIN_PASSWORD；沒設就互動輸入（不會顯示在畫面上）。網站沒開寫入保護時不需要密碼。
"""
import getpass
import os

import httpx


def auth_headers(server: str) -> dict:
    server = server.rstrip("/")
    try:
        st = httpx.get(f"{server}/api/auth/status", timeout=20).json()
    except Exception:
        return {}
    if not st.get("protected"):
        return {}
    pw = os.environ.get("CHIP_ADMIN_PASSWORD") or getpass.getpass("網站密碼（ADMIN_PASSWORD）：")
    r = httpx.post(f"{server}/api/auth/login", json={"password": pw}, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"登入失敗：{r.status_code} {r.text[:200]}")
    return {"X-Auth-Token": r.json().get("token", "")}
