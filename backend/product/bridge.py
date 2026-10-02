"""The two functions that cross the A/B line.

    run_pipeline(matter_id) -> run_stats
    build_edition(matter_id, since) -> edition_json

B expects edition_json to look like:

    {"headline": {"text", "source_ids", "evidence"},
     "lead":     [{"text", "source_ids", "evidence"}, ...],          # up to 4
     "blocker":  {"node", "label", "resolved", "disputed",
                  "holders": [{"holder", "name", "quote", "source_ids", "date"}],
                  "dependents": ["label", ...], "requests_sent": int} | None}

Until backend/pipeline exists, the fallbacks below serve the cached edition row
and a plain reading of the `dependencies` table, so the product side runs on
fixtures. If A's edition has no "blocker" key, the fallback blocker is used.
"""
from backend import db
from backend.product import deterministic as det

try:
    from backend.pipeline.run import run_pipeline as _run_pipeline
except Exception:  # pipeline not pushed yet
    _run_pipeline = None
try:
    from backend.pipeline.edition import build_edition as _build_edition
except Exception:
    _build_edition = None

PIPELINE_LIVE = bool(_run_pipeline and _build_edition)


def run_pipeline(matter_id, user_id=None):
    """user_id: the signed-in firm user whose Clio token to read with. None = the service account."""
    if _run_pipeline:
        return _run_pipeline(matter_id, user_id=user_id)
    return {"stub": True, "items_changed": 0, "facts_kept": 0, "facts_dropped": 0,
            "note": "backend.pipeline.run not available; nothing was extracted"}


def fallback_blocker(matter_id):
    deps = det.deps()
    if not deps:
        return None
    kw = lambda d: d.get("node_waiting") or d["waiting_on"].strip().lower()
    kb = lambda d: d.get("node_blocked") or d["blocked"].strip().lower()
    children, labels = {}, {}
    for d in deps:
        children.setdefault(kw(d), set()).add(kb(d))
        labels.setdefault(kb(d), d["blocked"])
        labels[kw(d)] = d["waiting_on"]

    def reach(n, seen=None):
        seen = set() if seen is None else seen
        for c in children.get(n, ()):
            if c not in seen:
                seen.add(c)
                reach(c, seen)
        return seen

    root = max(children, key=lambda n: len(reach(n)))
    people = det.contacts(matter_id)
    dates = {i["item_id"]: i["item_date"] for i in db.q("SELECT item_id, item_date FROM items")}
    mine = [d for d in deps if kw(d) == root]
    holders = [{"holder": d["holder"], "name": people.get(d["holder"], {}).get("name") or d["holder"],
                "quote": d["evidence"], "source_ids": d["source_ids"],
                "date": max([dates.get(s) or "" for s in d["source_ids"]] or [""]) or None} for d in mine]
    answered = []
    for h in {h["holder"] for h in holders}:
        answered += [r for r in det.open_requests(h) if r["node"] == root and r["answered"]]
    requests = sum(r["times_asked"] for h in {h["holder"] for h in holders} for r in det.open_requests(h) if r["node"] == root)
    return {"node": root, "label": labels[root], "resolved": False,
            "disputed": len({h["holder"] for h in holders}) > 1, "holders": holders,
            "dependents": [labels.get(n, n) for n in reach(root)], "requests_sent": requests,
            "reply_received": bool(answered)}


def build_edition(matter_id, since=None):
    ed = None
    if _build_edition:
        ed = _build_edition(matter_id, since, wait=False)   # page loads never wait on the model
    if not ed:
        rows = db.q("SELECT * FROM editions WHERE matter_id=? ORDER BY created_at DESC LIMIT 1", (str(matter_id),))
        ed = {"headline": db.J(rows[0]["headline_json"]) if rows else None,
              "lead": db.J(rows[0]["lead_json"], []) if rows else []}
    if "blocker" not in ed:
        ed["blocker"] = fallback_blocker(matter_id)
    return ed
