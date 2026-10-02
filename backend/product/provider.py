"""Provider side: roles, sections, share tokens, snapshots, view log.

The public page renders only from shares.snapshot_json, the frozen copy the
attorney approved. public_view() never queries facts, items or conflicts.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from backend import db
from backend.product import ai, bridge
from backend.product import deterministic as det

SECTIONS = [
    ("status", "Case status", True),
    ("requests", "What the firm needs from your office", True),
    ("treatment", "Treatment on file", True),
    ("updates", "Recent updates", True),
    ("coverage", "Coverage", False),
    ("other_treatment", "Other treatment on file", False),
    ("patient_told_us", "What your patient told us", False),
]
DEFAULTS = {k: on for k, _, on in SECTIONS}
NOT_SHARED = ["Liability", "Valuation", "Strategy", "Corrections"]
EXPIRY_DAYS = 30


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def roles(matter_id):
    people = det.contacts(matter_id)
    client = det.client_id(matter_id)
    people.pop(client, None)
    mapped = ai.classify_roles([p["description"] for p in people.values()])
    return {cid: dict(p, role=mapped.get(p["description"], "other")) for cid, p in people.items()}


def providers(matter_id):
    return {cid: p for cid, p in roles(matter_id).items() if p["role"] == "treating_provider"}


def build_sections(matter_id, cid):
    """Every section for one provider, built fresh from internal data. Attorney-only."""
    m = det.matter(matter_id)
    raw = m["raw"] if m else {}
    t = det.today()
    facts = det.facts()

    dated = [det.local_date(i["item_date"]) for i in det.items("clio_type NOT IN ('matter','relationship')")]
    dated = [d for d in dated if d and d <= t]
    status = {"status": raw.get("status"), "stage": (raw.get("matter_stage") or {}).get("name"),
              "last_activity": det.iso(max(dated)) if dated else None}

    cov = next(k for k in det.kpis(matter_id) if k["slot"] == "coverage")
    if cov["conflict"]:
        coverage = {"held": True, "reason": "Held back while the file has an open coverage conflict."}
    else:
        coverage = {"held": False, "state": "confirmed" if cov["value"] else "not yet confirmed"}

    requests = [{k: r[k] for k in ("ref", "what", "first_asked", "last_asked", "times_asked", "fields")}
                for r in det.open_requests(cid, facts) if not r["answered"]]

    seen = sorted((f for f in facts if f["category"] == "treatment" and f["audience"] == "shareable"
                   and cid in f["entities"] and det.local_date(f["event_date"]) and det.local_date(f["event_date"]) <= t),
                  key=lambda f: f["event_date"])
    name = providers(matter_id).get(cid, {}).get("name", "")
    upcoming = [{"title": i["title"], "date": det.iso(det.local_date(i["item_date"]))}
                for i in det.items("clio_type='calendar_entry'")
                if (det.local_date(i["item_date"]) or t) > t - timedelta(days=1) and det.local_date(i["item_date"])
                and any(p.get("id") == cid for p in i["people"])]
    treatment = {"last_reported": {"text": seen[-1]["text"], "date": seen[-1]["event_date"]} if seen else None,
                 "upcoming": sorted(upcoming, key=lambda u: u["date"])}

    other = [{"name": p["name"], "specialty": p["description"]} for c, p in providers(matter_id).items() if c != cid]

    shareable = sorted((f for f in facts if f["audience"] == "shareable" and f["event_date"]
                        and f["category"] not in ("provider_request",)
                        and (cid in f["entities"] or not any(e in providers(matter_id) for e in f["entities"]))),
                       key=lambda f: f["event_date"], reverse=True)[:6]
    updates = [{"id": f["id"], "text": f["text"], "date": f["event_date"]} for f in shareable]

    told = []
    b = bridge.build_edition(matter_id, None).get("blocker")
    if b and b.get("disputed") and not b.get("resolved") and any(h["holder"] == cid for h in b["holders"]):
        # Statements that name this provider as the one holding things up, quoted as written.
        told = [{"quote": h["quote"], "date": h.get("date"), "about": b["label"]} for h in b["holders"] if h["holder"] == cid]

    return {"provider_name": name, "status": status, "coverage": coverage, "requests": requests,
            "treatment": treatment, "other_treatment": other, "updates": updates, "patient_told_us": told}


def make_snapshot(matter_id, cid, sections, previous=None):
    full = build_sections(matter_id, cid)
    m = det.matter(matter_id)
    stamp = now()
    old = {u["id"]: u.get("shared_at") for u in ((previous or {}).get("sections", {}).get("updates") or [])}
    snap = {"provider_name": full["provider_name"], "patient": ((m["raw"].get("client") if m else None) or {}).get("name"),
            "generated_at": stamp, "sections": {}, "not_shared": NOT_SHARED}
    for key, _, _ in SECTIONS:
        if sections.get(key):
            snap["sections"][key] = full[key]
    for u in snap["sections"].get("updates", []):
        u["shared_at"] = old.get(u["id"]) or stamp
    return snap


def create_share(matter_id, cid, sections=None):
    if cid not in providers(matter_id):
        raise KeyError("not a treating provider on this matter")
    sections = {**DEFAULTS, **(sections or {})}
    token = secrets.token_urlsafe(32)
    stamp = now()
    expires = (datetime.now(timezone.utc) + timedelta(days=EXPIRY_DAYS)).isoformat(timespec="seconds")
    db.x("UPDATE shares SET revoked=1 WHERE matter_id=? AND provider_contact_id=?", (str(matter_id), cid))
    db.x("INSERT INTO shares(token,matter_id,provider_contact_id,sections_json,snapshot_json,created_at,refreshed_at,"
         "expires_at,revoked) VALUES (?,?,?,?,?,?,?,?,0)",
         (token, str(matter_id), cid, json.dumps(sections), json.dumps(make_snapshot(matter_id, cid, sections)),
          stamp, stamp, expires))
    return get_share(token)


def get_share(token):
    rows = db.q("SELECT * FROM shares WHERE token=?", (token,))
    if not rows:
        return None
    s = rows[0]
    s["sections"] = db.J(s.pop("sections_json"), {})
    s["snapshot"] = db.J(s.pop("snapshot_json"), {})
    s["live"] = not s["revoked"] and s["expires_at"] > now()
    return s


def refresh_share(token, sections=None):
    s = get_share(token)
    if not s or not s["live"]:
        return None
    sections = {**s["sections"], **(sections or {})}
    snap = make_snapshot(s["matter_id"], s["provider_contact_id"], sections, previous=s["snapshot"])
    db.x("UPDATE shares SET sections_json=?, snapshot_json=?, refreshed_at=? WHERE token=?",
         (json.dumps(sections), json.dumps(snap), now(), token))
    return get_share(token)


def revoke_share(token):
    db.x("UPDATE shares SET revoked=1 WHERE token=?", (token,))
    return get_share(token)


def public_view(token, user_agent=""):
    """The provider page. Snapshot + view log + this token's own replies, nothing else."""
    s = get_share(token)
    if not s or not s["live"]:
        return None
    prev = db.q("SELECT MAX(viewed_at) AS t FROM share_views WHERE token=?", (token,))[0]["t"]
    db.x("INSERT INTO share_views(token, viewed_at, ua_hash) VALUES (?,?,?)",
         (token, now(), hashlib.sha256((user_agent or "").encode()).hexdigest()[:16]))
    snap = s["snapshot"]
    updates = snap.get("sections", {}).get("updates")
    new = None
    if updates is not None:
        new = len([u for u in updates if not prev or (u.get("shared_at") or "") > prev])
    mine = {}
    for r in db.q("SELECT request_ref, field, value, note, created_at FROM provider_replies WHERE token=? ORDER BY id", (token,)):
        mine.setdefault(r["request_ref"], []).append(r)
    return dict(snap, last_view=prev, new_updates=new, refreshed_at=s["refreshed_at"], expires_at=s["expires_at"],
                my_replies=mine)


def pending_updates(share):
    """How much has moved since the attorney last approved this share."""
    fresh = make_snapshot(share["matter_id"], share["provider_contact_id"], share["sections"], previous=share["snapshot"])
    n = 0
    for key, new in fresh["sections"].items():
        old = share["snapshot"].get("sections", {}).get(key)
        if key == "updates":
            have = {u["id"] for u in old or []}
            n += len([u for u in new if u["id"] not in have])
        elif key == "requests":
            have = {r["ref"] for r in old or []}
            n += len({r["ref"] for r in new} ^ have)
        elif json.dumps(new, sort_keys=True) != json.dumps(old, sort_keys=True):
            n += 1
    return n


def active_share(matter_id, cid):
    rows = db.q("SELECT token FROM shares WHERE matter_id=? AND provider_contact_id=? ORDER BY created_at DESC LIMIT 1",
                (str(matter_id), cid))
    return get_share(rows[0]["token"]) if rows else None


def panel(matter_id):
    out = []
    for cid, p in providers(matter_id).items():
        s = active_share(matter_id, cid)
        row = {"contact_id": cid, "name": p["name"], "specialty": p["description"], "share": None,
               "new_replies": db.q("SELECT COUNT(*) AS n FROM provider_replies WHERE provider_contact_id=? AND status='new'",
                                   (cid,))[0]["n"]}
        if s:
            v = db.q("SELECT COUNT(*) AS n, MAX(viewed_at) AS last FROM share_views WHERE token=?", (s["token"],))[0]
            row["share"] = {"token": s["token"], "live": s["live"], "revoked": bool(s["revoked"]),
                            "created_at": s["created_at"], "refreshed_at": s["refreshed_at"],
                            "expires_at": s["expires_at"], "opens": v["n"], "last_opened": v["last"],
                            "sections": s["sections"],
                            "pending_updates": pending_updates(s) if s["live"] else 0}
        out.append(row)
    return out


def review(matter_id, cid):
    """Review screen: every section in full, the toggles, and the current share."""
    if cid not in providers(matter_id):
        return None
    s = active_share(matter_id, cid)
    return {"contact_id": cid, "preview": build_sections(matter_id, cid),
            "sections": [{"key": k, "label": label, "default": on} for k, label, on in SECTIONS],
            "selected": s["sections"] if s and s["live"] else DEFAULTS, "not_shared": NOT_SHARED,
            "share": next((r["share"] for r in panel(matter_id) if r["contact_id"] == cid), None)}
