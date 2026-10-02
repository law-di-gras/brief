"""Provider replies. Stored in our own database, never written to Clio.

Safety limits:
- a token can only answer requests that are on its own approved snapshot
- only the fields that request offers are accepted, dates must be real dates
- text is length-capped and stored as plain text (the frontend never renders it as HTML)
- the pipeline treats reply text as untrusted third-party text
"""
import re
from datetime import date

from backend import db
from backend.product import deterministic as det
from backend.product import provider

MAX_LEN = 500


class ReplyError(ValueError):
    pass


def clean(s):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(s or "")).strip()
    return s[:MAX_LEN]


def submit(token, request_ref, fields=None, note=""):
    share = provider.get_share(token)
    if not share or not share["live"]:
        raise ReplyError("This link is no longer active.")
    reqs = {r["ref"]: r for r in share["snapshot"].get("sections", {}).get("requests", [])}
    req = reqs.get(request_ref)
    if not req:
        raise ReplyError("That request is not on this page.")
    allowed = {f["name"]: f for f in req["fields"]}
    note = clean(note or (fields or {}).get("note"))
    rows = []
    for name, value in (fields or {}).items():
        value = clean(value)
        if name == "note" or not value:
            continue
        if name not in allowed:
            raise ReplyError("Unknown field.")
        if allowed[name]["type"] == "date":
            try:
                value = date.fromisoformat(value).isoformat()
            except ValueError:
                raise ReplyError(f"{allowed[name]['label']} must be a date.")
        rows.append((name, value))
    if not rows and not note:
        raise ReplyError("Nothing to send.")
    if not rows:
        rows = [("note", note)]
    stamp = provider.now()
    ids = [db.x("INSERT INTO provider_replies(token,provider_contact_id,request_ref,field,value,note,created_at,status)"
                " VALUES (?,?,?,?,?,?,?, 'new')",
                (token, share["provider_contact_id"], request_ref, name, value, note if name != "note" else "", stamp))
           for name, value in rows]
    return {"ok": True, "ids": ids, "matter_id": share["matter_id"], "created_at": stamp}


def inbox(matter_id):
    people = det.contacts(matter_id)
    labels = {}
    for cid in people:
        for r in det.open_requests(cid):
            labels[r["ref"]] = r["what"]
    rows = db.q("SELECT r.* FROM provider_replies r JOIN shares s ON s.token = r.token WHERE s.matter_id=?"
                " ORDER BY r.id DESC", (str(matter_id),))
    for r in rows:
        r.pop("token")
        r["provider"] = people.get(r["provider_contact_id"], {}).get("name")
        r["request"] = labels.get(r["request_ref"])
        r["source_id"] = f"portal:{r['id']}"
    return rows


def acknowledge(matter_id):
    db.x("UPDATE provider_replies SET status='seen' WHERE status='new' AND token IN"
         " (SELECT token FROM shares WHERE matter_id=?)", (str(matter_id),))
    return {"ok": True}
