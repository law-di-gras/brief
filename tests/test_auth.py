"""Clio tokens are per user, and the OAuth state belongs to the browser that started the login."""
import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.pipeline import auth


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("CLIO_CLIENT_ID", "id")
    monkeypatch.setenv("CLIO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CLIO_REDIRECT_URI", "http://127.0.0.1:8000/auth/clio/callback")


def tok(name):
    return {"access_token": f"access-{name}", "refresh_token": f"refresh-{name}", "expires_in": 3600}


def test_second_login_does_not_replace_the_first_users_token(env):
    auth._save("user:1", tok("A"))
    auth._save("user:2", tok("B"))
    assert auth.access_token("user:1") == "access-A"
    assert auth.access_token("user:2") == "access-B"
    assert auth.access_token() == "access-A"            # background work stays on the first account


def test_acting_user_is_respected(env):
    auth._save("user:1", tok("A"))
    auth._save("user:2", tok("B"))
    auth.acting_as("user:2")
    try:
        assert auth.access_token() == "access-B"
    finally:
        auth.acting_as(None)


def test_unknown_user_gets_no_token(env):
    auth._save("user:1", tok("A"))
    with pytest.raises(RuntimeError):
        auth.access_token("user:9")


def test_callback_refuses_a_state_from_another_browser(env):
    from backend.main import app
    c = TestClient(app, follow_redirects=False)
    assert c.get("/auth/clio/callback?code=x&state=forged").status_code == 400      # no state cookie at all
    login = c.get("/auth/clio/login")
    state = login.headers["location"].split("state=")[1].split("&")[0]
    other = TestClient(app, follow_redirects=False)                                    # a different browser
    assert other.get(f"/auth/clio/callback?code=x&state={state}").status_code == 400
    assert c.get("/auth/clio/callback?code=x&state=wrong").status_code == 400          # right browser, wrong state
