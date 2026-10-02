"""SQLite helpers shared by the pipeline (get_meta, fact_row, ...) and the product layer (q, x, J)."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCHEMA = Path(__file__).with_name("schema.sql")


def db_path() -> str:
    return os.environ.get("DB_PATH", "brief.db")


_ready: set[str] = set()      # database files whose schema this process has already applied
_ready_lock = threading.Lock()


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or db_path()
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    # Apply the schema once per file per process, not on every connection: it takes a write lock.
    with _ready_lock:
        if path not in _ready:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA.read_text())
            _ready.add(path)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_meta(conn, matter_id, key, default=None):
    row = conn.execute(
        "SELECT value_json FROM meta WHERE matter_id=? AND key=?", (str(matter_id), key)
    ).fetchone()
    return json.loads(row["value_json"]) if row else default


def set_meta(conn, matter_id, key, value) -> None:
    conn.execute(
        "INSERT INTO meta(matter_id, key, value_json) VALUES (?,?,?) "
        "ON CONFLICT(matter_id, key) DO UPDATE SET value_json=excluded.value_json",
        (str(matter_id), key, json.dumps(value)),
    )


def fact_row(row) -> dict:
    """Decode a facts row into the JSON shape used across the app."""
    d = dict(row)
    d["entities"] = json.loads(d.pop("entities_json") or "[]")
    d["source_ids"] = json.loads(d.pop("source_ids_json") or "[]")
    d["is_open_issue"] = bool(d["is_open_issue"])
    return d


# ---- product-side helpers (each opens its own short-lived connection) ----

def q(sql, args=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def x(sql, args=()):
    conn = connect()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def J(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
