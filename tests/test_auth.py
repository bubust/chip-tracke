"""寫入保護：python -m pytest tests/test_auth.py -q"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth


def _reset(monkeypatch, pw):
    if pw is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", pw)
    monkeypatch.setenv("AUTH_SECRET", "unit-test-secret")
    auth._secret_cache = None
    auth._attempts.clear()


def test_not_configured_means_unprotected(monkeypatch):
    _reset(monkeypatch, None)
    assert auth.password_configured() is False
    assert auth.check_password("anything") is False


def test_password_and_token(monkeypatch):
    _reset(monkeypatch, "pw-for-tests")
    assert auth.check_password("pw-for-tests") and not auth.check_password("nope")
    t = auth.make_token()
    assert auth.check_token(t)
    assert not auth.check_token(t[:-1] + ("0" if t[-1] != "0" else "1"))   # 竄改簽章
    assert not auth.check_token("garbage") and not auth.check_token("")


def test_changing_password_invalidates_tokens(monkeypatch):
    _reset(monkeypatch, "old-pw")
    t = auth.make_token()
    monkeypatch.setenv("ADMIN_PASSWORD", "new-pw")
    assert not auth.check_token(t)


def test_expired_token_rejected(monkeypatch):
    _reset(monkeypatch, "pw")
    exp = int(time.time()) - 10
    payload = f"{exp}.abcd"
    assert not auth.check_token(f"{payload}.{auth._sign(payload)}")


def test_login_rate_limit(monkeypatch):
    _reset(monkeypatch, "pw")
    assert all(auth.allow_attempt("1.2.3.4") for _ in range(auth.MAX_ATTEMPTS))
    assert not auth.allow_attempt("1.2.3.4")
    assert auth.allow_attempt("5.6.7.8")
