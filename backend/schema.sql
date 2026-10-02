-- Brief schema. One matter per database file (DB_PATH), so the core tables carry no matter_id.
-- Frozen contract from the README; later changes are additive only.
-- Additive vs the README: items.raw_json, dependencies.run_id, runs.* extras, and the
-- documents / blocker_nodes / meta / oauth_tokens tables used by the pipeline.
-- Pipeline (Person A) writes: items, documents, facts, dependencies, blocker_nodes, conflicts,
--   issues, editions, runs, meta, oauth_tokens.  Product (Person B) writes: visits, shares,
--   share_views, provider_replies.

CREATE TABLE IF NOT EXISTS items(
  item_id TEXT PRIMARY KEY,
  source TEXT,              -- "clio" | "portal"
  clio_type TEXT,           -- matter | relationship | note | communication | task | calendar_entry | expense | document | provider_reply
  clio_id TEXT,
  title TEXT,
  text TEXT,
  item_date TEXT,           -- business date, ISO
  people_json TEXT,         -- [{"id": "contact:<id>", "name": "...", "role": "sender|receiver|assignee|client|..."}]
  hash TEXT,
  first_seen_at TEXT,
  last_synced_at TEXT,
  raw_json TEXT             -- the Clio record as returned by the API
);

CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY,
  text TEXT, category TEXT, event_date TEXT,
  entities_json TEXT, source_ids_json TEXT, evidence TEXT,
  audience TEXT, importance INTEGER, is_open_issue INTEGER DEFAULT 0, run_id INTEGER
);

CREATE TABLE IF NOT EXISTS dependencies(
  id INTEGER PRIMARY KEY,
  blocked TEXT, waiting_on TEXT, holder TEXT,
  node_blocked TEXT, node_waiting TEXT,
  source_ids_json TEXT, evidence TEXT,
  run_id INTEGER
);

-- Canonical blocker-graph nodes (labels from the model, resolution checked by code).
CREATE TABLE IF NOT EXISTS blocker_nodes(
  matter_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  label TEXT NOT NULL,
  resolved_by_fact INTEGER,
  PRIMARY KEY (matter_id, node_id)
);

CREATE TABLE IF NOT EXISTS conflicts(
  id INTEGER PRIMARY KEY,
  fingerprint TEXT UNIQUE, fact_ids_json TEXT, topic TEXT, explanation TEXT,
  severity TEXT, kpi_affected TEXT, status TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS issues(
  id INTEGER PRIMARY KEY,
  topic TEXT, fact_ids_json TEXT, first_flagged TEXT, last_mentioned TEXT,
  mentions INTEGER, resolved_by_fact INTEGER
);

CREATE TABLE IF NOT EXISTS editions(
  cache_key TEXT PRIMARY KEY, matter_id TEXT, headline_json TEXT, lead_json TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS visits(
  user_id TEXT, matter_id TEXT, last_visit_at TEXT, PRIMARY KEY(user_id, matter_id)
);

CREATE TABLE IF NOT EXISTS shares(
  token TEXT PRIMARY KEY, matter_id TEXT, provider_contact_id TEXT,
  sections_json TEXT, snapshot_json TEXT,
  created_at TEXT, refreshed_at TEXT, expires_at TEXT, revoked INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS share_views(token TEXT, viewed_at TEXT, ua_hash TEXT);

CREATE TABLE IF NOT EXISTS provider_replies(
  id INTEGER PRIMARY KEY,
  token TEXT, provider_contact_id TEXT, request_ref TEXT,
  field TEXT, value TEXT, note TEXT, created_at TEXT, status TEXT DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY,
  started_at TEXT, items_changed INTEGER, facts_kept INTEGER, facts_dropped INTEGER,
  input_tokens INTEGER, output_tokens INTEGER,
  matter_id TEXT, finished_at TEXT, drop_reasons_json TEXT, status TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY,          -- Clio document id
  matter_id TEXT NOT NULL,
  name TEXT, folder TEXT, received_at TEXT,
  version_key TEXT,                 -- changes when a new version is uploaded
  pages INTEGER, text_pages INTEGER,
  image_only INTEGER NOT NULL DEFAULT 0,
  doc_type TEXT,                    -- photo_id | pleading | medical_records | ... (Haiku)
  photo_path TEXT
);

-- Sync cursors, roster, matter snapshot, client photo path.
CREATE TABLE IF NOT EXISTS meta(
  matter_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
  PRIMARY KEY (matter_id, key)
);

CREATE TABLE IF NOT EXISTS oauth_tokens(
  id INTEGER PRIMARY KEY CHECK (id = 1),
  access_token TEXT NOT NULL, refresh_token TEXT, expires_at REAL
);

-- Firm and provider sessions (product/sessions.py). Only a hash of the cookie value is stored.
CREATE TABLE IF NOT EXISTS sessions(
  sid_hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL,               -- firm | provider
  user_id TEXT, user_name TEXT,     -- firm sessions: the Clio user
  token TEXT,                       -- provider sessions: the share this session belongs to
  ua_hash TEXT,
  created_at TEXT, last_seen_at TEXT, expires_at TEXT,
  revoked INTEGER NOT NULL DEFAULT 0
);
