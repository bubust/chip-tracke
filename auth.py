"""
auth.py - 單一使用者登入（伺服器端驗證）

- 密碼：環境變數 ADMIN_PASSWORD（Fly secret；部署流程會從 GitHub secret 同名變數帶入）。
  未設定時「不啟用保護」（維持舊行為，寫入 API 不擋），/api/auth/status 回報 protected=false，設定頁顯示紅色警告。
- 登入成功回傳簽章 token（預設 30 天），前端放 localStorage，寫入類請求帶 X-Auth-Token。
- 簽章金鑰 = 伺服器隨機密鑰（存 settings 表，重啟不失效）＋ 密碼雜湊 → 換密碼後舊 token 全部失效。
- 登入嘗試限流：同一 IP 10 分鐘內最多 10 次。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

TOKEN_DAYS = 30

_secret_cache: bytes | None = None
_lock = threading.Lock()
_attempts: dict = {}          # ip → [timestamps]
MAX_ATTEMPTS, WINDOW = 10, 600


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def password_configured() -> bool:
    return bool(os.environ.get("ADMIN_PASSWORD", "").strip())


def _pw_digest() -> str:
    return _sha256(os.environ.get("ADMIN_PASSWORD", "").strip())


def check_password(pw: str) -> bool:
    pw = (pw or "").strip()
    if not pw or not password_configured():
        return False
    return hmac.compare_digest(_sha256(pw), _pw_digest())


def _server_secret() -> bytes:
    """隨機伺服器密鑰，存在 settings 表（chip_data 是 Fly volume，重啟不變）"""
    global _secret_cache
    with _lock:
        if _secret_cache:
            return _secret_cache
        env = os.environ.get("AUTH_SECRET", "").strip()
        if env:
            _secret_cache = env.encode()
            return _secret_cache
        try:
            from chip_tracker_v2 import get_conn
            conn = get_conn()
            row = conn.execute("SELECT value FROM settings WHERE key='auth_secret'").fetchone()
            if row and row[0]:
                val = row[0]
            else:
                val = secrets.token_hex(32)
                conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('auth_secret', ?)", (val,))
                conn.commit()
            conn.close()
        except Exception:
            val = secrets.token_hex(32)   # DB 不可用時只在本次程序有效
        _secret_cache = val.encode()
        return _secret_cache


def _sign(payload: str) -> str:
    key = _server_secret() + _pw_digest().encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def make_token(days: int = TOKEN_DAYS) -> str:
    exp = int(time.time()) + days * 86400
    payload = f"{exp}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload)}"


def check_token(token: str) -> bool:
    try:
        exp, nonce, sig = (token or "").split(".")
        if int(exp) < time.time():
            return False
        return hmac.compare_digest(sig, _sign(f"{exp}.{nonce}"))
    except Exception:
        return False


def allow_attempt(ip: str) -> bool:
    now = time.time()
    with _lock:
        lst = [t for t in _attempts.get(ip, []) if now - t < WINDOW]
        if len(lst) >= MAX_ATTEMPTS:
            _attempts[ip] = lst
            return False
        lst.append(now)
        _attempts[ip] = lst
        return True


def client_ip(request) -> str:
    return (request.headers.get("fly-client-ip")
            or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))
