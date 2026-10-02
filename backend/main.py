import faulthandler
import os
import threading
import signal
from datetime import timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend import db
from backend.product import bridge, provider, replies, sessions
from backend.product import deterministic as det

# `kill -USR1 <pid>` prints every thread's stack to the server log, for diagnosing a stuck server.
faulthandler.register(signal.SIGUSR1, all_threads=True)

app = FastAPI(title="Brief")


@app.on_event("startup")
async def one_request_thread():
    """Run sync request handlers one at a time. Many SQLite connections opening and closing at once in one
    process deadlocked inside SQLite's file locking (threads stuck in connect/close at 0% CPU). Each page
    request takes well under a second, so serializing them costs little and removes the stall."""
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens = int(os.environ.get("REQUEST_THREADS", "1"))
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# A's OAuth routes (/auth/clio/login, /auth/clio/callback) mount here once pushed.
try:
    from backend.pipeline.auth import router as auth_router
    app.include_router(auth_router)
except Exception:
    pass


# ---------- sessions ----------

@app.middleware("http")
async def require_firm_session(request: Request, call_next):
    """Everything the firm sees needs a firm session. /p/* is the provider side and has its own."""
    request.state.user = {"id": "me", "name": None}
    if sessions.auth_required() and request.url.path.startswith(sessions.PROTECTED) and request.method != "OPTIONS":
        # The lookup touches SQLite; run it off the event loop so a busy database can never freeze the server.
        s = await run_in_threadpool(sessions.firm_session, request)
        if not s:
            return JSONResponse({"detail": "Sign in to continue."}, status_code=401)
        request.state.user = {"id": s["user_id"], "name": s["user_name"]}
    return await call_next(request)


@app.get("/auth/me")
def me(request: Request):
    base = {"auth_required": sessions.auth_required(), "fixture_mode": sessions.fixture_mode()}
    s = sessions.firm_session(request) if sessions.auth_required() else None
    if not s:
        return {**base, "authenticated": not sessions.auth_required(), "user": None, "sessions": []}
    return {**base, "authenticated": True, "user": {"id": s["user_id"], "name": s["user_name"]},
            "sessions": sessions.active_for_user(s["user_id"], request.cookies.get(sessions.FIRM_COOKIE))}


@app.post("/auth/dev/login")
def dev_login(request: Request):
    """Fixture sign-in: only exists when the app is reading the seed file instead of Clio."""
    if not sessions.fixture_mode():
        raise HTTPException(404, "Not found")
    from backend.pipeline.clio import make_client
    u = make_client().get("/users/who_am_i.json", {"fields": "id,name"})["data"]
    raw, _ = sessions.create("firm", sessions.FIRM_TTL, user_id=f"user:{u['id']}", user_name=u.get("name"),
                             user_agent=request.headers.get("user-agent", ""))
    resp = JSONResponse({"ok": True})
    sessions.set_cookie(resp, sessions.FIRM_COOKIE, raw, sessions.FIRM_TTL)
    return resp


@app.post("/auth/logout")
def logout(request: Request, everywhere_else: bool = False):
    raw = request.cookies.get(sessions.FIRM_COOKIE)
    s = sessions.firm_session(request)
    resp = JSONResponse({"ok": True})
    if s and everywhere_else:
        sessions.revoke_others(s["user_id"], raw)
    elif raw:
        sessions.revoke(raw)
        resp.delete_cookie(sessions.FIRM_COOKIE, path="/")
    return resp


def need(v, msg="Not found"):
    if v is None:
        raise HTTPException(404, msg)
    return v


@app.get("/config")
def config():
    m = db.q("SELECT clio_id FROM items WHERE clio_type='matter' LIMIT 1")
    return {"matter_id": os.environ.get("MATTER_ID") or (m[0]["clio_id"] if m else None),
            "pipeline_live": bridge.PIPELINE_LIVE}


# ---------- attorney ----------

@app.post("/matters/{mid}/sync")
def sync(mid: str, request: Request):
    return bridge.run_pipeline(mid, user_id=request.state.user["id"] if request.state.user["id"] != "me" else None)


DEFAULT_SINCE_DAYS = 14


def client_photo(mid: str):
    conn = db.connect()
    try:
        path = db.get_meta(conn, mid, "client_photo")
    finally:
        conn.close()
    return path if path and Path(path).exists() else None


@app.get("/matters/{mid}/photo")
def photo(mid: str):
    return FileResponse(need(client_photo(mid), "No client photo on file"))


@app.get("/matters/{mid}/edition")
def edition(mid: str, request: Request, since: str | None = None):
    user = request.state.user["id"]
    need(det.matter(mid), "Matter not loaded. Run the sync or dev/load_seed.py.")
    since_source = "query" if since else None
    if not since:
        v = db.q("SELECT last_visit_at FROM visits WHERE user_id=? AND matter_id=?", (user, mid))
        if v:
            since, since_source = v[0]["last_visit_at"], "visit"
        else:
            # First visit: still answer "what's been happening", over a fixed recent window.
            since, since_source = (det.today() - timedelta(days=DEFAULT_SINCE_DAYS)).isoformat(), "default"
    ed = bridge.build_edition(mid, since) or {}
    masthead = det.masthead(mid, since)
    masthead.update(since_source=since_source, since_days=DEFAULT_SINCE_DAYS,
                    photo_url=f"/matters/{mid}/photo" if client_photo(mid) else None)
    return {
        "masthead": masthead,
        "headline": ed.get("headline"),
        "lead": ed.get("lead") or [],
        "blocker": ed.get("blocker"),
        "front_page_pending": ed.get("front_page_pending", False),
        "kpis": det.kpis(mid),
        "corrections": det.corrections(mid),
        "still_waiting": det.still_waiting(mid),
        "coming_up": det.coming_up(mid),
        "last_client_contact": det.last_client_contact(mid),
        "pipeline_live": bridge.PIPELINE_LIVE,
    }


@app.get("/matters/{mid}/timeline")
def timeline(mid: str):
    return det.timeline(mid)


@app.post("/matters/{mid}/visit")
def visit(mid: str, request: Request):
    user = request.state.user["id"]
    stamp = provider.now()
    db.x("INSERT INTO visits(user_id, matter_id, last_visit_at) VALUES (?,?,?)"
         " ON CONFLICT(user_id, matter_id) DO UPDATE SET last_visit_at=excluded.last_visit_at", (user, mid, stamp))
    return {"last_visit_at": stamp}


@app.get("/items/{item_id}")
def item(item_id: str):
    return need(det.source(item_id))


@app.get("/matters/{mid}/items")
def full_file(mid: str):
    return det.full_file(mid)


@app.get("/matters/{mid}/runs")
def runs(mid: str):
    return db.q("SELECT * FROM runs ORDER BY id DESC LIMIT 20")


# ---------- provider shares (attorney side) ----------

class ShareIn(BaseModel):
    provider_contact_id: str
    sections: dict[str, bool] | None = None


class RefreshIn(BaseModel):
    sections: dict[str, bool] | None = None


@app.get("/matters/{mid}/providers")
def providers(mid: str):
    return provider.panel(mid)


@app.get("/matters/{mid}/providers/{cid}/review")
def review(mid: str, cid: str):
    return need(provider.review(mid, cid))


@app.get("/matters/{mid}/shares")
def shares(mid: str):
    return [dict(p["share"], contact_id=p["contact_id"], name=p["name"]) for p in provider.panel(mid) if p["share"]]


@app.post("/matters/{mid}/shares")
def create_share(mid: str, body: ShareIn):
    try:
        s = provider.create_share(mid, body.provider_contact_id, body.sections)
    except KeyError as e:
        raise HTTPException(400, str(e))
    return {"token": s["token"], "expires_at": s["expires_at"], "path": f"/p/{s['token']}"}


@app.post("/shares/{token}/refresh")
def refresh(token: str, body: RefreshIn | None = None):
    s = need(provider.refresh_share(token, body.sections if body else None), "Share is revoked or expired")
    return {"token": s["token"], "refreshed_at": s["refreshed_at"]}


@app.post("/shares/{token}/revoke")
def revoke(token: str):
    need(provider.revoke_share(token))
    sessions.revoke_for_share(token)
    return {"revoked": True}


@app.get("/matters/{mid}/replies")
def inbox(mid: str):
    return replies.inbox(mid)


@app.post("/matters/{mid}/replies/ack")
def ack(mid: str):
    return replies.acknowledge(mid)


# ---------- public provider page ----------

class ReplyIn(BaseModel):
    request_ref: str
    fields: dict[str, str] | None = None
    note: str | None = ""


@app.get("/p/{token}")
def provider_page(token: str, request: Request):
    """Opening a live link starts a provider session. One session is one logged view."""
    gone = "This link has expired or been revoked."
    share = need(provider.get_share(token), gone)
    if not share["live"]:
        raise HTTPException(404, gone)
    ua = request.headers.get("user-agent", "")
    s, raw = sessions.provider_session(request, token), None
    if s:
        started = s["created_at"]
    else:
        raw, started = sessions.create("provider", sessions.PROVIDER_TTL, token=token, user_agent=ua)
    page = need(provider.public_view(token, ua, session_started=started, log_view=raw is not None), gone)
    resp = JSONResponse(page)
    if raw:
        sessions.set_cookie(resp, sessions.provider_cookie(token), raw, sessions.PROVIDER_TTL, path=f"/p/{token}")
    return resp


@app.post("/p/{token}/reply")
def reply(token: str, body: ReplyIn, bg: BackgroundTasks, request: Request):
    if not sessions.provider_session(request, token):
        raise HTTPException(401, "Your session ended. Reload the page and send again.")
    try:
        out = replies.submit(token, body.request_ref, body.fields, body.note)
    except replies.ReplyError as e:
        raise HTTPException(400, str(e))
    # Saved first so the attorney inbox has it right away, then the pipeline picks it up as a portal item.
    # Its own thread, not the request pool: a pipeline run can take minutes and must not hold up page loads.
    threading.Thread(target=bridge.run_pipeline, args=(out["matter_id"],), daemon=True).start()
    return {"ok": True, "created_at": out["created_at"]}


# ---------- built frontend (optional) ----------
# If frontend/dist exists, serve it here so the app runs without Node: open http://localhost:8000/
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html")
