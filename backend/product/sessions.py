"""Sessions for both sides. Rows live in our own database; cookies are HttpOnly.

Attorney ("firm") sessions are created only after a Clio OAuth login proves who
the user is, or by the fixture sign-in when CLIO_SOURCE=fixture. They key the
"since your last visit" state, so each person gets their own front page.

Provider sessions are created when a live share link is opened. One session is
one logged view, however many times the page reloads, and a reply is only
accepted from a browser holding the session for that link. Revoking a share
ends its sessions.

Only a SHA-256 of the cookie value is stored. AUTH=off disables the firm-side
check for local debugging (everyone is user "me").
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from backend import db

FIRM_COOKIE = "brief_session"
FIRM_TTL, FIRM_IDLE = timedelta(hours=12), timedelta(hours=2)
PROVIDER_TTL, PROVIDER_IDLE = timedelta(hours=12), timedelta(minutes=30)
PROTECTED = ("/matters", "/items", "/shares", "/config")


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.isoformat(timespec="seconds")


def _hash(raw):
    return hashlib.sha256((raw or "").encode()).hexdigest()


def auth_required():
    return os.environ.get("AUTH", "on").lower() not in ("off", "0", "false")


def fixture_mode():
    return os.environ.get("CLIO_SOURCE") == "fixture"


def provider_cookie(token):
    return "brief_p_" + _hash(token)[:12]


def create(kind, ttl, user_id=None, user_name=None, token=None, user_agent=""):
    raw = secrets.token_urlsafe(32)
    now = _now()
    db.x("INSERT INTO sessions(sid_hash, kind, user_id, user_name, token, ua_hash, created_at, last_seen_at, expires_at,"
         " revoked) VALUES (?,?,?,?,?,?,?,?,?,0)",
         (_hash(raw), kind, user_id, user_name, token, _hash(user_agent)[:16], _iso(now), _iso(now), _iso(now + ttl)))
    return raw, _iso(now)


def lookup(raw, kind, idle, token=None):
    """The live session for this cookie value, or None. Touches last_seen_at."""
    if not raw:
        return None
    rows = db.q("SELECT * FROM sessions WHERE sid_hash=? AND kind=? AND revoked=0", (_hash(raw), kind))
    if not rows:
        return None
    s, now = rows[0], _now()
    if s["expires_at"] <= _iso(now) or s["last_seen_at"] <= _iso(now - idle):
        return None
    if token is not None and s["token"] != token:
        return None
    db.x("UPDATE sessions SET last_seen_at=? WHERE sid_hash=?", (_iso(now), s["sid_hash"]))
    return s


def firm_session(request):
    return lookup(request.cookies.get(FIRM_COOKIE), "firm", FIRM_IDLE)


def provider_session(request, token):
    return lookup(request.cookies.get(provider_cookie(token)), "provider", PROVIDER_IDLE, token=token)


def set_cookie(response, name, raw, ttl, path="/"):
    response.set_cookie(name, raw, max_age=int(ttl.total_seconds()), httponly=True, samesite="lax", path=path)


def revoke(raw):
    db.x("UPDATE sessions SET revoked=1 WHERE sid_hash=?", (_hash(raw),))


def revoke_others(user_id, keep_raw):
    db.x("UPDATE sessions SET revoked=1 WHERE kind='firm' AND user_id=? AND sid_hash<>?", (user_id, _hash(keep_raw)))


def revoke_for_share(token):
    db.x("UPDATE sessions SET revoked=1 WHERE kind='provider' AND token=?", (token,))


def active_for_user(user_id, current_raw=None):
    now = _now()
    rows = db.q("SELECT sid_hash, created_at, last_seen_at FROM sessions WHERE kind='firm' AND user_id=? AND revoked=0"
                " AND expires_at>? AND last_seen_at>? ORDER BY last_seen_at DESC",
                (user_id, _iso(now), _iso(now - FIRM_IDLE)))
    cur = _hash(current_raw)
    return [{"created_at": r["created_at"], "last_seen_at": r["last_seen_at"], "current": r["sid_hash"] == cur}
            for r in rows]
