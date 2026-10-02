"""Blocker graph. The model only maps free-text labels to canonical nodes (and spots resolutions);
Python builds the graph and picks the root blocker."""
import json
import logging
import re
from collections import defaultdict
from datetime import date

from backend import db
from backend.pipeline import llm
from backend.pipeline.analyze import item_map, load_facts, said_date

log = logging.getLogger(__name__)

SYSTEM = """You tidy a list of dependency labels from a legal matter ("X is waiting on Y").
Different labels often name the same step in different words. Group labels that mean the same
step into one node with a short snake_case node_id and a clear label (2-6 words).
Every input label must appear in exactly one node's aliases, copied exactly.

Then look at the recent facts. If a fact shows that a node's step has now happened (for example
the record arrived, the date was set, the payment was made), list it under resolutions with that
fact's id. Only resolve a node when the fact clearly says so.

Answer by calling the record_nodes tool."""

SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array", "items": {"type": "object", "properties": {
            "node_id": {"type": "string"},
            "label": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}},
        }, "required": ["node_id", "label", "aliases"]}},
        "resolutions": {"type": "array", "items": {"type": "object", "properties": {
            "node_id": {"type": "string"},
            "fact_id": {"type": "integer"},
        }, "required": ["node_id", "fact_id"]}},
    },
    "required": ["nodes", "resolutions"],
}

RESOLUTION_CATEGORIES = {"treatment", "provider_request", "procedure", "discovery", "client_contact",
                         "coverage", "lien", "damages"}


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:48] or "node"


def label_nodes(conn, matter_id) -> None:
    """Assign node_blocked / node_waiting on every dependency and refresh blocker_nodes."""
    matter_id = str(matter_id)
    deps = conn.execute("SELECT * FROM dependencies WHERE matter_id=?", (matter_id,)).fetchall()
    conn.execute("DELETE FROM blocker_nodes WHERE matter_id=?", (matter_id,))
    if not deps:
        conn.commit()
        return
    labels = sorted({d["blocked"] for d in deps} | {d["waiting_on"] for d in deps})
    facts = load_facts(conn, matter_id)
    items = item_map(conn, matter_id)
    alias_to_node, node_labels, resolutions = {}, {}, {}

    if llm.available():
        recent = sorted((f for f in facts.values() if f["category"] in RESOLUTION_CATEGORIES),
                        key=lambda f: said_date(f, items) or "", reverse=True)[:80]
        prompt = ("Labels:\n" + "\n".join(f"- {l}" for l in labels) + "\n\nRecent facts:\n" +
                  "\n".join(f"[{f['id']}] ({said_date(f, items)}) {f['text']}" for f in recent))
        try:
            out = llm.call_json(llm.SONNET, SYSTEM, prompt, "record_nodes", "Record canonical nodes.",
                                SCHEMA, max_tokens=8000, effort="low")
            for n in out.get("nodes") or []:
                nid = slug(n.get("node_id") or n.get("label") or "")
                for a in n.get("aliases") or []:
                    if a in labels and a not in alias_to_node:
                        alias_to_node[a] = nid
                        node_labels.setdefault(nid, n.get("label") or a)
            for r in out.get("resolutions") or []:
                if r.get("fact_id") in facts:
                    resolutions[slug(r.get("node_id") or "")] = r["fact_id"]
        except Exception as e:  # noqa: BLE001
            log.error("node labelling failed, falling back to exact labels: %s", e)

    for l in labels:  # unmapped labels become their own node
        if l not in alias_to_node:
            nid = slug(l)
            alias_to_node[l] = nid
            node_labels.setdefault(nid, l)

    for d in deps:
        conn.execute("UPDATE dependencies SET node_blocked=?, node_waiting=? WHERE id=?",
                     (alias_to_node[d["blocked"]], alias_to_node[d["waiting_on"]], d["id"]))

    # A resolution only counts if the fact was recorded no earlier than the latest request it answers.
    last_ask = defaultdict(str)
    for d in deps:
        for s in json.loads(d["source_ids_json"]):
            dt = (items.get(s) or {}).get("item_date") or ""
            nid = alias_to_node[d["waiting_on"]]
            last_ask[nid] = max(last_ask[nid], dt)
    for nid, label in node_labels.items():
        fid = resolutions.get(nid)
        if fid is not None and (said_date(facts[fid], items) or "") < last_ask[nid]:
            fid = None
        conn.execute("INSERT INTO blocker_nodes(matter_id, node_id, label, resolved_by_fact) VALUES (?,?,?,?)",
                     (matter_id, nid, label, fid))
    conn.commit()


def build_graph(conn, matter_id, today: date | None = None) -> dict:
    """Pure Python: edges, root blocker, chain, holders, disputed quotes. No model calls."""
    matter_id = str(matter_id)
    today = today or date.today()
    nodes = {r["node_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM blocker_nodes WHERE matter_id=?", (matter_id,))}
    deps = [dict(r) for r in conn.execute(
        "SELECT * FROM dependencies WHERE matter_id=? AND node_blocked IS NOT NULL", (matter_id,))]
    items = item_map(conn, matter_id)
    if not deps:
        return {"root": None, "nodes": [], "edges": []}

    resolved = {n for n, v in nodes.items() if v["resolved_by_fact"] is not None}
    waits_on = defaultdict(set)      # blocked -> {waiting}
    blocks = defaultdict(set)        # waiting -> {blocked}
    for d in deps:
        if d["node_blocked"] != d["node_waiting"]:
            waits_on[d["node_blocked"]].add(d["node_waiting"])
            blocks[d["node_waiting"]].add(d["node_blocked"])

    def dependents(n):
        seen, stack = set(), [n]
        while stack:
            for b in blocks[stack.pop()]:
                if b not in seen and b not in resolved and b != n:
                    seen.add(b)
                    stack.append(b)
        return seen

    def sources_for(n):
        return {s for d in deps if d["node_waiting"] == n for s in json.loads(d["source_ids_json"])}

    candidates = [n for n in blocks if n not in resolved]
    root = None
    if candidates:
        def rank(n):
            leaf = not (waits_on[n] - resolved)   # nothing unresolved behind it: the true bottleneck
            return (len(dependents(n)), leaf, len(sources_for(n)))
        root = max(candidates, key=rank)

    root_info = None
    if root:
        deps_on_root = [d for d in deps if d["node_waiting"] == root]
        holders = defaultdict(list)
        for d in deps_on_root:
            srcs = json.loads(d["source_ids_json"])
            holders[d["holder"]].append({
                "evidence": d["evidence"], "source_ids": srcs,
                "date": max((items.get(s, {}).get("item_date") or "" for s in srcs), default="") or None,
            })
        named = [h for h in holders if h != "unknown"]
        # chain: root -> the dependent with the most dependents, upward to an outcome nobody waits on
        chain, cur, guard = [root], root, set([root])
        while True:
            ups = [b for b in blocks[cur] if b not in resolved and b not in guard]
            if not ups:
                break
            cur = max(ups, key=lambda b: len(dependents(b)))
            guard.add(cur)
            chain.append(cur)
        srcs = sources_for(root)
        ask_dates = sorted(d for d in (items.get(s, {}).get("item_date") for s in srcs) if d)
        requests = [s for s in srcs if items.get(s, {}).get("clio_type") in ("communication", "task")]
        first = ask_dates[0] if ask_dates else None
        root_info = {
            "node_id": root,
            "label": nodes.get(root, {}).get("label", root),
            "dependents": [nodes.get(n, {}).get("label", n) for n in sorted(dependents(root))],
            "chain": [nodes.get(n, {}).get("label", n) for n in chain],
            "holders": named or ["unknown"],
            "disputed": len(named) > 1,
            "quotes": {h: q for h, q in holders.items()},
            "source_ids": sorted(srcs),
            "request_count": len(requests),
            "first_asked": first,
            "last_asked": ask_dates[-1] if ask_dates else None,
            "days_waiting": (today - date.fromisoformat(first)).days if first else None,
        }

    return {
        "root": root_info,
        "nodes": [{"node_id": n, "label": v["label"], "resolved": n in resolved,
                   "resolved_by_fact": v["resolved_by_fact"]} for n, v in nodes.items()],
        "edges": [{"blocked": d["node_blocked"], "waiting_on": d["node_waiting"], "holder": d["holder"],
                   "source_ids": json.loads(d["source_ids_json"]), "evidence": d["evidence"]} for d in deps],
    }
