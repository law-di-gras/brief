"""Read-only Clio sync: every record becomes one row in `items`, with a content hash.

Only items whose hash changed go forward to extraction.
"""
import hashlib
import json
import logging

from backend import db
from backend.pipeline import docs

log = logging.getLogger(__name__)

# Clio returns minimal data unless fields= is passed, so every call names its fields.
FIELDS = {
    "matter": "id,display_number,description,status,open_date,close_date,statute_of_limitations,"
              "client{id,name,type},matter_stage{id,name},practice_area{id,name},"
              "custom_field_values{id,field_name,value},updated_at",
    "relationships": "id,description,contact{id,name,type}",
    "notes": "id,subject,detail,date,created_at,updated_at",
    "communications": "id,type,subject,body,date,senders{id,name,type},receivers{id,name,type},created_at,updated_at",
    "tasks": "id,name,description,status,priority,due_at,completed_at,assignee{id,name,type},created_at,updated_at",
    "calendar_entries": "id,summary,description,location,start_at,end_at,all_day,created_at,updated_at",
    "activities": "id,type,date,quantity,price,total,note,created_at,updated_at",
    "documents": "id,name,received_at,content_type,parent{id,name},latest_document_version{uuid,size},created_at,updated_at",
}


def _d(value) -> str | None:
    """Business date as YYYY-MM-DD."""
    if not value:
        return None
    return str(value)[:10]


def _person(p, role=None) -> dict | None:
    """{"id": "contact:<id>", "name": ..., "role": ...}, the shape the product side reads."""
    if not p or p.get("id") is None:
        return None
    kind = "user" if p.get("type") == "User" else "contact"
    return {"id": f"{kind}:{p['id']}", "name": p.get("name"), "role": role}


def _names(people) -> str:
    return ", ".join(p.get("name") or (_person(p) or {}).get("id") or "?" for p in people or [])


def content_hash(item: dict) -> str:
    payload = json.dumps([item["title"], item["text"], item["item_date"], item["people"]], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---- normalizers: Clio record -> {item_id, source, clio_type, title, text, item_date, people, raw} ----

def norm_matter(m: dict) -> dict:
    lines = [
        f"Matter {m.get('display_number') or m['id']}: {m.get('description') or ''}",
        f"Status: {m.get('status')}",
    ]
    if m.get("matter_stage"):
        lines.append(f"Stage: {m['matter_stage'].get('name')}")
    if m.get("practice_area"):
        lines.append(f"Practice area: {m['practice_area'].get('name')}")
    if m.get("client"):
        lines.append(f"Client: {m['client'].get('name')}")
    lines.append(f"Open date: {m.get('open_date')}")
    sol = m.get("statute_of_limitations")
    if isinstance(sol, dict):
        sol = sol.get("due_at") or sol.get("name")
    if sol:
        lines.append(f"Statute of limitations: {sol}")
    for cf in m.get("custom_field_values") or []:
        lines.append(f"{cf.get('field_name')}: {cf.get('value')}")
    return dict(
        item_id=f"matter:{m['id']}", source="clio", clio_type="matter", clio_id=str(m["id"]),
        title="Matter details and custom fields", text="\n".join(lines), item_date=_d(m.get("open_date")),
        people=[p for p in [_person(m.get("client"), "client")] if p], raw=m,
    )


def norm_relationship(r: dict) -> dict:
    """A roster entry. Product code builds its contact list from these (raw = the Clio record)."""
    c = r.get("contact") or {}
    return dict(
        item_id=f"relationship:{r['id']}", source="clio", clio_type="relationship", clio_id=str(r["id"]),
        title=c.get("name") or "Contact", text=r.get("description") or "", item_date=None,
        people=[p for p in [_person(c, r.get("description") or "related")] if p], raw=r,
    )


def norm_note(n: dict) -> dict:
    return dict(
        item_id=f"note:{n['id']}", source="clio", clio_type="note", clio_id=str(n["id"]),
        title=n.get("subject") or "Note", text=f"Note dated {n.get('date')}: {n.get('subject') or ''}\n\n{n.get('detail') or ''}",
        item_date=_d(n.get("date") or n.get("created_at")), people=[], raw=n,
    )


def norm_comm(c: dict) -> dict:
    senders, receivers = c.get("senders") or [], c.get("receivers") or []
    kind = (c.get("type") or "Communication").replace("Communication", "").strip() or "Communication"
    text = (f"{kind} dated {c.get('date')}\nFrom: {_names(senders)}\nTo: {_names(receivers)}\n"
            f"Subject: {c.get('subject') or ''}\n\n{c.get('body') or ''}")
    return dict(
        item_id=f"comm:{c['id']}", source="clio", clio_type="communication", clio_id=str(c["id"]),
        title=c.get("subject") or kind, text=text, item_date=_d(c.get("date") or c.get("created_at")),
        people=[p for p in [_person(s, "sender") for s in senders] + [_person(r, "receiver") for r in receivers] if p], raw=c,
    )


def norm_task(t: dict) -> dict:
    text = (f"Task: {t.get('name')}\nStatus: {t.get('status')}\nDue: {_d(t.get('due_at'))}\n"
            + (f"Completed: {_d(t.get('completed_at'))}\n" if t.get("completed_at") else "")
            + f"\n{t.get('description') or ''}")
    return dict(
        item_id=f"task:{t['id']}", source="clio", clio_type="task", clio_id=str(t["id"]),
        title=t.get("name") or "Task", text=text, item_date=_d(t.get("due_at") or t.get("created_at")),
        people=[p for p in [_person(t.get("assignee"), "assignee")] if p], raw=t,
    )


def norm_event(e: dict) -> dict:
    text = (f"Calendar entry: {e.get('summary')}\nStarts: {e.get('start_at')}\nEnds: {e.get('end_at')}\n"
            + (f"Location: {e['location']}\n" if e.get("location") else "")
            + f"\n{e.get('description') or ''}")
    return dict(
        item_id=f"event:{e['id']}", source="clio", clio_type="calendar_entry", clio_id=str(e["id"]),
        title=e.get("summary") or "Calendar entry", text=text, item_date=_d(e.get("start_at")), people=[], raw=e,
    )


def norm_expense(a: dict) -> dict:
    total = a.get("total")
    if total is None:
        total = float(a.get("price") or 0) * float(a.get("quantity") or 1)
    text = f"Expense dated {a.get('date')}: ${float(total):,.2f}\n\n{a.get('note') or ''}"
    return dict(
        item_id=f"expense:{a['id']}", source="clio", clio_type="expense", clio_id=str(a["id"]),
        title=(a.get("note") or "Expense").split("\n")[0][:120], text=text, item_date=_d(a.get("date")),
        people=[], raw=a,
    )


# ---- storage ------------------------------------------------------------------

def upsert_item(conn, matter_id, item: dict) -> bool:
    """Insert or update one item. Returns True when its content hash changed."""
    h = content_hash(item)
    now = db.now_iso()
    row = conn.execute("SELECT hash FROM items WHERE item_id=?", (item["item_id"],)).fetchone()
    if row and row["hash"] == h:
        conn.execute("UPDATE items SET last_synced_at=? WHERE item_id=?", (now, item["item_id"]))
        return False
    conn.execute(
        """INSERT INTO items(item_id, source, clio_type, clio_id, title, text, item_date,
                             people_json, raw_json, hash, first_seen_at, last_synced_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(item_id) DO UPDATE SET title=excluded.title, text=excluded.text,
             item_date=excluded.item_date, people_json=excluded.people_json, raw_json=excluded.raw_json,
             hash=excluded.hash, last_synced_at=excluded.last_synced_at""",
        (item["item_id"], item["source"], item.get("clio_type"), item.get("clio_id"),
         item.get("title"), item["text"], item.get("item_date"), json.dumps(item.get("people") or []),
         json.dumps(item.get("raw"), default=str) if item.get("raw") is not None else None, h, now, now),
    )
    return True


def delete_items(conn, item_ids) -> None:
    from backend.pipeline.extract import delete_facts_for_items
    item_ids = list(item_ids)
    if not item_ids:
        return
    delete_facts_for_items(conn, item_ids)
    conn.executemany("DELETE FROM items WHERE item_id=?", [(i,) for i in item_ids])


def build_roster(matter: dict, relationships: list, user: dict | None) -> list[dict]:
    roster = []
    if matter.get("client"):
        c = matter["client"]
        roster.append({"id": f"contact:{c['id']}", "name": c.get("name"), "role": "Client", "type": c.get("type")})
    if user:
        roster.append({"id": f"user:{user['id']}", "name": user.get("name"), "role": "Firm user", "type": "User"})
    for r in relationships:
        c = r.get("contact") or {}
        if c.get("id") is None:
            continue
        roster.append({"id": f"contact:{c['id']}", "name": c.get("name"),
                       "role": r.get("description") or "Related contact", "type": c.get("type")})
    return roster


def sync(conn, clio, matter_id, full: bool = False) -> list[str]:
    """Pull the matter from Clio (GET only). Returns the item_ids whose content changed."""
    matter_id = str(matter_id)
    started = db.now_iso()
    since = None if full else db.get_meta(conn, matter_id, "clio_synced_at")
    q = {"matter_id": matter_id}
    if since:
        q["updated_since"] = since

    matter = clio.get(f"/matters/{matter_id}.json", {"fields": FIELDS["matter"]})["data"]
    relationships = clio.get("/relationships.json", {"matter_id": matter_id, "fields": FIELDS["relationships"]})["data"]
    try:
        user = clio.get("/users/who_am_i.json", {"fields": "id,name"})["data"]
    except Exception:  # noqa: BLE001 - roster still works without the firm user
        user = None
    db.set_meta(conn, matter_id, "matter", matter)
    db.set_meta(conn, matter_id, "roster", build_roster(matter, relationships, user))

    items = [norm_matter(matter)] + [norm_relationship(r) for r in relationships]
    for rec in clio.get("/notes.json", {**q, "type": "Matter", "fields": FIELDS["notes"]})["data"]:
        items.append(norm_note(rec))
    for rec in clio.get("/communications.json", {**q, "fields": FIELDS["communications"]})["data"]:
        items.append(norm_comm(rec))
    for rec in clio.get("/tasks.json", {**q, "fields": FIELDS["tasks"]})["data"]:
        items.append(norm_task(rec))
    for rec in clio.get("/calendar_entries.json", {**q, "fields": FIELDS["calendar_entries"]})["data"]:
        items.append(norm_event(rec))
    for rec in clio.get("/activities.json", {**q, "type": "ExpenseEntry", "fields": FIELDS["activities"]})["data"]:
        if rec.get("type", "ExpenseEntry") == "ExpenseEntry":
            items.append(norm_expense(rec))

    changed = [it["item_id"] for it in items if upsert_item(conn, matter_id, it)]

    documents = clio.get("/documents.json", {**q, "fields": FIELDS["documents"]})["data"]
    changed += docs.process_documents(conn, clio, matter_id, documents)

    if not since:
        # Full sync: anything from Clio we did not see this time was deleted there.
        seen = {it["item_id"] for it in items}
        seen_docs = {str(d["id"]) for d in documents}
        stale = []
        for row in conn.execute("SELECT item_id, clio_type, clio_id FROM items WHERE source='clio'"):
            if row["clio_type"] == "document":
                if row["clio_id"] not in seen_docs:
                    stale.append(row["item_id"])
            elif row["item_id"] not in seen:
                stale.append(row["item_id"])
        if stale:
            log.info("removing %d items deleted in Clio", len(stale))
            delete_items(conn, stale)
            changed += stale

    db.set_meta(conn, matter_id, "clio_synced_at", started)
    db.set_meta(conn, matter_id, "last_activity_date",
                conn.execute("SELECT MAX(item_date) d FROM items WHERE item_date<=date('now')").fetchone()["d"])
    conn.commit()
    log.info("sync: %d items, %d changed", len(items), len(changed))
    return changed
