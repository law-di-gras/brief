"""Attorney edition: the AI- and analysis-backed parts of the front page.

build_edition(matter_id, since) is the contract function B calls from /edition. B's deterministic
sections (masthead, KPIs, still waiting, coming up, ...) are built in product/deterministic.py and
merged by the route.
"""
import hashlib
import json
import logging
from datetime import date

from backend import db
from backend.pipeline import llm, validate
from backend.pipeline.analyze import fact_date, item_map, load_facts, said_date
from backend.pipeline.graph import build_graph

log = logging.getLogger(__name__)

MAX_LEAD = 4

SYSTEM = """You write the front page of a legal matter for the lawyers working it, like a newspaper.
You get the matter's facts (each with an id), its open conflicts, its open issues and the step that is
holding the case up.

Write:
- headline: at most 14 words, the single most important thing about the case right now.
- lead: up to 4 sentences, most important first. Say what changed since the reader's last visit if
  anything did, what is holding the case up and who holds it, and the case value and coverage.
  The conflicts are shown in their own section below the lead: mention at most one, in a few words.

Every sentence must rest on the listed facts: give the ids of the facts it relies on. Use only numbers,
amounts and dates that appear in those facts. Plain words, no adjectives of praise or alarm, no advice.
Answer by calling the record_front_page tool."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "object", "properties": {
            "text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["text", "fact_ids"]},
        "lead": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["text", "fact_ids"]}},
    },
    "required": ["headline", "lead"],
}


def facts_version(conn, matter_id) -> str:
    row = conn.execute(
        "SELECT COUNT(*) n, COALESCE(MAX(id),0) mx, COALESCE(SUM(id),0) s FROM facts").fetchone()
    extra = conn.execute(
        "SELECT (SELECT group_concat(fingerprint||status) FROM conflicts) c, "
        "(SELECT group_concat(node_id||COALESCE(resolved_by_fact,'')) FROM blocker_nodes WHERE matter_id=?) b",
        (str(matter_id),)).fetchone()
    return hashlib.sha256(f"{row['n']}|{row['mx']}|{row['s']}|{extra['c']}|{extra['b']}".encode()).hexdigest()[:16]


def _cited(sentence: dict, facts: dict, items: dict) -> dict | None:
    """Keep a generated sentence only if its fact ids are real and its numbers are in the sources."""
    fids = [i for i in sentence.get("fact_ids") or [] if i in facts]
    text = (sentence.get("text") or "").strip()
    if not text or not fids:
        return None
    sids = sorted({s for i in fids for s in facts[i]["source_ids"]})
    src = [items[s]["text"] for s in sids if s in items]
    dates = [items[s]["item_date"] for s in sids if s in items]
    if not validate.check_sentence(text, src, dates):
        log.info("dropped generated sentence (unsourced number): %s", text)
        return None
    return {"text": text, "fact_ids": fids, "source_ids": sids}


def _fallback(facts, graph, conflicts) -> tuple[dict, list]:
    """No-AI front page from validated facts only.

    Headline: the most important fact behind the root blocker. Lead: the most important remaining
    facts, one per category, leaving out facts the corrections section already shows.
    """
    def cite(f):
        return {"text": f["text"], "fact_ids": [f["id"]], "source_ids": f["source_ids"]}

    ranked = sorted(facts.values(), key=lambda f: (-f["importance"], -(f["id"])))
    if not ranked:
        return {"text": "No facts extracted yet", "fact_ids": [], "source_ids": []}, []
    root = graph.get("root")
    root_sources = set(root["source_ids"]) if root else set()
    head = next((f for f in ranked if set(f["source_ids"]) & root_sources), ranked[0])
    shown = {i for c in conflicts for i in c["fact_ids"]} | {head["id"]}
    lead, cats = [], set()
    for f in ranked:
        if f["id"] in shown or f["category"] in cats:
            continue
        lead.append(cite(f))
        cats.add(f["category"])
        if len(lead) == MAX_LEAD - 1:
            break
    return cite(head), lead


def write_front_page(conn, matter_id, since, facts, items, graph, conflicts, issues) -> tuple[dict, list]:
    key = hashlib.sha256(f"{matter_id}|{facts_version(conn, matter_id)}|{(since or '')[:10]}".encode()).hexdigest()
    row = conn.execute("SELECT headline_json, lead_json FROM editions WHERE cache_key=?", (key,)).fetchone()
    if row:
        return json.loads(row["headline_json"]), json.loads(row["lead_json"])
    if not llm.available() or not facts:
        return _fallback(facts, graph, conflicts)

    since_d = (since or "")[:10]
    in_conflict = {i for c in conflicts for i in c["fact_ids"]}
    in_issue = {i for it in issues for i in it["fact_ids"]}
    root_sources = set(graph["root"]["source_ids"]) if graph.get("root") else set()
    chosen = [f for f in facts.values() if f["importance"] >= 4 or f["id"] in in_conflict or f["id"] in in_issue
              or set(f["source_ids"]) & root_sources or (since_d and (said_date(f, items) or "") > since_d)]
    chosen = sorted(chosen, key=lambda f: (-f["importance"], said_date(f, items) or ""))[:80]

    def line(f):
        new = " NEW" if since_d and (said_date(f, items) or "") > since_d else ""
        return f"[{f['id']}]{new} ({f['category']}, {fact_date(f, items) or 'undated'}) {f['text']}"

    root = graph.get("root")
    prompt = [f"Today is {date.today().isoformat()}. Reader's last visit: {since_d or 'never'}.", "", "Facts:"]
    prompt += [line(f) for f in chosen]
    prompt += ["", "Open conflicts:"] + [f"- {c['topic']}: facts {c['fact_ids']}" for c in conflicts]
    prompt += ["", "Open issues:"] + [f"- {i['topic']} (open {i['days_open']} days): facts {i['fact_ids']}"
                                      for i in issues if not i["resolved_by_fact"]]
    if root:
        prompt += ["", f"Holding the case up: {root['label']} (held by {', '.join(root['holders'])}"
                       f"{', disputed' if root['disputed'] else ''}); it blocks: {', '.join(root['dependents'])}"]
    try:
        out = llm.call_json(llm.SONNET, SYSTEM, "\n".join(prompt), "record_front_page",
                            "Record the headline and lead.", SCHEMA, max_tokens=4000, effort="medium")
    except Exception as e:  # noqa: BLE001
        log.error("front page generation failed: %s", e)
        return _fallback(facts, graph, conflicts)

    headline = _cited(out.get("headline") or {}, facts, items)
    lead = [s for s in (_cited(x, facts, items) for x in (out.get("lead") or [])[:MAX_LEAD]) if s]
    fb_head, fb_lead = _fallback(facts, graph, conflicts)
    headline = headline or fb_head
    lead = lead or fb_lead
    conn.execute("INSERT OR REPLACE INTO editions(cache_key, matter_id, headline_json, lead_json, created_at) "
                 "VALUES (?,?,?,?,?)", (key, str(matter_id), json.dumps(headline), json.dumps(lead), db.now_iso()))
    conn.commit()
    return headline, lead


def build_timeline(facts, items, conflicts, issues, today: date) -> list[dict]:
    """Key dated facts from incident to today; conflicts and open issues become red markers."""
    conflict_of = {i: c["id"] for c in conflicts for i in c["fact_ids"]}
    issue_of = {i: it["id"] for it in issues if not it["resolved_by_fact"] for i in it["fact_ids"]}
    out = []
    for f in facts.values():
        if not f["event_date"] or f["importance"] < 3:
            continue
        marker = "conflict" if f["id"] in conflict_of else "issue" if f["id"] in issue_of else None
        out.append({"date": f["event_date"], "fact_id": f["id"], "text": f["text"], "category": f["category"],
                    "importance": f["importance"], "source_ids": f["source_ids"], "marker": marker,
                    "conflict_id": conflict_of.get(f["id"]), "issue_id": issue_of.get(f["id"]),
                    "future": f["event_date"] > today.isoformat()})
    out.sort(key=lambda x: (x["date"], -x["importance"]))
    return out


def _with_evidence(sentence: dict, facts: dict) -> dict:
    """The product UI highlights `evidence` when a sentence is clicked."""
    ev = [facts[i]["evidence"] for i in sentence.get("fact_ids", []) if i in facts]
    return {**sentence, "evidence": ev[0] if ev else None}


def product_blocker(conn, matter_id, graph: dict, facts: dict, items: dict) -> dict | None:
    """The blocker in the shape product/bridge.py and BlockerCard.jsx expect.

    When no unresolved root remains but a provider reply cleared a node, return that node as
    resolved so the page can show "Root blocker cleared".
    """
    roster = {r["id"]: r.get("name") for r in db.get_meta(conn, matter_id, "roster", [])}
    root = graph.get("root")
    if root:
        holders = [{"holder": h, "name": roster.get(h) or h, "quote": q["evidence"],
                    "source_ids": q["source_ids"], "date": q["date"]}
                   for h, quotes in root["quotes"].items() for q in quotes]
        pending_reply = any(
            i["source"] == "portal" and not conn.execute(
                "SELECT 1 FROM facts, json_each(facts.source_ids_json) s WHERE s.value=? LIMIT 1", (i["item_id"],)).fetchone()
            for i in items.values())
        return {"node": root["node_id"], "label": root["label"], "resolved": False, "disputed": root["disputed"],
                "holders": holders, "dependents": root["dependents"], "requests_sent": root["request_count"],
                "days_waiting": root["days_waiting"],
                "reply_received": pending_reply}
    cleared = []
    for n in graph["nodes"]:
        fid = n["resolved_by_fact"]
        if fid in facts and any(items.get(s, {}).get("source") == "portal" for s in facts[fid]["source_ids"]):
            cleared.append((said_date(facts[fid], items) or "", n))
    if cleared:
        n = max(cleared, key=lambda c: c[0])[1]
        return {"node": n["node_id"], "label": n["label"], "resolved": True, "disputed": False, "holders": [],
                "dependents": [], "requests_sent": 0, "reply_received": True,
                "resolved_by_fact": n["resolved_by_fact"]}
    return None


def build_edition(matter_id, since: str | None = None, conn=None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    try:
        matter_id = str(matter_id)
        today = date.today()
        facts = load_facts(conn, matter_id)
        items = item_map(conn, matter_id)

        conflicts = []
        for r in conn.execute("SELECT * FROM conflicts ORDER BY "
                              "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id"):
            c = dict(r)
            c["fact_ids"] = json.loads(c.pop("fact_ids_json"))
            c["facts"] = [facts[i] for i in c["fact_ids"] if i in facts]
            c["source_ids"] = sorted({s for f in c["facts"] for s in f["source_ids"]})
            if c["status"] == "open":
                conflicts.append(c)

        issues = []
        for r in conn.execute("SELECT * FROM issues ORDER BY first_flagged"):
            it = dict(r)
            it["fact_ids"] = json.loads(it.pop("fact_ids_json"))
            it["facts"] = [facts[i] for i in it["fact_ids"] if i in facts]
            it["source_ids"] = sorted({s for f in it["facts"] for s in f["source_ids"]})
            it["days_open"] = (today - date.fromisoformat(it["first_flagged"])).days if it["first_flagged"] else None
            it["resolved_by"] = facts.get(it["resolved_by_fact"]) if it["resolved_by_fact"] else None
            issues.append(it)

        graph = build_graph(conn, matter_id, today)
        headline, lead = write_front_page(conn, matter_id, since, facts, items, graph, conflicts, issues)

        since_d = (since or "")[:10]
        updates = []
        if since_d:
            seen_docs = set()
            for r in conn.execute(
                    "SELECT i.item_id, i.title, i.item_date, i.source, i.clio_type, i.clio_id, d.name doc_name "
                    "FROM items i LEFT JOIN documents d ON i.clio_type='document' AND d.doc_id=i.clio_id "
                    "WHERE i.item_date>? AND i.item_date<=? AND i.clio_type NOT IN ('matter','relationship') "
                    "ORDER BY i.item_date DESC, i.item_id",
                    (since_d, today.isoformat())):
                if r["clio_type"] == "document":   # one update per document, not per page
                    if r["clio_id"] in seen_docs:
                        continue
                    seen_docs.add(r["clio_id"])
                updates.append(dict(item_id=r["item_id"], title=r["doc_name"] or r["title"], item_date=r["item_date"],
                                    source=r["source"], clio_type=r["clio_type"]))

        run = conn.execute("SELECT * FROM runs WHERE matter_id=? ORDER BY id DESC LIMIT 1", (matter_id,)).fetchone()
        return {
            "matter_id": matter_id,
            "generated_at": db.now_iso(),
            "since": since,
            "facts_version": facts_version(conn, matter_id),
            "headline": _with_evidence(headline, facts),
            "lead": [_with_evidence(s, facts) for s in lead],
            "timeline": build_timeline(facts, items, conflicts, issues, today),
            "blocker": product_blocker(conn, matter_id, graph, facts, items),
            "blocker_detail": graph["root"],
            "graph": {"nodes": graph["nodes"], "edges": graph["edges"]},
            "conflicts": conflicts,
            "issues": issues,
            "updates_since": {"count": len(updates), "items": updates},
            "client_photo": db.get_meta(conn, matter_id, "client_photo"),
            "run": dict(run) if run else None,
        }
    finally:
        if own:
            conn.close()
