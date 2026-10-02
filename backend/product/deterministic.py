"""Deterministic sections of the attorney edition. No model writes anything here.

Reads `items` (raw Clio records) and the pipeline tables. Writes nothing.
"""
import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend import db
from backend.product import ai

J = db.J
META = ("matter", "relationship")


def tz():
    return ZoneInfo(os.environ.get("FIRM_TZ", "America/Los_Angeles"))


def today():
    return datetime.now(tz()).date()


def local_date(s):
    """Business date in the firm's timezone. Clio datetimes are UTC."""
    if not s:
        return None
    s = str(s)
    try:
        if len(s) <= 10:
            return date.fromisoformat(s)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(tz()).date()
    except ValueError:
        return None


def iso(d):
    return d.isoformat() if d else None


def money(v):
    if v is None:
        return None
    m = re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(m)
    except ValueError:
        return None


# ---------- loaders ----------

def items(where="1=1", args=()):
    out = db.q(f"SELECT * FROM items WHERE {where}", args)
    for r in out:
        r["people"] = J(r.pop("people_json"), [])
        r["raw"] = J(r.pop("raw_json"), {}) or {}
    return out


def matter(matter_id):
    rows = items("clio_type='matter' AND clio_id=?", (str(matter_id),)) or items("clio_type='matter'")
    return rows[0] if rows else None


def facts():
    out = db.q("SELECT * FROM facts")
    for f in out:
        f["entities"] = J(f.pop("entities_json"), [])
        f["source_ids"] = J(f.pop("source_ids_json"), [])
    return out


def deps():
    out = db.q("SELECT * FROM dependencies")
    for d in out:
        d["source_ids"] = J(d.pop("source_ids_json"), [])
    return out


def open_conflicts():
    out = db.q("SELECT * FROM conflicts WHERE COALESCE(status,'open')='open'")
    for c in out:
        c["fact_ids"] = J(c.pop("fact_ids_json"), [])
    return out


def contacts(matter_id):
    """{contact_id: {name, description}} from the roster, plus the client."""
    out = {}
    for r in items("clio_type='relationship'"):
        c = r["raw"].get("contact") or {}
        if c.get("id") is not None:
            out[f"contact:{c['id']}"] = {"name": c.get("name") or r["title"], "description": r["raw"].get("description") or r["text"] or ""}
    m = matter(matter_id)
    cl = (m["raw"].get("client") if m else None) or {}
    if cl.get("id") is not None:
        out[f"contact:{cl['id']}"] = {"name": cl.get("name"), "description": "Client"}
    return out


def client_id(matter_id):
    m = matter(matter_id)
    cl = (m["raw"].get("client") if m else None) or {}
    return f"contact:{cl['id']}" if cl.get("id") is not None else None


def fact_brief(f):
    return {"id": f["id"], "text": f["text"], "event_date": f["event_date"], "category": f["category"],
            "source_ids": f["source_ids"], "evidence": f["evidence"]}


# ---------- sections ----------

def masthead(matter_id, since):
    m = matter(matter_id)
    raw = m["raw"] if m else {}
    sd = local_date(since)
    def is_new(i):
        if not sd:
            return False
        if i["source"] == "portal":
            return (local_date(i["first_seen_at"]) or date.min) >= sd
        d = local_date(i["item_date"])
        return bool(d) and sd < d <= today()

    changed = [i for i in items("clio_type NOT IN ('matter','relationship')") if is_new(i)]
    changed.sort(key=lambda i: i["item_date"] or "", reverse=True)
    return {
        "client": (raw.get("client") or {}).get("name"),
        "display_number": raw.get("display_number"),
        "description": raw.get("description"),
        "stage": (raw.get("matter_stage") or {}).get("name") or raw.get("status"),
        "status": raw.get("status"),
        "since": iso(sd),
        "updates_since": len(changed) if sd else None,
        "changes": [{"item_id": i["item_id"], "title": i["title"], "date": iso(local_date(i["item_date"])),
                     "type": i["clio_type"]} for i in changed[:8]] if sd else [],
    }


KPI_LABELS = {"case_value": "Case value", "coverage": "Coverage", "specials": "Specials", "lien": "Lien"}


def firm_spend():
    ex = items("clio_type='expense'")
    total = 0.0
    for e in ex:
        r = e["raw"]
        v = money(r.get("total"))
        if v is None and r.get("price") is not None:
            v = (money(r.get("price")) or 0) * (money(r.get("quantity")) or 1)
        total += v or 0
    return {"total": round(total, 2), "count": len(ex), "source_ids": [e["item_id"] for e in ex]}


def kpis(matter_id):
    m = matter(matter_id)
    cfs = []
    for cf in (m["raw"].get("custom_field_values") if m else None) or []:
        name = cf.get("field_name") or (cf.get("custom_field") or {}).get("name")
        if name:
            cfs.append((name, cf.get("value")))
    slots = ai.map_kpi_fields([n for n, _ in cfs])
    conflicts = {c["kpi_affected"]: c for c in open_conflicts() if c.get("kpi_affected")}
    out = []
    for slot, label in KPI_LABELS.items():
        hit = next(((n, v) for n, v in cfs if slots.get(n) == slot and v not in (None, "")), None)
        c = conflicts.get(slot)
        out.append({"slot": slot, "label": label, "field_name": hit[0] if hit else None,
                    "value": hit[1] if hit else None, "amount": money(hit[1]) if hit else None,
                    "source_ids": [m["item_id"]] if hit and m else [],
                    "conflict": {"id": c["id"], "topic": c["topic"], "explanation": c["explanation"]} if c else None})
    fs = firm_spend()
    out.append({"slot": "firm_spend", "label": "Firm spend", "field_name": f"{fs['count']} expenses",
                "value": fs["total"], "amount": fs["total"], "source_ids": fs["source_ids"], "conflict": None})
    return out


DATE_WORDS = ("date", "schedul", "appointment", "surgery", "procedure", "when")
SEND_WORDS = ("record", "bill", "ledger", "report", "send", "fax", "copy", "copies", "invoice", "statement", "itemiz")


def request_fields(text):
    """Reply fields come from the wording of the request itself."""
    s = text.lower()
    fields = []
    if any(w in s for w in DATE_WORDS):
        fields.append({"name": "date", "label": "Date", "type": "date"})
    if any(w in s for w in SEND_WORDS):
        fields.append({"name": "sent_on", "label": "Sent on", "type": "date"})
    fields.append({"name": "note", "label": "Short note", "type": "text"})
    return fields


def open_requests(contact_id, all_facts=None, all_deps=None):
    """What the firm is waiting on from one contact, with repeated asks grouped."""
    all_facts = facts() if all_facts is None else all_facts
    cdeps = [d for d in (deps() if all_deps is None else all_deps) if d["holder"] == contact_id]
    item_dates = {i["item_id"]: i["item_date"] for i in db.q("SELECT item_id, item_date FROM items")}
    groups = {}

    def key_of(d):
        return d.get("node_waiting") or d["waiting_on"].strip().lower()

    for f in all_facts:
        if f["category"] != "provider_request" or contact_id not in f["entities"]:
            continue
        hits = [d for d in cdeps if set(d["source_ids"]) & set(f["source_ids"]) or d["waiting_on"].lower() in f["text"].lower()]
        targets = [(key_of(d), d["waiting_on"]) for d in hits] or [(f["text"], f["text"])]
        for key, label in dict(targets).items():
            g = groups.setdefault(key, {"what": label, "asks": [], "source_ids": [], "texts": []})
            g["asks"].append(f["event_date"])
            g["source_ids"] += f["source_ids"]
            g["texts"].append(f["text"])
    for d in cdeps:
        g = groups.setdefault(key_of(d), {"what": d["waiting_on"], "asks": [], "source_ids": [], "texts": []})
        g["source_ids"] += d["source_ids"]
        g["texts"].append(d["waiting_on"])
        if not g["asks"]:
            g["dep_dates"] = g.get("dep_dates", []) + [item_dates.get(s) for s in d["source_ids"]]

    answered = {r["request_ref"] for r in db.q(
        "SELECT DISTINCT request_ref FROM provider_replies WHERE provider_contact_id=?", (contact_id,))}
    out = []
    for key, g in groups.items():
        dates = sorted(d for d in (local_date(a) for a in (g["asks"] or g.get("dep_dates", []))) if d)
        ref = hashlib.sha1(f"{contact_id}|{key}".encode()).hexdigest()[:12]
        what = g["what"][:1].upper() + g["what"][1:]
        out.append({"ref": ref, "node": key, "what": what, "first_asked": iso(dates[0]) if dates else None,
                    "last_asked": iso(dates[-1]) if dates else None, "times_asked": len(g["asks"]),
                    "source_ids": list(dict.fromkeys(g["source_ids"])),
                    "fields": request_fields(" ".join(g["texts"])), "answered": ref in answered})
    out.sort(key=lambda r: (r["answered"], -r["times_asked"], r["first_asked"] or "9"))
    return out


def last_heard_from(contact_id):
    ds = [local_date(i["item_date"]) for i in items("clio_type IN ('communication','provider_reply')")
          if any(p.get("id") == contact_id and p.get("role") == "sender" for p in i["people"])]
    ds += [local_date(r["created_at"]) for r in db.q(
        "SELECT created_at FROM provider_replies WHERE provider_contact_id=?", (contact_id,))]
    ds = [d for d in ds if d and d <= today()]
    return max(ds) if ds else None


def still_waiting(matter_id):
    fs, ds, people = facts(), deps(), contacts(matter_id)
    out = []
    for cid, c in people.items():
        reqs = [r for r in open_requests(cid, fs, ds) if not r["answered"]]
        if not reqs:
            continue
        heard = last_heard_from(cid)
        firsts = [r["first_asked"] for r in reqs if r["first_asked"]]
        ref_day = heard or (local_date(min(firsts)) if firsts else None)
        out.append({"contact_id": cid, "name": c["name"], "owes": reqs,
                    "requests_sent": sum(r["times_asked"] for r in reqs),
                    "last_heard": iso(heard), "days_silent": (today() - ref_day).days if ref_day else None})
    out.sort(key=lambda r: -(r["days_silent"] or 0))
    return out


def coming_up(matter_id, days=21):
    t = today()
    out = []
    for i in items("clio_type='task'"):
        status = str(i["raw"].get("status") or "pending").lower()
        d = local_date(i["item_date"])
        if status.startswith("complete") or not d:
            continue
        # Only pending tasks with a past due date are overdue. Past calendar entries never are.
        if d < t or d <= t + timedelta(days=days):
            out.append({"item_id": i["item_id"], "kind": "task", "title": i["title"], "date": iso(d),
                        "overdue": d < t, "days": (d - t).days})
    for i in items("clio_type='calendar_entry'"):
        d = local_date(i["item_date"])
        if d and t <= d <= t + timedelta(days=days):
            out.append({"item_id": i["item_id"], "kind": "event", "title": i["title"], "date": iso(d),
                        "overdue": False, "days": (d - t).days})
    out.sort(key=lambda r: (not r["overdue"], r["date"]))
    return out


def last_client_contact(matter_id):
    cid = client_id(matter_id)
    best = None
    for i in items("clio_type='communication'"):
        d = local_date(i["item_date"])
        if d and d <= today() and any(p.get("id") == cid for p in i["people"]) and (not best or d > best[0]):
            best = (d, i["title"], [i["item_id"]], None)
    for f in facts():
        d = local_date(f["event_date"])
        if f["category"] == "client_contact" and d and d <= today() and (not best or d > best[0]):
            best = (d, f["text"], f["source_ids"], f["evidence"])
    if not best:
        return None
    return {"date": iso(best[0]), "days_ago": (today() - best[0]).days, "title": best[1],
            "source_ids": best[2], "evidence": best[3]}


def timeline(matter_id, limit=14):
    flagged = {}
    for c in open_conflicts():
        for fid in c["fact_ids"]:
            flagged[fid] = "conflict"
    for i in db.q("SELECT * FROM issues WHERE resolved_by_fact IS NULL"):
        for fid in J(i["fact_ids_json"], []):
            flagged.setdefault(fid, "issue")
    fs = [f for f in facts() if local_date(f["event_date"]) and local_date(f["event_date"]) <= today()]
    for f in fs:
        if f["is_open_issue"]:
            flagged.setdefault(f["id"], "issue")
    fs.sort(key=lambda f: (f["id"] not in flagged, -(f["importance"] or 0)))
    picked = sorted(fs[:limit], key=lambda f: f["event_date"])
    m = matter(matter_id)
    return {"start": picked[0]["event_date"] if picked else (m["item_date"] if m else None), "today": iso(today()),
            "events": [dict(fact_brief(f), importance=f["importance"], marker=flagged.get(f["id"])) for f in picked]}


def corrections(matter_id):
    by_id = {f["id"]: f for f in facts()}
    conflicts = [{"id": c["id"], "topic": c["topic"], "explanation": c["explanation"], "severity": c["severity"],
                  "kpi_affected": c["kpi_affected"],
                  "facts": [fact_brief(by_id[i]) for i in c["fact_ids"] if i in by_id]} for c in open_conflicts()]
    issues = []
    for i in db.q("SELECT * FROM issues"):
        first = local_date(i["first_flagged"])
        issues.append({"id": i["id"], "topic": i["topic"], "first_flagged": i["first_flagged"],
                       "last_mentioned": i["last_mentioned"], "mentions": i["mentions"],
                       "days_open": (today() - first).days if first else None,
                       "resolved": i["resolved_by_fact"] is not None,
                       "facts": [fact_brief(by_id[f]) for f in J(i["fact_ids_json"], []) if f in by_id]})
    issues.sort(key=lambda i: (i["resolved"], -(i["days_open"] or 0)))
    return {"conflicts": conflicts, "issues": issues}


def source(item_id):
    rows = items("item_id=?", (item_id,))
    if not rows:
        return None
    i = rows[0]
    m = db.q("SELECT clio_id FROM items WHERE clio_type='matter' LIMIT 1")
    link = f"https://app.clio.com/nc/#/matters/{m[0]['clio_id']}" if m and i["source"] == "clio" else None
    return {"item_id": i["item_id"], "source": i["source"], "type": i["clio_type"], "title": i["title"],
            "text": i["text"], "date": iso(local_date(i["item_date"])), "people": i["people"], "clio_url": link}


def full_file(matter_id):
    out = [{"item_id": i["item_id"], "source": i["source"], "type": i["clio_type"], "title": i["title"],
            "text": (i["text"] or "")[:400], "date": iso(local_date(i["item_date"]))}
           for i in items("clio_type NOT IN ('matter','relationship')")]
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out
