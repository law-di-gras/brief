"""SQLite helpers shared by the pipeline and the product layer."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCHEMA = Path(__file__).with_name("schema.sql")


def db_path() -> str:
    return os.environ.get("DB_PATH", "brief.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text())
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
