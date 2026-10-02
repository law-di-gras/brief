"""Analysis over facts (never raw items): conflicts and open issues, one Sonnet call per category group."""
import hashlib
import json
import logging
from collections import Counter

from backend import db
from backend.pipeline import llm, validate

log = logging.getLogger(__name__)

GROUPS = [
    ("money", {"coverage", "damages", "lien"}),
    ("liability", {"liability", "procedure", "discovery"}),
    ("medical", {"injury", "treatment", "provider_request"}),
    ("client", {"client_contact", "issue"}),
]
KPIS = ["case_value", "coverage", "specials", "lien", "wage_loss", "firm_spend", "none"]

SYSTEM = """You review facts extracted from a legal matter's file and find where the file disagrees
with itself, and which problems the firm itself has flagged.

Conflicts: two or more facts that cannot all be true, or that give different values for the same thing
(amounts, dates, who is responsible, whether something is confirmed). Facts that merely add detail, or
that describe a change over time in order, are not conflicts. For each conflict give the fact ids,
a short topic, one or two sentences explaining the disagreement using only what the facts say,
a severity (high when it changes case value, coverage or a deadline), and the KPI it affects.

Open issues: problems, gaps, mistakes or unanswered questions that the firm flagged in its own notes,
tasks or emails. Group facts that mention the same issue. If a later fact shows the issue was resolved,
give that fact's id as resolved_by_fact_id; otherwise null.

Only use fact ids from the list. Answer by calling the record_analysis tool."""

SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {"type": "array", "items": {"type": "object", "properties": {
            "fact_ids": {"type": "array", "items": {"type": "integer"}},
            "topic": {"type": "string"},
            "explanation": {"type": "string"},
            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "kpi_affected": {"type": "string", "enum": KPIS},
        }, "required": ["fact_ids", "topic", "explanation", "severity", "kpi_affected"]}},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "topic": {"type": "string"},
            "fact_ids": {"type": "array", "items": {"type": "integer"}},
            "resolved_by_fact_id": {"type": ["integer", "null"]},
        }, "required": ["topic", "fact_ids"]}},
    },
    "required": ["conflicts", "issues"],
}


def load_facts(conn, matter_id) -> dict[int, dict]:
    return {r["id"]: db.fact_row(r) for r in conn.execute(
        "SELECT * FROM facts WHERE matter_id=? ORDER BY id", (str(matter_id),))}


def item_map(conn, matter_id) -> dict[str, dict]:
    return {r["item_id"]: dict(r) for r in conn.execute(
        "SELECT item_id, item_date, text, title, clio_type, source FROM items WHERE matter_id=?", (str(matter_id),))}


def fact_date(f: dict, items: dict) -> str | None:
    """When a fact was said: its event date, else the earliest business date of its sources."""
    if f.get("event_date"):
        return f["event_date"]
    dates = [items[s]["item_date"] for s in f["source_ids"] if s in items and items[s]["item_date"]]
    return min(dates) if dates else None


def said_date(f: dict, items: dict) -> str | None:
    """When the file recorded the fact (latest source date)."""
    dates = [items[s]["item_date"] for s in f["source_ids"] if s in items and items[s]["item_date"]]
    return max(dates) if dates else f.get("event_date")


def fingerprint(fact_ids) -> str:
    return hashlib.sha256(json.dumps(sorted(set(fact_ids))).encode()).hexdigest()[:24]


def _fact_line(f, items) -> str:
    return (f"[{f['id']}] ({f['category']}; said {said_date(f, items) or '?'}; source {', '.join(f['source_ids'])}) "
            f"{f['text']}")


def analyze(conn, matter_id) -> dict:
    matter_id = str(matter_id)
    if not llm.available():
        # Without the model there is nothing new to say; keep the last analysis as it is.
        log.warning("ANTHROPIC_API_KEY not set: skipping conflict/issue analysis")
        return {"skipped": True}
    facts = load_facts(conn, matter_id)
    items = item_map(conn, matter_id)
    old_status = {r["fingerprint"]: r["status"] for r in conn.execute(
        "SELECT fingerprint, status FROM conflicts WHERE matter_id=?", (matter_id,))}
    conflicts, issues = [], []
    drops = Counter()

    for name, cats in GROUPS:
        group = [f for f in facts.values() if f["category"] in cats]
        if len(group) < 2 and not any(f["is_open_issue"] for f in group):
            continue
        listing = "\n".join(_fact_line(f, items) for f in group)
        try:
            out = llm.call_json(llm.SONNET, SYSTEM, f"Facts ({name}):\n{listing}", "record_analysis",
                                "Record conflicts and open issues.", SCHEMA, max_tokens=16000, effort="medium")
        except Exception as e:  # noqa: BLE001
            log.error("analysis %s failed: %s", name, e)
            continue
        ids = {f["id"] for f in group}
        for c in out.get("conflicts") or []:
            fids = sorted({i for i in c.get("fact_ids") or [] if i in ids})
            sources = [frozenset(facts[i]["source_ids"]) for i in fids]
            # A conflict is real only when its facts come from at least two different items.
            if len(fids) < 2 or len(set(sources)) < 2 or len(frozenset().union(*sources)) < 2:
                drops["conflict_single_source"] += 1
                continue
            expl = (c.get("explanation") or "").strip()
            src_texts = [items[s]["text"] for i in fids for s in facts[i]["source_ids"] if s in items]
            if expl and not validate.check_sentence(expl, src_texts + [facts[i]["text"] for i in fids]):
                drops["conflict_explanation_number"] += 1
                expl = None
            conflicts.append({"fact_ids": fids, "topic": c.get("topic") or name, "explanation": expl,
                              "severity": c.get("severity") or "medium",
                              "kpi_affected": None if c.get("kpi_affected") in (None, "none") else c["kpi_affected"]})
        for it in out.get("issues") or []:
            fids = sorted({i for i in it.get("fact_ids") or [] if i in ids})
            if fids:
                issues.append({"topic": it.get("topic") or "Open issue", "fact_ids": fids,
                               "resolved_by": it.get("resolved_by_fact_id")})

    # Facts the extractor flagged as open issues but no group claimed still count as issues.
    claimed = {i for it in issues for i in it["fact_ids"]}
    for f in facts.values():
        if f["is_open_issue"] and f["id"] not in claimed:
            issues.append({"topic": f["text"][:80], "fact_ids": [f["id"]], "resolved_by": None})

    conn.execute("DELETE FROM conflicts WHERE matter_id=?", (matter_id,))
    seen = set()
    for c in conflicts:
        fp = fingerprint(c["fact_ids"])
        if fp in seen:
            continue
        seen.add(fp)
        conn.execute(
            """INSERT INTO conflicts(matter_id, fingerprint, fact_ids_json, topic, explanation, severity, kpi_affected, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (matter_id, fp, json.dumps(c["fact_ids"]), c["topic"], c["explanation"], c["severity"],
             c["kpi_affected"], old_status.get(fp, "open")))

    conn.execute("DELETE FROM issues WHERE matter_id=?", (matter_id,))
    for it in issues:
        fs = [facts[i] for i in it["fact_ids"]]
        dates = sorted(d for d in (said_date(f, items) for f in fs) if d)
        mentions = len({s for f in fs for s in f["source_ids"]})
        resolved = it["resolved_by"]
        # The resolving fact must exist and be recorded no earlier than the last mention.
        if resolved not in facts or resolved in it["fact_ids"] or \
                (dates and (said_date(facts[resolved], items) or "") < dates[-1]):
            resolved = None
        conn.execute(
            """INSERT INTO issues(matter_id, topic, fact_ids_json, first_flagged, last_mentioned, mentions, resolved_by_fact)
               VALUES (?,?,?,?,?,?,?)""",
            (matter_id, it["topic"], json.dumps(it["fact_ids"]), dates[0] if dates else None,
             dates[-1] if dates else None, mentions, resolved))
    conn.commit()
    log.info("analysis: %d conflicts, %d issues, drops %s", len(seen), len(issues), dict(drops))
    return {"conflicts": len(seen), "issues": len(issues), "drops": dict(drops)}
