"""Firm and provider sessions over the HTTP API (fake Clio, scripted model, no network)."""
from fastapi.testclient import TestClient

from backend import db
from backend.pipeline import clio, run
from tests.test_pipeline import FakeClio, env  # noqa: F401


def app():
    from backend.main import app
    return app


def sign_in(monkeypatch):
    monkeypatch.setenv("CLIO_SOURCE", "fixture")
    monkeypatch.setattr(clio, "make_client", lambda: FakeClio())
    c = TestClient(app())
    assert c.post("/auth/dev/login").status_code == 200
    return c


def test_firm_routes_need_a_session(env, monkeypatch):
    run.run_pipeline("7")
    anon = TestClient(app())
    for path in ("/config", "/matters/7/edition", "/matters/7/providers", "/items/note:1", "/matters/7/replies"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/matters/7/shares", json={"provider_contact_id": "contact:20"}).status_code == 401
    assert anon.get("/auth/me").json()["authenticated"] is False
    assert anon.post("/auth/dev/login").status_code == 404          # no fixture mode, no shortcut

    c = sign_in(monkeypatch)
    me = c.get("/auth/me").json()
    assert me["authenticated"] and me["user"] == {"id": "user:1", "name": "Pat Lawyer"} and len(me["sessions"]) == 1
    assert c.get("/matters/7/edition").status_code == 200

    # visits are per signed-in user, not a shared "me"
    c.post("/matters/7/visit")
    assert [r["user_id"] for r in db.q("SELECT user_id FROM visits")] == ["user:1"]

    # a second browser, then sign the other one out
    c2 = sign_in(monkeypatch)
    assert len(c2.get("/auth/me").json()["sessions"]) == 2
    c2.post("/auth/logout?everywhere_else=true")
    assert c.get("/matters/7/edition").status_code == 401
    assert c2.get("/matters/7/edition").status_code == 200

    c2.post("/auth/logout")
    assert c2.get("/matters/7/edition").status_code == 401
    # the raw cookie value is never stored
    assert all(len(r["sid_hash"]) == 64 for r in db.q("SELECT sid_hash FROM sessions"))


def test_provider_sessions(env, monkeypatch):
    run.run_pipeline("7")
    firm = sign_in(monkeypatch)
    tok = firm.post("/matters/7/shares", json={"provider_contact_id": "contact:20"}).json()["token"]

    office = TestClient(app())                       # the provider's browser: no firm session
    page = office.get(f"/p/{tok}")
    assert page.status_code == 200 and "brief_p_" in page.headers["set-cookie"] and "HttpOnly" in page.headers["set-cookie"]
    office.get(f"/p/{tok}"); office.get(f"/p/{tok}")  # reloads
    assert db.q("SELECT COUNT(*) n FROM share_views")[0]["n"] == 1      # one session, one logged view
    assert office.get("/matters/7/edition").status_code == 401          # a provider session opens nothing else

    req = page.json()["sections"]["requests"][0]
    body = {"request_ref": req["ref"], "fields": {req["fields"][0]["name"]: "2026-11-12"}}
    stranger = TestClient(app())                     # has the URL but never opened the page
    assert stranger.post(f"/p/{tok}/reply", json=body).status_code == 401
    assert office.post(f"/p/{tok}/reply", json=body).status_code == 200

    other = TestClient(app())                        # a second device is a second view
    other.get(f"/p/{tok}")
    assert db.q("SELECT COUNT(*) n FROM share_views")[0]["n"] == 2

    firm.post(f"/shares/{tok}/revoke")               # revoking the share ends its sessions
    assert office.get(f"/p/{tok}").status_code == 404
    assert office.post(f"/p/{tok}/reply", json=body).status_code in (400, 401)
    assert db.q("SELECT COUNT(*) n FROM sessions WHERE kind='provider' AND revoked=0")[0]["n"] == 0


def test_auth_off_switch(env, monkeypatch):
    run.run_pipeline("7")
    monkeypatch.setenv("AUTH", "off")
    assert TestClient(app()).get("/matters/7/edition").status_code == 200
