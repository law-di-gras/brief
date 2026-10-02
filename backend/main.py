import os
from datetime import timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import db
from backend.product import bridge, provider, replies
from backend.product import deterministic as det

app = FastAPI(title="Brief")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# A's OAuth routes (/auth/clio/login, /auth/clio/callback) mount here once pushed.
try:
    from backend.pipeline.auth import router as auth_router
    app.include_router(auth_router)
except Exception:
    pass


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
def sync(mid: str):
    return bridge.run_pipeline(mid)


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
def edition(mid: str, since: str | None = None, user: str = "me"):
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
def visit(mid: str, user: str = "me"):
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
    return need(provider.public_view(token, request.headers.get("user-agent", "")),
                "This link has expired or been revoked.")


@app.post("/p/{token}/reply")
def reply(token: str, body: ReplyIn, bg: BackgroundTasks):
    try:
        out = replies.submit(token, body.request_ref, body.fields, body.note)
    except replies.ReplyError as e:
        raise HTTPException(400, str(e))
    # Saved first so the attorney inbox has it right away, then the pipeline picks it up as a portal item.
    bg.add_task(bridge.run_pipeline, out["matter_id"])
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
