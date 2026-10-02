-- Frozen contract. Changes after the freeze are additive and announced.
-- Additive vs the README: items.raw_json (the normalized record already carries it).

CREATE TABLE IF NOT EXISTS items(
  item_id TEXT PRIMARY KEY,
  source TEXT,              -- "clio" | "portal"
  clio_type TEXT,           -- matter | relationship | note | communication | task | calendar_entry | expense | document | document_page | provider_reply
  clio_id TEXT,
  title TEXT,
  text TEXT,
  item_date TEXT,           -- business date, ISO
  people_json TEXT,         -- [{"id": "contact:<id>", "name": "...", "role": "sender|receiver|attendee|assignee|..."}]
  hash TEXT,
  first_seen_at TEXT,
  last_synced_at TEXT,
  raw_json TEXT
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
  source_ids_json TEXT, evidence TEXT
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
  input_tokens INTEGER, output_tokens INTEGER
);
