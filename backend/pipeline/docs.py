"""Documents: one item per page with a text layer, a placeholder for scans, Haiku doc types, client photo."""
import logging
import os
from pathlib import Path

import fitz  # PyMuPDF

from backend.pipeline import llm

log = logging.getLogger(__name__)

MIN_PAGE_CHARS = 40
DOC_TYPES = ["photo_id", "retainer_or_authorization", "pleading", "discovery", "medical_records",
             "medical_bills_or_liens", "correspondence", "expert_report", "insurance", "other"]


def data_dir() -> Path:
    p = Path(os.environ.get("DATA_DIR", "data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _version_key(d: dict) -> str:
    v = d.get("latest_document_version") or {}
    return str(v.get("uuid") or d.get("updated_at") or "")


def page_items(doc: dict, pdf_bytes: bytes) -> tuple[list[dict], dict]:
    """Split a document into page items (or one placeholder). Returns (items, stats)."""
    from backend.pipeline.sync import _d
    doc_id = str(doc["id"])
    name = doc.get("name") or f"Document {doc_id}"
    folder = (doc.get("parent") or {}).get("name")
    received = _d(doc.get("received_at") or doc.get("created_at"))
    items, n_pages = [], 0
    try:
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        n_pages = len(pdf)
        for i, page in enumerate(pdf, start=1):
            text = page.get_text().strip()
            if len(text) < MIN_PAGE_CHARS:
                continue
            items.append(dict(
                item_id=f"doc:{doc_id}:p{i}", source="clio", clio_type="document", clio_id=doc_id,
                title=f"{name}, page {i}",
                text=f"Document: {name} (folder: {folder}), page {i} of {n_pages}, received {received}\n\n{text}",
                item_date=received, people=[], raw={"doc_id": doc_id, "page": i},
            ))
    except Exception as e:  # noqa: BLE001 - unreadable files still get a placeholder
        log.warning("could not parse %s: %s", name, e)
    stats = {"pages": n_pages, "text_pages": len(items), "image_only": not items}
    if not items:
        items.append(dict(
            item_id=f"doc:{doc_id}", source="clio", clio_type="document", clio_id=doc_id, title=name,
            text=(f"Document: {name} (folder: {folder}), received {received}. {n_pages} pages, "
                  "scanned with no text layer; contents not read."),
            item_date=received, people=[], raw={"doc_id": doc_id, "placeholder": True},
        ))
    return items, stats


def process_documents(conn, clio, matter_id, documents: list[dict]) -> list[str]:
    from backend.pipeline.sync import upsert_item, delete_items
    changed = []
    cache = data_dir() / "docs"
    cache.mkdir(exist_ok=True)
    for d in documents:
        doc_id = str(d["id"])
        key = _version_key(d)
        row = conn.execute("SELECT version_key FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row and row["version_key"] == key and key:
            continue
        path = cache / f"{doc_id}.pdf"
        pdf = clio.get(f"/documents/{doc_id}/download", raw=True)
        path.write_bytes(pdf)
        items, stats = page_items(d, pdf)
        new_ids = {it["item_id"] for it in items}
        old_ids = [r["item_id"] for r in conn.execute(
            "SELECT item_id FROM items WHERE clio_type='document' AND clio_id=?", (doc_id,))]
        gone = [i for i in old_ids if i not in new_ids]
        delete_items(conn, gone)
        changed += gone
        changed += [it["item_id"] for it in items if upsert_item(conn, matter_id, it)]
        conn.execute(
            """INSERT INTO documents(doc_id, matter_id, name, folder, received_at, version_key, pages, text_pages, image_only)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(doc_id) DO UPDATE SET name=excluded.name, folder=excluded.folder,
                 received_at=excluded.received_at, version_key=excluded.version_key, pages=excluded.pages,
                 text_pages=excluded.text_pages, image_only=excluded.image_only""",
            (doc_id, str(matter_id), d.get("name"), (d.get("parent") or {}).get("name"), d.get("received_at"),
             key, stats["pages"], stats["text_pages"], int(stats["image_only"])),
        )
    classify_documents(conn, matter_id)
    extract_photo(conn, matter_id)
    return changed


# ---- classification ---------------------------------------------------------------

_KEYWORDS = [
    ("photo_id", ["photo-id", "photo id", "license", "passport"]),
    ("retainer_or_authorization", ["retainer", "hipaa", "authorization"]),
    ("expert_report", ["expert", "ime", "radiology-review", "review"]),
    ("medical_bills_or_liens", ["bill", "lien", "ledger"]),
    ("medical_records", ["record", "imaging", "mri", "operative"]),
    ("discovery", ["discovery", "subpoena", "demand", "interrogator", "deposition"]),
    ("pleading", ["summons", "complaint", "answer", "particulars", "pleading", "motion"]),
    ("correspondence", ["letter", "correspondence"]),
    ("insurance", ["declaration", "policy", "insurance"]),
]


def _heuristic_type(name: str) -> str:
    n = name.lower()
    for t, words in _KEYWORDS:
        if any(w in n for w in words):
            return t
    return "other"


def classify_documents(conn, matter_id) -> None:
    rows = conn.execute("SELECT doc_id, name, folder FROM documents WHERE matter_id=? AND doc_type IS NULL",
                        (str(matter_id),)).fetchall()
    if not rows:
        return
    types = {}
    if llm.available():
        listing = "\n".join(f"{r['doc_id']}: {r['name']} (folder: {r['folder']})" for r in rows)
        try:
            out = llm.call_json(
                llm.HAIKU,
                "You classify law-firm case documents by file name and folder.",
                f"Classify each document.\n\n{listing}",
                "classify_documents", "Record the type of each document.",
                {"type": "object", "properties": {"documents": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "doc_id": {"type": "string"},
                        "doc_type": {"type": "string", "enum": DOC_TYPES}},
                    "required": ["doc_id", "doc_type"]}}}, "required": ["documents"]},
                max_tokens=2000,
            )
            types = {str(x["doc_id"]): x["doc_type"] for x in out.get("documents", []) if x.get("doc_type") in DOC_TYPES}
        except Exception as e:  # noqa: BLE001
            log.warning("doc classification failed, using name heuristics: %s", e)
    for r in rows:
        conn.execute("UPDATE documents SET doc_type=? WHERE doc_id=?",
                     (types.get(r["doc_id"]) or _heuristic_type(f"{r['name']} {r['folder']}"), r["doc_id"]))


def extract_photo(conn, matter_id) -> None:
    """The client photo is the largest embedded image in the document classified as a photo ID."""
    row = conn.execute("SELECT doc_id FROM documents WHERE matter_id=? AND doc_type='photo_id' "
                       "ORDER BY received_at LIMIT 1", (str(matter_id),)).fetchone()
    if not row:
        return
    path = data_dir() / "docs" / f"{row['doc_id']}.pdf"
    if not path.exists():
        return
    best = None
    with fitz.open(path) as pdf:
        for page in pdf:
            for img in page.get_images(full=True):
                info = pdf.extract_image(img[0])
                size = info["width"] * info["height"]
                if not best or size > best[0]:
                    best = (size, info["image"], info["ext"])
    if not best:
        return
    out = data_dir() / "photos" / f"{matter_id}.{best[2]}"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(best[1])
    conn.execute("UPDATE documents SET photo_path=? WHERE doc_id=?", (str(out), row["doc_id"]))
    from backend import db
    db.set_meta(conn, matter_id, "client_photo", str(out))
