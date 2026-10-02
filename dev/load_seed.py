"""Load a Clio-shaped JSON export into `items` so B can build without OAuth.

    python dev/load_seed.py path/to/seed.json [--facts path/to/facts.json] [--reset]

The seed is expected to look like Clio API responses grouped by resource
(matter, relationships, notes, communications, tasks, calendar_entries,
activities, documents). Each value may be a list or {"data": [...]}.
Records without an id get a fake sequential one.

Facts default to dev/fixtures/facts.json (A's fixture) and fall back to
dev/fixtures/demo_facts.json.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import db  # noqa: E402

FIX = ROOT / "dev" / "fixtures"


def rows(seed, *keys):
    for k in keys:
        v = seed.get(k)
        if isinstance(v, dict) and "data" in v:
            v = v["data"]
        if isinstance(v, dict):
            v = [v]
        if v:
            return v
    return []


def person(p, role):
    if not isinstance(p, dict):
        return None
    c = p.get("contact") if isinstance(p.get("contact"), dict) else p
    if c.get("id") is None and not c.get("name"):
        return None
    kind = "user" if (c.get("type") or p.get("type")) == "User" else "contact"
    return {"id": f"{kind}:{c.get('id')}", "name": c.get("name"), "role": role}


def people(rec, spec):
    out = []
    for key, role in spec:
        v = rec.get(key)
        for p in v if isinstance(v, list) else [v]:
            pp = person(p, role)
            if pp:
                out.append(pp)
    return out


def first(rec, *keys):
    for k in keys:
        if rec.get(k):
            return rec[k]
    return ""


# resource keys, id prefix, clio_type, title keys, text keys, date keys, people spec
SPEC = [
    (("notes",), "note", "note", ("subject",), ("detail", "detail_text_type", "body"), ("date", "created_at"), []),
    (("communications",), "comm", "communication", ("subject",), ("body", "detail"), ("date", "received_at", "created_at"),
     [("senders", "sender"), ("receivers", "receiver")]),
    (("tasks",), "task", "task", ("name",), ("description",), ("due_at", "created_at"), [("assignee", "assignee")]),
    (("calendar_entries", "calendar"), "cal", "calendar_entry", ("summary", "name"), ("description", "location"),
     ("start_at",), [("attendees", "attendee")]),
    (("activities", "expenses"), "expense", "expense", ("note", "description"), ("note", "description"), ("date",), []),
    (("documents",), "doc", "document", ("name",), ("name",), ("received_at", "created_at"), []),
]


def matter_text(m):
    lines = [m.get("description") or ""]
    for cf in m.get("custom_field_values") or []:
        name = cf.get("field_name") or (cf.get("custom_field") or {}).get("name")
        if name:
            lines.append(f"{name}: {cf.get('value')}")
    return "\n".join(lines)


def normalize(seed):
    out = []
    for i, m in enumerate(rows(seed, "matter", "matters"), 1):
        mid = m.get("id") or i
        out.append((f"matter:{mid}", "matter", mid, m.get("display_number") or "Matter", matter_text(m),
                    m.get("open_date"), people(m, [("client", "client")]), m))
    for i, r in enumerate(rows(seed, "relationships"), 1):
        rid = r.get("id") or i
        c = r.get("contact") or {}
        out.append((f"relationship:{rid}", "relationship", rid, c.get("name") or "", r.get("description") or "",
                    None, people(r, [("contact", r.get("description") or "related")]), r))
    for keys, prefix, ctype, tk, xk, dk, pspec in SPEC:
        for i, r in enumerate(rows(seed, *keys), 1):
            if ctype == "expense" and r.get("type") not in (None, "ExpenseEntry"):
                continue
            rid = r.get("id") or i
            text = first(r, *xk)
            if ctype == "document":
                text = f"[Document on file: {r.get('name')}. Text not loaded by the seed loader.]"
            out.append((f"{prefix}:{rid}", ctype, rid, first(r, *tk) or ctype, text, first(r, *dk) or None,
                        people(r, pspec), r))
    return out


def load_items(conn, seed):
    now = datetime.now(timezone.utc).isoformat()
    items = normalize(seed)
    for item_id, ctype, cid, title, text, date, ppl, raw in items:
        h = hashlib.sha256(json.dumps([title, text, date], sort_keys=True).encode()).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO items(item_id, source, clio_type, clio_id, title, text, item_date, people_json,"
            " hash, first_seen_at, last_synced_at, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, "clio", ctype, str(cid), title, text, date, json.dumps(ppl), h, now, now, json.dumps(raw)))
    return len(items)


def load_facts(conn, fx, matter_id):
    for t in ("facts", "dependencies", "conflicts", "issues", "editions"):
        conn.execute(f"DELETE FROM {t}")
    for f in fx.get("facts", []):
        conn.execute(
            "INSERT INTO facts(id,text,category,event_date,entities_json,source_ids_json,evidence,audience,importance,"
            "is_open_issue,run_id) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
            (f.get("id"), f["text"], f.get("category"), f.get("event_date"), json.dumps(f.get("entities", [])),
             json.dumps(f.get("source_ids", [])), f.get("evidence"), f.get("audience", "internal"),
             f.get("importance", 3), int(bool(f.get("is_open_issue")))))
    for d in fx.get("dependencies", []):
        conn.execute(
            "INSERT INTO dependencies(id,blocked,waiting_on,holder,node_blocked,node_waiting,source_ids_json,evidence)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (d.get("id"), d["blocked"], d["waiting_on"], d.get("holder", "unknown"), d.get("node_blocked"),
             d.get("node_waiting"), json.dumps(d.get("source_ids", [])), d.get("evidence")))
    for c in fx.get("conflicts", []):
        ids = sorted(c["fact_ids"])
        conn.execute(
            "INSERT INTO conflicts(id,fingerprint,fact_ids_json,topic,explanation,severity,kpi_affected,status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (c.get("id"), c.get("fingerprint") or "-".join(map(str, ids)), json.dumps(ids), c.get("topic"),
             c.get("explanation"), c.get("severity"), c.get("kpi_affected"), c.get("status", "open")))
    for i in fx.get("issues", []):
        conn.execute(
            "INSERT INTO issues(id,topic,fact_ids_json,first_flagged,last_mentioned,mentions,resolved_by_fact)"
            " VALUES (?,?,?,?,?,?,?)",
            (i.get("id"), i.get("topic"), json.dumps(i.get("fact_ids", [])), i.get("first_flagged"),
             i.get("last_mentioned"), i.get("mentions", 1), i.get("resolved_by_fact")))
    ed = fx.get("edition")
    if ed:
        conn.execute("INSERT INTO editions(cache_key,matter_id,headline_json,lead_json,created_at) VALUES (?,?,?,?,?)",
                     ("fixture", str(matter_id), json.dumps(ed.get("headline")), json.dumps(ed.get("lead", [])),
                      datetime.now(timezone.utc).isoformat()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", nargs="?", default=str(FIX / "demo_seed.json"))
    ap.add_argument("--facts")
    ap.add_argument("--no-facts", action="store_true")
    ap.add_argument("--reset", action="store_true", help="also clear visits, shares, views and replies")
    a = ap.parse_args()

    seed = json.loads(Path(a.seed).read_text())
    conn = db.connect()
    conn.execute("DELETE FROM items WHERE source = 'clio'")
    if a.reset:
        for t in ("visits", "shares", "share_views", "provider_replies"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM items")
    n = load_items(conn, seed)
    m = conn.execute("SELECT clio_id FROM items WHERE clio_type='matter' LIMIT 1").fetchone()
    matter_id = m["clio_id"] if m else "0"
    msg = f"{n} items loaded into {db.db_path()} (matter {matter_id})"
    if not a.no_facts:
        fp = Path(a.facts) if a.facts else next((p for p in (FIX / "facts.json", FIX / "demo_facts.json") if p.exists()), None)
        if fp:
            load_facts(conn, json.loads(fp.read_text()), matter_id)
            msg += f", facts from {fp.name}"
    conn.commit()
    conn.close()
    print(msg)


if __name__ == "__main__":
    main()
