# Brief: the case reads itself

> Team: **[team name]** · Swans Applied AI Hackathon, Law-Di-Gras, San Diego, October 2, 2026

Brief turns a live Clio Manage matter into a front page for each person who opens it, and into a smaller, attorney-approved page for each treating provider.

- **Attorneys** get what changed since their last visit, the case in four cited sentences, the one thing holding the case up, and every place the file disagrees with itself.
- **Providers** get case status, what the firm needs from their office, and updates as the case moves, through a share link the attorney controls.

Every sentence on screen links back to the Clio note, email, task or document page it came from.

---

## Where to look first (for judges)

1. **`backend/pipeline/validate.py`**: the three trust rules. Anything the model can't back with a real source is dropped, and the drop counts are logged per run.
2. **`backend/pipeline/clio.py`**: the Clio client has a `get()` method and nothing else. There is no code path that writes to Clio.
3. **`backend/pipeline/graph.py`**: the root blocker is computed in plain Python from extracted dependencies, not chosen by the model.
4. **`backend/product/provider.py`**: the provider page renders only from the attorney-approved share snapshot. It never queries internal facts.
5. **Nothing is case-specific.** No prompt or code mentions Sapini, a person, a provider, or a dollar amount. Change `MATTER_ID` and it builds a new front page.

---

## The three trust rules

Every fact the model extracts must pass all three checks in `validate.py`, or it is dropped:

1. **Real sources only.** Every `source_id` must be one of the items actually sent in that request.
2. **Verbatim evidence.** Every fact carries an `evidence` quote that must appear word for word in a cited source. The source viewer highlights it.
3. **No number without a source.** Every number, dollar amount and date in a fact or a generated sentence must appear in the cited source text, after normalization (`$22,180.00` matches `22180`, `5 October 2011` matches `2011-10-05`).

Each run records how many facts were kept and dropped in the `runs` table, shown in the app's debug footer.

---

## Architecture

```
Clio Manage (GET only)
   │  ClioReadOnly client: no POST/PUT/PATCH/DELETE methods exist
   ▼
1. SYNC ───────────► items: one row per note, communication, task, event, expense, document page
   │                 content hash per item; only new or changed hashes go forward
   ▼
2. DOC TEXT ───────► PyMuPDF text per page; image-only documents flagged; photo ID image extracted
   ▼
3. EXTRACT (Sonnet) ► facts + dependencies, each citing item IDs and a verbatim evidence quote
   ▼
4. VALIDATE (code) ─► drop fake source IDs, non-verbatim quotes, unsourced numbers
   ▼
5. ANALYZE (runs over facts, not raw items)
   ├─ conflicts       (Sonnet)  facts from different items that disagree
   ├─ open issues     (Sonnet)  problems the firm flagged, and how long they have been open
   ├─ blocker graph   (Sonnet labels nodes, Python builds the graph) root blocker + disputed holder check
   └─ ranking         (Haiku)   importance 1 to 5 with a one-line reason
   ▼
6. EDITIONS
   ├─ Attorney: headline + lead (Sonnet, cited) + deterministic sections (no AI)
   └─ Provider: attorney-approved snapshot behind a token link, with a view log
```

### Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, httpx |
| Database | SQLite (outside Clio), file at `DB_PATH` |
| PDFs | PyMuPDF |
| AI | Anthropic API: `claude-sonnet-5-5` for extraction, analysis and writing; `claude-haiku-4-5-20251001` for ranking and classification |
| Frontend | React + Vite + Tailwind |
| Runs on | localhost |

---

## Workflow, stage by stage

### 1. Read-only Clio sync (`pipeline/clio.py`, `pipeline/sync.py`)

| Resource | Endpoint | Business date (`item_date`) |
|---|---|---|
| Matter + custom fields | `/matters/{id}.json` | open_date |
| Roster | `/relationships.json?matter_id=` | n/a |
| Notes | `/notes.json?matter_id=&type=Matter` | date |
| Communications | `/communications.json?matter_id=` | date |
| Tasks | `/tasks.json?matter_id=` | due_at |
| Calendar | `/calendar_entries.json?matter_id=` | start_at |
| Expenses | `/activities.json?matter_id=&type=ExpenseEntry` | date |
| Documents | `/documents.json?matter_id=` + download | received_at |

- Clio returns minimal data unless `fields=` is passed, so every call names its fields.
- Each record is normalized to `{item_id, clio_type, title, text, item_date, people, raw_json}`.
- The hash covers content fields only (not `updated_at` or `etag`), so a no-op edit costs nothing.
- Re-syncs use `updated_since` plus the hash.
- "Since your last visit" uses each item's business date, not Clio's `created_at`.

### 2. Documents (`pipeline/docs.py`)

- Pages with a text layer become one item each (`doc:45:p3`), so citations open the exact page.
- Scanned documents with no text layer get a single placeholder item so the model knows they exist.
- Haiku classifies documents by name into types (photo ID, pleading, medical records, expert report, and so on). The client photo is the largest embedded image in the document classified as a photo ID.

### 3. Extraction (`pipeline/extract.py`)

Changed items only, about 10 per call, with JSON forced through tool use. The prompt includes the matter's roster (client, firm user, related contacts with IDs), so names resolve to contact IDs.

```json
{
  "facts": [{
    "text": "...",
    "category": "coverage|liability|injury|treatment|damages|lien|procedure|discovery|client_contact|provider_request|issue",
    "event_date": "YYYY-MM-DD",
    "entities": ["contact:<id>"],
    "source_ids": ["note:<id>"],
    "evidence": "exact quote from the source",
    "audience": "internal | shareable",
    "is_open_issue": false
  }],
  "dependencies": [{
    "blocked": "short label",
    "waiting_on": "short label",
    "holder": "contact:<id> | firm | court | unknown",
    "source_ids": ["..."],
    "evidence": "..."
  }]
}
```

### 4. Validation (`pipeline/validate.py`)

See the three trust rules above.

### 5. Analysis (`pipeline/analyze.py`, `pipeline/graph.py`)

- **Conflicts:** facts are grouped by category and checked for disagreement. A conflict is kept only if its facts come from at least two different items. Each conflict is fingerprinted by its sorted fact IDs, so re-runs don't duplicate it.
- **Open issues:** facts the firm marked as problems are clustered by topic. Code computes when each issue was first flagged, how often it was mentioned, how many days it has been open, and whether a later fact resolves it.
- **Blocker graph:** the model only maps free-text dependency labels to canonical node IDs. Python then builds the graph, picks as root blocker the unresolved node with the most dependents, and marks it **disputed** when its sources name different holders.
- **Ranking:** Haiku scores new facts 1 to 5 with a reason.

### 6. Attorney edition (`product/edition.py`, `product/deterministic.py`)

| Section | How it's made |
|---|---|
| Masthead: client, photo, stage, "N updates since [date]" | No AI |
| Headline + lead story (up to 4 sentences, each cited) | Sonnet, then the number check |
| KPIs: case value, coverage, specials, lien, firm spend | No AI (Haiku maps custom field names to slots once) |
| Root blocker card | Graph output + conflicting quotes |
| Corrections: conflicts + open issues with age | Analysis output |
| Still waiting: who owes what, requests sent, days silent | No AI |
| Coming up: next 21 days, overdue tasks first | No AI |
| Last client contact | No AI |
| Source viewer with highlighted evidence + Clio link | Stored source IDs |
| Full file, filterable | No AI |

The headline and lead are cached by fact-table version and visit date.

### 7. Provider edition and sharing (`product/provider.py`)

- Haiku classifies matter relationships by role and keeps the treating providers.
- Each provider gets a draft with four sections:
  - case status and last activity date
  - coverage as confirmed or unconfirmed only (**blocked while a coverage conflict is open**)
  - what the firm needs from this office
  - shareable updates involving them
- If the provider is a holder on a disputed root blocker, Brief drafts a cited message from the other holder's statement for the attorney to approve.
- The attorney reviews the draft with a toggle per section and per fact. Approval creates a share with a random token (`secrets.token_urlsafe(32)`), a 30-day expiry and a revoke button.
- The provider page renders only from the approved snapshot. New shareable facts wait in an approval queue on the attorney page.
- Every view of a share link is logged.

### What happens when one note changes

1. The sync finds one changed hash.
2. Facts sourced from that item are deleted.
3. That one item is re-extracted.
4. The analysis passes re-run over facts.
5. The edition cache is invalidated.

Nothing else is re-read.

---

## Data model (`schema.sql`)

```sql
items(item_id PK, clio_type, clio_id, title, text, item_date, people_json, hash, first_seen_at, last_synced_at)
facts(id PK, text, category, event_date, entities_json, source_ids_json, evidence, audience, is_open_issue, importance, importance_reason, run_id)
dependencies(id PK, blocked, waiting_on, holder, node_blocked, node_waiting, source_ids_json, evidence)
conflicts(id PK, fingerprint UNIQUE, fact_ids_json, topic, explanation, severity, kpi_affected, status)
issues(id PK, topic, fact_ids_json, first_flagged, last_mentioned, mentions, resolved_by_fact)
editions(cache_key PK, matter_id, headline_json, lead_json, created_at)
visits(user_id, matter_id, last_visit_at, PRIMARY KEY(user_id, matter_id))
shares(token PK, matter_id, provider_contact_id, sections_json, approved_fact_ids_json, message, expires_at, revoked)
share_views(token, viewed_at, ua_hash)
runs(id PK, started_at, items_changed, facts_kept, facts_dropped, input_tokens, output_tokens)
```

## API routes

```
GET  /auth/clio/login            GET  /auth/clio/callback
POST /matters/{id}/sync          run sync + pipeline, return run stats
GET  /matters/{id}/edition?since=
POST /matters/{id}/visit
GET  /items/{item_id}            source viewer
GET  /matters/{id}/providers
GET  /matters/{id}/shares        POST /matters/{id}/shares
GET  /p/{token}                  provider page, logs the view
GET  /matters/{id}/runs          token usage and drop counts
```

## Repo layout

```
backend/
  pipeline/   clio.py  sync.py  docs.py  llm.py  extract.py  validate.py  analyze.py  graph.py  run.py
  product/    deterministic.py  edition.py  provider.py
  db.py  schema.sql  main.py
frontend/
  src/pages/  AttorneyEdition.jsx  ProviderReview.jsx  ProviderPage.jsx  FullFile.jsx
dev/          load_seed.py  fixtures/facts.json   (development only, never imported by the app)
```

---

## Setup

```bash
# 1. Environment
cp .env.example .env
# CLIO_CLIENT_ID, CLIO_CLIENT_SECRET, CLIO_REDIRECT_URI=http://localhost:8000/auth/clio/callback
# ANTHROPIC_API_KEY, MATTER_ID, DB_PATH=brief.db

# 2. Backend
pip install -r requirements.txt
uvicorn backend.main:app --reload

# 3. Connect Clio (read-only scopes): open http://localhost:8000/auth/clio/login

# 4. Run the pipeline for a matter
python -m backend.pipeline.run --matter-id $MATTER_ID

# 5. Frontend
cd frontend && npm install && npm run dev
```

---

## Models and cost per case

| Step | Model |
|---|---|
| Fact + dependency extraction, conflicts, open issues, blocker labels, headline + lead | `claude-sonnet-5-5` |
| Importance ranking, document / role / custom field classification | `claude-haiku-4-5-20251001` |

Every API call logs its token usage to the `runs` table.

| Run | Input tokens | Output tokens | Cost |
|---|---|---|---|
| First full digest of Sapini | TODO: measured | TODO: measured | TODO |
| Incremental update (one new note) | TODO: measured | TODO: measured | TODO |

The full digest runs once per case. After that, only new or changed Clio items are sent to the model, so cost per update stays small as the file and the team grow.

---

## Not built / known limits

- OCR of the scanned medical records bundles (they appear as placeholder items only).
- TODO: list anything else unfinished before submitting.
