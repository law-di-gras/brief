"""run_pipeline(matter_id): sync -> portal replies -> extract -> validate -> analyze -> graph.

    python -m backend.pipeline.run --matter-id $MATTER_ID [--full]
    python -m backend.pipeline.run --matter-id 1 --fixture-facts   # load dev/fixtures/facts.json, no model calls
"""
import argparse
import json
import logging
import os
from collections import Counter
from pathlib import Path

from backend import db
from backend.pipeline import analyze, extract, graph, llm, sync, validate
from backend.pipeline.clio import make_client

log = logging.getLogger(__name__)

REPAIRS = {"event_date_cleared"}          # counted for the log, but the fact was kept
MAX_REPLY_CHARS = 2000
FIXTURE = Path(__file__).resolve().parents[2] / "dev" / "fixtures" / "facts.json"


def _contact_id(raw) -> str:
    raw = str(raw)
    return raw if ":" in raw else f"contact:{raw}"


FIELD_LABELS = {"date": "Date given", "sent_on": "Sent on", "note": "Note"}


def ingest_replies(conn, matter_id) -> list[str]:
    """Provider replies (our DB, written by product/replies.py) become items with source='portal'.

    One submission (same share, request and time) is one item, however many fields it carried, so
    "date given" and "sent on" are read together and not as two replies that might disagree.
    """
    roster = {r["id"]: r for r in db.get_meta(conn, matter_id, "roster", [])}
    rows = conn.execute(
        "SELECT r.*, s.snapshot_json FROM provider_replies r JOIN shares s ON s.token = r.token WHERE s.matter_id=? "
        "ORDER BY r.id", (str(matter_id),)).fetchall()
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["token"], r["request_ref"], r["created_at"]), []).append(r)

    changed, keep = [], set()
    for grp in groups.values():
        first = grp[0]
        cid = _contact_id(first["provider_contact_id"])
        who = (roster.get(cid) or {}).get("name") or cid
        received = (first["created_at"] or "")[:10]
        lines = [f"Reply from {who} through the provider share page, received {received}."]
        if first["request_ref"]:
            # The ref is an opaque hash; the approved snapshot has what the firm actually asked for.
            asked = {q.get("ref"): q.get("what") for q in
                     ((db.J(first["snapshot_json"], {}) or {}).get("sections", {}).get("requests") or [])}
            lines.append(f"In answer to the firm's request for: {asked.get(first['request_ref']) or first['request_ref']}")
        for r in grp:
            if r["value"] and r["field"] != "note":
                lines.append(f"{FIELD_LABELS.get(r['field'], r['field'] or 'Answer')}: {r['value']}")
        note = next((r["note"] or r["value"] for r in grp if r["note"] or r["field"] == "note"), "")
        if note:
            lines.append(f"Note: {note}")
        item = dict(item_id=f"portal:{first['id']}", source="portal", clio_type="provider_reply", clio_id=None,
                    title=f"Reply from {who}", text="\n".join(lines)[:MAX_REPLY_CHARS], item_date=received or None,
                    people=[{"id": cid, "name": who, "role": "provider"}], raw=None)
        keep.add(item["item_id"])
        if sync.upsert_item(conn, matter_id, item):
            changed.append(item["item_id"])
    stale = [r["item_id"] for r in conn.execute("SELECT item_id FROM items WHERE source='portal'")
             if r["item_id"] not in keep]
    sync.delete_items(conn, stale)     # replies saved in an older one-item-per-field layout
    conn.commit()
    return changed + stale


def load_fixture_facts(conn, matter_id, path: Path = FIXTURE) -> dict:
    """Load the contract fixture. Facts go through the same validator as model output."""
    data = json.loads(path.read_text())
    roster = db.get_meta(conn, matter_id, "roster", [])

    def by_name(names):
        out = []
        for n in names or []:
            out += [r["id"] for r in roster if n.lower() in (r.get("name") or "").lower()]
        return out

    sent = {r["item_id"]: dict(r) for r in conn.execute("SELECT * FROM items")}
    roster_ids = {r["id"] for r in roster}
    for f in data["facts"]:
        f["entities"] = (f.get("entities") or []) + by_name(f.pop("entity_names", []))
    for d in data["dependencies"]:
        if "holder_name" in d:
            d["holder"] = (by_name([d.pop("holder_name")]) or ["unknown"])[0]

    conn.execute("DELETE FROM facts")
    conn.execute("DELETE FROM dependencies")
    keys = [f.pop("key") for f in data["facts"]]
    kept_keys, kept = [], []
    for k, f in zip(keys, data["facts"]):
        ok, drops = validate.validate_facts([f], sent, roster_ids)
        if ok:
            kept_keys.append(k)
            kept += ok
        else:
            log.warning("fixture fact %s dropped: %s", k, dict(drops))
    extract.insert_facts(conn, matter_id, kept, None)
    deps, ddrops = validate.validate_dependencies(data["dependencies"], sent, roster_ids)
    extract.insert_dependencies(conn, matter_id, deps, None)
    ids = [r["id"] for r in conn.execute("SELECT id FROM facts ORDER BY id")]
    key_to_id = dict(zip(kept_keys, ids))

    conn.execute("DELETE FROM conflicts")
    for c in data["conflicts"]:
        fids = [key_to_id[k] for k in c["facts"] if k in key_to_id]
        if len(fids) >= 2:
            conn.execute("INSERT INTO conflicts(fingerprint, fact_ids_json, topic, explanation, severity, "
                         "kpi_affected) VALUES (?,?,?,?,?,?)",
                         (analyze.fingerprint(fids), json.dumps(fids), c["topic"],
                          c.get("explanation"), c.get("severity", "medium"), c.get("kpi_affected")))
    conn.execute("DELETE FROM issues")
    facts = analyze.load_facts(conn, matter_id)
    items = analyze.item_map(conn, matter_id)
    for it in data["issues"]:
        fids = [key_to_id[k] for k in it["facts"] if k in key_to_id]
        dates = sorted(d for d in (analyze.said_date(facts[i], items) for i in fids) if d)
        conn.execute("INSERT INTO issues(topic, fact_ids_json, first_flagged, last_mentioned, mentions) "
                     "VALUES (?,?,?,?,?)", (it["topic"], json.dumps(fids),
                                              dates[0] if dates else None, dates[-1] if dates else None,
                                              len({s for i in fids for s in facts[i]["source_ids"]})))
    conn.commit()
    graph.label_nodes(conn, matter_id)
    return {"facts_kept": len(kept), "facts_dropped": len(keys) - len(kept),
            "dependencies": len(deps), "dependency_drops": dict(ddrops)}


def run_pipeline(matter_id, full: bool = False, skip_sync: bool = False, reextract: bool = False, conn=None,
                 user_id: str | None = None) -> dict:
    """Contract function (called by /sync and after each provider reply). Returns run stats."""
    own = conn is None
    conn = conn or db.connect()
    matter_id = str(matter_id)
    llm.reset_usage()
    run_id = conn.execute("INSERT INTO runs(matter_id, started_at, status) VALUES (?,?,'running')",
                          (matter_id, db.now_iso())).lastrowid
    conn.commit()
    stats = {"run_id": run_id, "items_changed": 0, "facts_kept": 0, "facts_dropped": 0, "drop_reasons": {}}
    status, error = "error", None
    try:
        changed = [] if skip_sync else sync.sync(conn, make_client(user_id), matter_id, full=full)
        changed += ingest_replies(conn, matter_id)
        # Items whose extraction failed last time are tried again, even though they have not changed.
        retry = [i for i in db.get_meta(conn, matter_id, "pending_extraction", [])
                 if conn.execute("SELECT 1 FROM items WHERE item_id=?", (i,)).fetchone()]
        changed = list(dict.fromkeys(changed + retry))
        if reextract:   # e.g. after a failed model run: send every stored item through extraction again
            changed = [r["item_id"] for r in conn.execute("SELECT item_id FROM items")]
        stats["items_changed"] = len(changed)

        drops = Counter()
        if changed:
            if llm.available():
                kept, drops, failed = extract.extract_items(conn, matter_id, changed, run_id)
                stats["facts_kept"] = kept
                db.set_meta(conn, matter_id, "pending_extraction", failed)
                stats["extraction_failed"] = len(failed)
            else:
                db.set_meta(conn, matter_id, "pending_extraction", changed)   # keep old facts; extract when a key exists
                log.warning("ANTHROPIC_API_KEY not set: items synced, extraction skipped")
        stats["drop_reasons"] = dict(drops)
        stats["facts_dropped"] = sum(v for k, v in drops.items() if k not in REPAIRS and not k.startswith("dep_")
                                     and k != "batch_failed")

        never_analyzed = conn.execute("SELECT COUNT(*) n FROM blocker_nodes WHERE matter_id=?",
                                      (matter_id,)).fetchone()["n"] == 0
        if changed or never_analyzed:
            stats["analysis"] = analyze.analyze(conn, matter_id)
            graph.label_nodes(conn, matter_id)
        conn.execute("DELETE FROM editions WHERE matter_id=?", (matter_id,))
        n_failed = stats.get("extraction_failed", 0)
        status = "partial" if n_failed else "ok"
        error = f"{n_failed} item(s) could not be extracted and will be retried on the next run" if n_failed else None
    except Exception as e:
        status, error = "error", f"{type(e).__name__}: {e}"
        log.exception("pipeline failed")
        raise
    finally:
        inp, out = llm.usage()
        stats.update(input_tokens=inp, output_tokens=out, status=status)
        conn.execute(
            """UPDATE runs SET finished_at=?, items_changed=?, facts_kept=?, facts_dropped=?, drop_reasons_json=?,
                   input_tokens=?, output_tokens=?, status=?, error=? WHERE id=?""",
            (db.now_iso(), stats["items_changed"], stats["facts_kept"], stats["facts_dropped"],
             json.dumps(stats["drop_reasons"]), inp, out, status, error, run_id))
        conn.commit()
        if own:
            conn.close()
    return stats


def main():
    p = argparse.ArgumentParser(description="Run the Brief pipeline for one matter")
    p.add_argument("--matter-id", default=os.environ.get("MATTER_ID"), required=not os.environ.get("MATTER_ID"))
    p.add_argument("--full", action="store_true", help="ignore updated_since and resync everything")
    p.add_argument("--reextract", action="store_true", help="send every stored item through extraction again")
    p.add_argument("--fixture-facts", action="store_true", help="load dev/fixtures/facts.json instead of calling the model")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.fixture_facts:
        conn = db.connect()
        sync.sync(conn, make_client(), args.matter_id, full=True)
        print(json.dumps(load_fixture_facts(conn, args.matter_id), indent=2))
        return
    print(json.dumps(run_pipeline(args.matter_id, full=args.full, reextract=args.reextract), indent=2))


if __name__ == "__main__":
    main()
