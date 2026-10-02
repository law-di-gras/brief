"""Clio OAuth (authorization code flow). Tokens live in our own database.

Mount in main.py with: app.include_router(auth.router)
"""
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from backend import db
from backend.pipeline.clio import clio_base

router = APIRouter()
_states: set[str] = set()


def _cfg(name):
    val = os.environ.get(name)
    if not val:
        raise HTTPException(500, f"{name} is not set")
    return val


def _save(tok: dict) -> None:
    with db.connect() as conn:
        old = conn.execute("SELECT refresh_token FROM oauth_tokens WHERE id=1").fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO oauth_tokens(id, access_token, refresh_token, expires_at) VALUES (1,?,?,?)",
            (tok["access_token"], tok.get("refresh_token") or (old["refresh_token"] if old else None),
             time.time() + float(tok.get("expires_in", 3600)) - 60),
        )


def _token_request(data: dict) -> dict:
    data = {**data, "client_id": _cfg("CLIO_CLIENT_ID"), "client_secret": _cfg("CLIO_CLIENT_SECRET")}
    resp = httpx.post(f"{clio_base()}/oauth/token", data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def access_token(force: bool = False) -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM oauth_tokens WHERE id=1").fetchone()
    if not row:
        raise RuntimeError("Clio is not connected: open /auth/clio/login first")
    if force or (row["expires_at"] and row["expires_at"] < time.time()):
        if not row["refresh_token"]:
            raise RuntimeError("Clio token expired and there is no refresh token: log in again")
        _save(_token_request({"grant_type": "refresh_token", "refresh_token": row["refresh_token"]}))
        return access_token()
    return row["access_token"]


@router.get("/auth/clio/login")
def login():
    state = secrets.token_urlsafe(16)
    _states.add(state)
    q = urlencode({
        "response_type": "code",
        "client_id": _cfg("CLIO_CLIENT_ID"),
        "redirect_uri": _cfg("CLIO_REDIRECT_URI"),
        "state": state,
    })
    return RedirectResponse(f"{clio_base()}/oauth/authorize?{q}")


@router.get("/auth/clio/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, f"Clio returned: {error}")
    if not code or state not in _states:
        raise HTTPException(400, "invalid OAuth state")
    _states.discard(state)
    _save(_token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _cfg("CLIO_REDIRECT_URI"),
    }))
    # The OAuth login is the one moment the user's identity is proven, so the firm session starts here.
    try:
        from backend.product import sessions
        me = httpx.get(f"{clio_base()}/api/v4/users/who_am_i.json", params={"fields": "id,name"},
                       headers={"Authorization": f"Bearer {access_token()}"}, timeout=30)
        me.raise_for_status()
        u = me.json()["data"]
        raw, _ = sessions.create("firm", sessions.FIRM_TTL, user_id=f"user:{u['id']}", user_name=u.get("name"))
        resp = RedirectResponse("/")
        sessions.set_cookie(resp, sessions.FIRM_COOKIE, raw, sessions.FIRM_TTL)
        return resp
    except Exception:
        return HTMLResponse("<p>Clio connected (read-only), but the sign-in step failed. Reload and try again.</p>")
