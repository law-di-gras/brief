-- Brief schema. Frozen from the README contract; later changes are additive only.
-- Pipeline (Person A) writes: items, documents, facts, dependencies, blocker_nodes,
--   conflicts, issues, editions, runs, meta, oauth_tokens.
-- Product (Person B) writes: visits, shares, share_views, provider_replies.

CREATE TABLE IF NOT EXISTS items (
    item_id         TEXT PRIMARY KEY,          -- note:12, comm:7, task:3, event:9, expense:4, doc:45:p3, doc:45, matter:1, portal:5
    matter_id       TEXT NOT NULL,
    source          TEXT NOT NULL,             -- clio | portal
    clio_type       TEXT,                      -- note | communication | task | calendar_entry | expense | document | matter
    clio_id         TEXT,
    title           TEXT,
    text            TEXT NOT NULL DEFAULT '',
    item_date       TEXT,                      -- business date, YYYY-MM-DD
    people_json     TEXT NOT NULL DEFAULT '[]',
    raw_json        TEXT,
    hash            TEXT NOT NULL,
    first_seen_at   TEXT NOT NULL,
    last_synced_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_matter ON items(matter_id);

CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,          -- Clio document id
    matter_id       TEXT NOT NULL,
    name            TEXT,
    folder          TEXT,
    received_at     TEXT,
    version_key     TEXT,                      -- changes when a new version is uploaded
    pages           INTEGER,
    text_pages      INTEGER,
    image_only      INTEGER NOT NULL DEFAULT 0,
    doc_type        TEXT,                      -- photo_id | pleading | medical_records | ... (Haiku)
    photo_path      TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id       TEXT NOT NULL,
    text            TEXT NOT NULL,
    category        TEXT NOT NULL,
    event_date      TEXT,
    entities_json   TEXT NOT NULL DEFAULT '[]',
    source_ids_json TEXT NOT NULL,
    evidence        TEXT NOT NULL,
    audience        TEXT NOT NULL DEFAULT 'internal',
    importance      INTEGER NOT NULL DEFAULT 3,
    is_open_issue   INTEGER NOT NULL DEFAULT 0,
    run_id          INTEGER
);
CREATE INDEX IF NOT EXISTS facts_matter ON facts(matter_id);

CREATE TABLE IF NOT EXISTS dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id       TEXT NOT NULL,
    blocked         TEXT NOT NULL,
    waiting_on      TEXT NOT NULL,
    holder          TEXT NOT NULL DEFAULT 'unknown',
    node_blocked    TEXT,
    node_waiting    TEXT,
    source_ids_json TEXT NOT NULL,
    evidence        TEXT NOT NULL,
    run_id          INTEGER
);

-- Canonical blocker-graph nodes (labels from the model, resolution checked by code).
CREATE TABLE IF NOT EXISTS blocker_nodes (
    matter_id        TEXT NOT NULL,
    node_id          TEXT NOT NULL,
    label            TEXT NOT NULL,
    resolved_by_fact INTEGER,
    PRIMARY KEY (matter_id, node_id)
);

CREATE TABLE IF NOT EXISTS conflicts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id       TEXT NOT NULL,
    fingerprint     TEXT NOT NULL UNIQUE,
    fact_ids_json   TEXT NOT NULL,
    topic           TEXT NOT NULL,
    explanation     TEXT,
    severity        TEXT,                      -- high | medium | low
    kpi_affected    TEXT,                      -- case_value | coverage | specials | lien | firm_spend | null
    status          TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS issues (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id        TEXT NOT NULL,
    topic            TEXT NOT NULL,
    fact_ids_json    TEXT NOT NULL,
    first_flagged    TEXT,
    last_mentioned   TEXT,
    mentions         INTEGER NOT NULL DEFAULT 0,
    resolved_by_fact INTEGER
);

CREATE TABLE IF NOT EXISTS editions (
    cache_key       TEXT PRIMARY KEY,
    matter_id       TEXT NOT NULL,
    headline_json   TEXT,
    lead_json       TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visits (
    user_id         TEXT NOT NULL,
    matter_id       TEXT NOT NULL,
    last_visit_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, matter_id)
);

CREATE TABLE IF NOT EXISTS shares (
    token               TEXT PRIMARY KEY,
    matter_id           TEXT NOT NULL,
    provider_contact_id TEXT NOT NULL,
    sections_json       TEXT NOT NULL,
    snapshot_json       TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    refreshed_at        TEXT,
    expires_at          TEXT NOT NULL,
    revoked             INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS share_views (
    token           TEXT NOT NULL,
    viewed_at       TEXT NOT NULL,
    ua_hash         TEXT
);

CREATE TABLE IF NOT EXISTS provider_replies (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    token               TEXT NOT NULL,
    provider_contact_id TEXT NOT NULL,
    request_ref         TEXT,
    field               TEXT,
    value               TEXT,
    note                TEXT,
    created_at          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    matter_id       TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    items_changed   INTEGER NOT NULL DEFAULT 0,
    facts_kept      INTEGER NOT NULL DEFAULT 0,
    facts_dropped   INTEGER NOT NULL DEFAULT 0,
    drop_reasons_json TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    status          TEXT,
    error           TEXT
);

-- Small key/value store: sync cursors, roster, matter snapshot, classifier caches.
CREATE TABLE IF NOT EXISTS meta (
    matter_id       TEXT NOT NULL,
    key             TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    PRIMARY KEY (matter_id, key)
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    expires_at      REAL
);
