"""Clio OAuth (authorization code flow). Tokens live in our own database.

Mount in main.py with: app.include_router(auth.router)
"""
import contextvars
import hmac
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend import db
from backend.pipeline.clio import clio_base

router = APIRouter()

STATE_COOKIE = "brief_oauth_state"
_acting_user: contextvars.ContextVar = contextvars.ContextVar("clio_acting_user", default=None)


def acting_as(user_id):
    """Run Clio calls on this thread/task as `user_id` (the signed-in firm user who asked for them)."""
    return _acting_user.set(user_id)


def _cfg(name):
    val = os.environ.get(name)
    if not val:
        raise HTTPException(500, f"{name} is not set")
    return val


def _save(user_id: str, tok: dict) -> None:
    with db.connect() as conn:
        old = conn.execute("SELECT refresh_token, is_service FROM clio_tokens WHERE user_id=?", (user_id,)).fetchone()
        has_service = conn.execute("SELECT 1 FROM clio_tokens WHERE is_service=1").fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO clio_tokens(user_id, access_token, refresh_token, expires_at, is_service, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (user_id, tok["access_token"], tok.get("refresh_token") or (old["refresh_token"] if old else None),
             time.time() + float(tok.get("expires_in", 3600)) - 60,
             1 if (old and old["is_service"]) or not has_service else 0, db.now_iso()))


def _token_request(data: dict) -> dict:
    data = {**data, "client_id": _cfg("CLIO_CLIENT_ID"), "client_secret": _cfg("CLIO_CLIENT_SECRET")}
    resp = httpx.post(f"{clio_base()}/oauth/token", data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _row(conn, user_id):
    if user_id:
        return conn.execute("SELECT * FROM clio_tokens WHERE user_id=?", (user_id,)).fetchone()
    row = conn.execute("SELECT * FROM clio_tokens WHERE is_service=1").fetchone()
    if not row:                      # token saved by an earlier version, before tokens were per user
        legacy = conn.execute("SELECT * FROM oauth_tokens WHERE id=1").fetchone()
        if legacy:
            conn.execute("INSERT OR IGNORE INTO clio_tokens(user_id, access_token, refresh_token, expires_at, is_service,"
                         " updated_at) VALUES ('legacy',?,?,?,1,?)",
                         (legacy["access_token"], legacy["refresh_token"], legacy["expires_at"], db.now_iso()))
            conn.commit()
            row = conn.execute("SELECT * FROM clio_tokens WHERE user_id='legacy'").fetchone()
    return row


def access_token(user_id: str | None = None, force: bool = False) -> str:
    """A signed-in user's own Clio token. With no user, the account background work runs as. One user's login
    never replaces another's token."""
    user_id = user_id or _acting_user.get()
    with db.connect() as conn:
        row = _row(conn, user_id)
    if not row:
        raise RuntimeError("Clio is not connected for this user: open /auth/clio/login first")
    if force or (row["expires_at"] and row["expires_at"] < time.time()):
        if not row["refresh_token"]:
            raise RuntimeError("Clio token expired and there is no refresh token: log in again")
        _save(row["user_id"], _token_request({"grant_type": "refresh_token", "refresh_token": row["refresh_token"]}))
        return access_token(row["user_id"])
    return row["access_token"]


@router.get("/auth/clio/login")
def login():
    state = secrets.token_urlsafe(24)
    q = urlencode({
        "response_type": "code",
        "client_id": _cfg("CLIO_CLIENT_ID"),
        "redirect_uri": _cfg("CLIO_REDIRECT_URI"),
        "state": state,
    })
    resp = RedirectResponse(f"{clio_base()}/oauth/authorize?{q}")
    # The state is tied to this browser: the callback only accepts the one this browser was given.
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", path="/auth/clio")
    return resp


@router.get("/auth/clio/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, f"Clio returned: {error}")
    mine = request.cookies.get(STATE_COOKIE)
    if not code or not state or not mine or not hmac.compare_digest(mine, state):
        raise HTTPException(400, "invalid OAuth state: start again from /auth/clio/login in this browser")
    tok = _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _cfg("CLIO_REDIRECT_URI"),
    })
    try:
        # Who just logged in comes from the token they just got, never from a shared one.
        me = httpx.get(f"{clio_base()}/api/v4/users/who_am_i.json", params={"fields": "id,name"},
                       headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30)
        me.raise_for_status()
        u = me.json()["data"]
        user_id = f"user:{u['id']}"
        _save(user_id, tok)
        from backend.product import sessions
        raw, _ = sessions.create("firm", sessions.FIRM_TTL, user_id=user_id, user_name=u.get("name"),
                                 user_agent=request.headers.get("user-agent", ""))
        resp = RedirectResponse("/")
        sessions.set_cookie(resp, sessions.FIRM_COOKIE, raw, sessions.FIRM_TTL)
        resp.delete_cookie(STATE_COOKIE, path="/auth/clio")
        return resp
    except Exception:
        return HTMLResponse("<p>Clio connected (read-only), but the sign-in step failed. Reload and try again.</p>")
