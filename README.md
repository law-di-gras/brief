# Brief: the case reads itself

> Team: **Lawgic** · Swans Applied AI Hackathon, Law-Di-Gras, San Diego, October 2, 2026

Brief turns a live Clio Manage matter into two connected views:

- **For the firm's team:** a front page per person, showing what changed since their last visit, a timeline of the case, the case in four cited sentences, the one thing holding the case up, and every place the file disagrees with itself.
- **For each treating provider:** an attorney-approved page showing whether the case is alive, whether coverage is confirmed, exactly what the firm needs from their office, and their patient's treatment on file. Providers **answer the firm's requests on that page** instead of by email, and their answers flow back into the attorney's front page.

Every sentence on screen opens the exact note, email, task or document page it came from, inside Brief, with the supporting quote highlighted, and links to the matter in Clio. Brief reads Clio and never writes to it.

---

## Where to look first (for judges)

1. **`backend/pipeline/validate.py`**: the three trust rules. Anything the model can't back with a real source is dropped, and the drop counts are logged per run.
2. **`backend/pipeline/clio.py`**: the Clio client has a `get()` method and nothing else. There is no code path that writes to Clio.
3. **`backend/pipeline/graph.py`**: the root blocker is computed in plain Python from extracted dependencies, not chosen by the model.
4. **`backend/product/provider.py`**: the provider page renders only from the attorney-approved share snapshot. It never queries internal facts.
5. **`backend/product/replies.py`**: provider answers are stored in our own database and re-enter the pipeline as items, so a reply can clear a blocker on the attorney's page. Nothing is written to Clio.
6. **Nothing is case-specific.** No prompt or backend or frontend code mentions Sapini, a person, a provider, or a dollar amount (the only Sapini data is the offline test fixtures in `dev/`). Change `MATTER_ID` and it builds a new front page.
7. **`backend/pipeline/analyze.py`, `independent()`**: a conflict is kept only if its statements come from independent origins (see below).
8. **`backend/product/sessions.py`**: both sides have sessions. The firm side opens only after a Clio sign-in, and a provider can reply only from a browser that opened their own link.

---

## The three trust rules

Every fact the model extracts must pass all three checks in `validate.py`, or it is dropped:

1. **Real sources only.** Every `source_id` must be one of the items actually sent in that request.
2. **Verbatim evidence.** Every fact carries an `evidence` quote that must appear word for word in a cited source. The source viewer highlights it.
3. **No number without a source.** Every number, dollar amount and date in a fact or a generated sentence must appear in the cited source text, after normalization (`$22,180.00` matches `22180`, `5 October 2011` matches `2011-10-05`).

Each run records how many facts were kept and dropped, with the reason for each drop, in the `runs` table, shown in the app's debug footer. On the first live run over Sapini the model proposed 399 facts and 389 passed. The 10 dropped were 8 unsourced numbers, 1 non-verbatim quote and 1 malformed fact. Dependencies go through rules 1 and 2.

### Checks on the sentences the model writes

The headline and lead are written by the model, so they get checks of their own. A sentence is kept only if it cites real facts, every number and date in it is in the sources behind them, most of its content words appear in those facts (so a sentence that brings in new subject matter fails), and a second, stricter model pass (Haiku) agrees that the cited facts state what the sentence claims. If a sentence fails, it is dropped; if none survive, the page falls back to the highest-importance cited facts.

### A failed model call never deletes facts

An item's old facts are replaced only after the model has answered for it. If a call fails, the old facts stay, the run is recorded as `partial` with the number of items affected, and those items are retried on the next run.

### Two more checks on conflicts

A "conflict" is a place where the file disagrees with itself. The model proposes them, then code keeps only the ones that hold up:

- **At least two different items.** A fact cannot conflict with itself.
- **Independent origins.** All pages of one PDF count as one origin. Two statements conflict only if they come from different kinds of source (matter record, note, email, task, document of a different type, provider reply) or from emails with different senders. Two notes, two tasks, two bills or two pages of one PDF are not a conflict. Dropped candidates are logged as `conflict_not_independent` and `conflict_single_source`.
- **The front page shows only high-severity conflicts and the five most important open issues.** The rest are one click away.

---

## Architecture

```
Clio Manage (GET only)                       Provider replies (our DB, via share link)
   │  ClioReadOnly client                        │  stored as items with source = "portal"
   ▼                                             ▼
1. SYNC ───────────► items: one row per note, communication, task, event, expense,
   │                 document page, or provider reply. Content hash per item;
   │                 only new or changed hashes go forward.
   ▼
2. DOC TEXT ───────► PyMuPDF text per page; image-only documents flagged; photo ID image extracted
   ▼
3. EXTRACT (Sonnet) ► facts + dependencies, each citing item IDs and a verbatim evidence quote
   ▼
4. VALIDATE (code) ─► drop fake source IDs, non-verbatim quotes, unsourced numbers
   ▼
5. ANALYZE (runs over facts, not raw items)
   ├─ conflicts + open issues (Sonnet, one call per category group)
   └─ blocker graph           (Sonnet labels nodes, Python builds the graph and picks the root)
   ▼
6. EDITIONS
   ├─ Attorney: timeline, headline + lead (Sonnet, cited), deterministic sections, provider panel
   └─ Provider: attorney-approved snapshot + reply box, behind a token link with a view log
```

### Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11 or newer, FastAPI, httpx |
| Database | SQLite (outside Clio), file at `DB_PATH` |
| PDFs | PyMuPDF |
| AI | Anthropic API: `claude-sonnet-5-5` for extraction, analysis and writing; `claude-haiku-4-5-20251001` for classification |
| Frontend | React + Vite + Tailwind |
| Sign-in | Clio OAuth for the firm, share-link sessions for providers; cookies are HttpOnly |
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
- Each record is normalized to `{item_id, source, clio_type, title, text, item_date, people, raw_json}`.
- The hash covers content fields only (not `updated_at` or `etag`), so a no-op edit costs nothing.
- Re-syncs use `updated_since` plus the hash.
- "Since your last visit" uses each item's business date, not Clio's `created_at`.

### 2. Documents (`pipeline/docs.py`)

- Pages with a text layer become one item each (`doc:45:p3`), so citations open the exact page.
- Scanned documents with no text layer get a single placeholder item so the model knows they exist.
- Haiku classifies documents by name into types (photo ID, pleading, medical records, expert report, and so on). The client photo is the largest embedded image in the document classified as a photo ID.

### 3. Extraction (`pipeline/extract.py`)

Changed items only, about 10 per call, with JSON forced through tool use. The prompt includes the matter's roster (client, firm user, related contacts with IDs), so names resolve to contact IDs. Provider replies are wrapped and labeled as untrusted third-party text: they can produce facts, but they go through the same validator as everything else.

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
    "importance": 3,
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

- **Conflicts:** facts are grouped by category and checked for disagreement. A conflict is kept only if its facts come from at least two different items and from independent origins (see "Two more checks on conflicts"). Each conflict is fingerprinted by its sorted fact IDs, so re-runs don't duplicate it.
- **Open issues:** returned by the same call. These are problems the firm itself flagged. Code computes when each was first flagged, how often it was mentioned, how many days it has been open, and whether a later fact resolves it.
- **Blocker graph:** the model only maps free-text dependency labels to canonical node IDs. Python then builds the graph, picks as root blocker the unresolved node with the most dependents, and marks it **disputed** when its sources name different holders.

### 6a. Attorney edition (`pipeline/edition.py`, `product/deterministic.py`)

| Section | How it's made |
|---|---|
| Masthead: client, photo, stage, "N updates since [date]", recent items | No AI |
| Headline + lead (two sentences shown, the rest behind "more", each cited) | Sonnet, then the checks on generated sentences |
| Four big-number tiles: days held up, overdue tasks, contradictions, days since client contact. Each opens the section behind it | No AI |
| Root blocker: drawn as a chain from the stuck step to what it holds up, the holder as a pill, the asks as dots, "disputed" when sources name different holders. Quotes are one click away | Graph output |
| The money: case value, coverage, specials, lien and firm spend as bars on one axis, with the coverage cap drawn across and a dot on any disputed figure. Every bar opens its source | No AI (Haiku maps custom field names to slots once) |
| Timeline: dated facts as dots on a time axis, red where the file disagrees | Facts table, no extra AI |
| Corrections: each conflict as its two statements side by side, each labelled with its source and date and the KPI it affects; open issues with age and mention count | Analysis output |
| Still waiting: who owes what, tagged by what is awaited (surgery date, report, records or bills, lien or payment), requests sent, days silent | No AI |
| Coming up: next 21 days, overdue tasks first | No AI |
| Last client contact | No AI |
| Provider panel: per provider, share status, times opened, last opened, new replies, updates waiting to be shared; reply inbox | No AI |
| Source viewer with highlighted evidence + Clio link | Stored source IDs |
| Full file, filterable | No AI |

The first view is the header, the headline and lead, the root blocker and the four tiles. Corrections, still waiting, coming up, the timeline, providers and run details sit in collapsed sections whose summary line shows a count, in red when something is overdue, conflicting or newly replied.

The headline and lead are cached by fact-table version and visit date. A page load never waits on the model: on a cache miss the page shows the no-AI front page (the top cited facts) at once, the headline is written in the background, and the page refreshes itself when it is ready.

### 6b. Provider edition (`product/provider.py`)

Haiku classifies the matter's relationships by role, and each treating provider gets their own page. The provider is asking six questions, and each section answers one of them:

| Provider question | Section | Source |
|---|---|---|
| "Is this case even still alive?" | Case status, stage, date of last activity | Matter + latest item date |
| "Is there coverage behind the case?" | Coverage: confirmed or not yet confirmed. **Held back automatically while a coverage conflict is open.** | Custom fields + conflicts |
| "What does the firm need from my office?" | Open requests to this provider: what, when first asked, how many times asked, each with a reply field. Built only from facts marked `shareable`, and grouped by what is awaited instead of one row per sentence | Request facts + dependencies held by this contact |
| "Is my patient still showing up?" | Treatment on file: the client's last reported attendance (with date) and upcoming treatment scheduled with this provider | Treatment facts + calendar |
| "I'm treating with one eye closed" | Other treatment on file: names and specialties of the other treating providers | Relationships |
| "Tell me when the case moves" | "N updates since your last view" + recent updates | Snapshot + view log |

Two more sections:

- **What your patient told us.** Shown only when this provider is a holder on a disputed root blocker. It contains the other side's statement, quoted with its date, and never the provider's own statement or the firm's internal note. For example, the client saying he will schedule whenever the office calls. This section is not AI-written; it is the cited fact itself.
- **Not shared.** Liability, valuation, strategy and corrections are listed by name as locked, so the provider can see that limits exist.

**Attorney controls.**

- **Review screen:** one toggle per section. The defaults share status, requests, treatment and updates. Coverage, other treatment and "what your patient told us" are off until the attorney turns them on.
- **Create share link:** a random token (`secrets.token_urlsafe(32)`), a 30-day expiry and a revoke button.
- **Snapshot model:** the provider page shows a frozen snapshot of the approved sections. When the case moves, the attorney sees "2 new updates for McCulloch" and clicks **Refresh share** to re-approve. Nothing reaches a provider without an attorney's click.
- **View log:** one view is logged per provider session, so reloading the page does not inflate the count. The provider panel shows "Opened 2 times, last Sep 30."
- **Revoke:** revoking a share ends its provider sessions at once.

### 6c. Provider replies (`product/replies.py`)

The reply box is what turns visibility into communication.

- Each open request on the provider page has structured fields (a date, a "sent on" date, a short note), plus one free-text box. The fields come from the request, not from a hardcoded form.
- Replies are saved to `provider_replies` in our database and shown in the attorney's provider panel as "McCulloch replied: surgery set for Nov 12." The attorney then enters the answer in Clio by hand. Brief does not write to Clio.
- Each reply is also stored as an item with `source = "portal"`. It goes through extraction and validation like any Clio item, so it can update the headline and clear the root blocker on the attorney's page.
- One submission is one portal item, even when it fills in two fields, so the model reads it as a single answer. The item names the request it answers ("Surgery date"), not an internal ID.
- **Safety limits:** a token can only answer the open requests on its own share, and only from a browser holding the provider session for that link. Only the fields that request offers are accepted, and date fields must be dates. Reply text is length-capped, rendered as plain text, and labeled untrusted in prompts.

### 6d. Sign-in and sessions (`product/sessions.py`, `pipeline/auth.py`)

| | Firm side | Provider side |
|---|---|---|
| How a session starts | Clio OAuth sign-in. The session is created in the OAuth callback, the one moment the user's identity is proven | Opening a live share link |
| What it unlocks | Every `/matters`, `/items`, `/shares` and `/config` route. Without a session these return 401 and the app shows the sign-in screen | That one share's page and its reply box. Nothing on the firm side |
| Lifetime | 12 hours, or 2 hours idle | 12 hours, or 30 minutes idle |
| Ends early when | The user signs out, or signs out their other sessions | The attorney revokes the share |

- Cookies are HttpOnly and SameSite=Lax. The database stores only a SHA-256 of the cookie value.
- "Since your last visit" is kept per signed-in Clio user, so each person gets their own front page.
- Each person's Clio token is stored under their own login. The OAuth state is bound to the browser that started the login.
- With `CLIO_SOURCE=fixture` the sign-in screen also offers "Continue with the seed file", which signs in as the fixture user. That route does not exist outside fixture mode.
- `AUTH=off` turns the firm-side check off for local debugging.

### What happens when something changes

**A note changes in Clio:**

1. The sync finds one changed hash.
2. Facts sourced from that item are deleted.
3. That one item is re-extracted.
4. The analysis passes re-run over facts.
5. The edition cache is invalidated.

**A provider replies:**

1. The reply is saved and shown in the attorney's inbox right away.
2. It becomes one new portal item and is extracted.
3. The analysis passes re-run over facts. If the reply answers the root blocker, the blocker resolves and the headline changes.

In both cases nothing else is re-read.

---

## Data model (`schema.sql`)

```sql
items(item_id PK, source, clio_type, clio_id, title, text, item_date, people_json, hash, first_seen_at, last_synced_at, raw_json)
documents(doc_id PK, matter_id, name, folder, received_at, version_key, pages, text_pages, image_only, doc_type, photo_path)
facts(id PK, text, category, event_date, entities_json, source_ids_json, evidence, audience, importance, is_open_issue, run_id)
dependencies(id PK, blocked, waiting_on, holder, node_blocked, node_waiting, source_ids_json, evidence, run_id)
blocker_nodes(matter_id, node_id, label, resolved_by_fact, PRIMARY KEY(matter_id, node_id))
conflicts(id PK, fingerprint UNIQUE, fact_ids_json, topic, explanation, severity, kpi_affected, status)
issues(id PK, topic, fact_ids_json, first_flagged, last_mentioned, mentions, resolved_by_fact)
editions(cache_key PK, matter_id, headline_json, lead_json, created_at)
runs(id PK, matter_id, started_at, finished_at, items_changed, facts_kept, facts_dropped, drop_reasons_json, input_tokens, output_tokens, status, error)
meta(matter_id, key, value_json, PRIMARY KEY(matter_id, key))
visits(user_id, matter_id, last_visit_at, PRIMARY KEY(user_id, matter_id))
shares(token PK, matter_id, provider_contact_id, sections_json, snapshot_json, created_at, refreshed_at, expires_at, revoked)
share_views(token, viewed_at, ua_hash)
provider_replies(id PK, token, provider_contact_id, request_ref, field, value, note, created_at, status)
sessions(sid_hash PK, kind, user_id, user_name, token, ua_hash, created_at, last_seen_at, expires_at, revoked)
clio_tokens(user_id PK, access_token, refresh_token, expires_at, is_service, updated_at)
oauth_tokens(id PK, access_token, refresh_token, expires_at)
```

One database file holds one matter, so the item, fact and analysis tables carry no matter column. The pipeline writes `items`, `documents`, `facts`, `dependencies`, `blocker_nodes`, `conflicts`, `issues`, `editions`, `runs` and `meta`. The product side writes `visits`, `shares`, `share_views`, `provider_replies` and `sessions`. `oauth_tokens` is the older single-token table, kept so an existing login migrates into `clio_tokens`.

## API routes

```
Sign-in
GET  /auth/clio/login                    GET  /auth/clio/callback        starts the firm session
GET  /auth/me                            who is signed in, and their active sessions
POST /auth/logout                        ?everywhere_else=true signs out the other sessions
POST /auth/dev/login                     fixture mode only

Firm side (needs a firm session)
GET  /config                             the matter this instance serves
POST /matters/{id}/sync                  run sync + pipeline, return run stats
GET  /matters/{id}/edition?since=        the front page
GET  /matters/{id}/timeline
GET  /matters/{id}/photo                 client photo
POST /matters/{id}/visit                 mark as read for the signed-in user
GET  /items/{item_id}                    source viewer
GET  /matters/{id}/items                 full file
GET  /matters/{id}/providers             provider panel data
GET  /matters/{id}/providers/{cid}/review   review screen: every section, the toggles, the current share
GET  /matters/{id}/shares                POST /matters/{id}/shares
POST /shares/{token}/refresh             POST /shares/{token}/revoke
GET  /matters/{id}/replies               attorney inbox
POST /matters/{id}/replies/ack           mark replies as read
GET  /matters/{id}/runs                  token usage and drop counts

Provider side (the share token, then a provider session)
GET  /p/{token}                          provider page; starts the session and logs one view
POST /p/{token}/reply                    provider answers an open request

GET  /                                   the built frontend, when frontend/dist exists
```

## Repo layout

```
backend/
  pipeline/   clio.py  fixture_clio.py  auth.py  sync.py  docs.py  llm.py  extract.py  validate.py
              analyze.py  graph.py  edition.py  run.py
  product/    deterministic.py  provider.py  replies.py  sessions.py  bridge.py  ai.py
  db.py  schema.sql  main.py
frontend/
  src/pages/       AttorneyEdition.jsx  ProviderReview.jsx  ProviderPage.jsx  FullFile.jsx
  src/components/  Visuals.jsx  Timeline.jsx  BlockerCard.jsx  SourceViewer.jsx  ProviderPanel.jsx
                   ProviderSections.jsx  ReplyBox.jsx
tests/        test_validate.py  test_pipeline.py  test_independent.py  test_extraction_failure.py
              test_generated_prose.py  test_auth.py  test_sessions.py
dev/          fixtures/ (offline test data)
```

- `product/bridge.py` is the one place the product side calls the pipeline: `run_pipeline(matter_id)` and `build_edition(matter_id, since)`.
- `product/ai.py` holds the two Haiku classifications the product side uses (custom field names to KPI slots, relationships to roles), with keyword fallbacks.
- `pipeline/fixture_clio.py` serves the seed file through the same interface as the live Clio client.

---

## Setup

```bash
# 1. Environment
cp .env.example .env
# CLIO_CLIENT_ID, CLIO_CLIENT_SECRET, MATTER_ID (the number after /matters/ in Clio's URL)
# CLIO_REDIRECT_URI=http://127.0.0.1:8000/auth/clio/callback   (Clio rejects "localhost"; register this exact URI)
# ANTHROPIC_API_KEY, and ANTHROPIC_WORKSPACE_ID if the key is not scoped to a workspace
# DB_PATH=brief.db (a separate file from Clio; one matter per file)

# 2. Backend
pip install -r requirements.txt
uvicorn backend.main:app --reload

# 3. Connect Clio (read-only scopes) and sign in: open http://127.0.0.1:8000/auth/clio/login

# 4. Run the pipeline for a matter
python -m backend.pipeline.run --matter-id $MATTER_ID

# 5. Frontend: build it and the backend serves it at http://127.0.0.1:8000
cd frontend && npm install && npm run build
# (or `npm run dev` for hot reload on :5173, which proxies to :8000)

# Tests: 29 of them, no network or API key needed; the model is scripted
python -m pytest -q
```

After step 3 you are signed in as your Clio user and land on the front page. The firm side returns 401 until then. To create a provider link, open a provider under Providers, choose the sections and click **Create share link**; open that link in a private window to see it as the provider does.

Offline, with no Clio account: set `CLIO_SOURCE=fixture` and `SEED_PATH=<path to sapini-clio-data.json>`. Sync then reads the seed file through the same code path. `python -m backend.pipeline.run --matter-id 1 --fixture-facts` loads a small hand-written facts file (`dev/fixtures/facts.json`) instead of calling the model. `--reextract` sends every stored item through the model again, e.g. after a failed run. In fixture mode the sign-in screen offers "Continue with the seed file", so no Clio account is needed. `AUTH=off` skips sign-in entirely for local debugging.

---

## Models and cost per case

| Step | Model |
|---|---|
| Fact + dependency extraction, conflicts, open issues, blocker labels, headline + lead | `claude-sonnet-5-5` |
| Document, role and custom field classification | `claude-haiku-4-5-20251001` |

Every API call logs its token usage to the `runs` table.

| Run | Input tokens | Output tokens | Cost |
|---|---|---|---|
| First full digest of Sapini (525 items, 389 facts kept) | 493,928 | 80,819 | about $1.80 |
| Provider reply (1 new item, then analysis re-run) | about 46,000 | about 8,000 | about $0.17 |

Measured on the live Sapini matter and read from the `runs` table. Cost is at Sonnet 5.5 list prices ($2 in / $10 out per million tokens); input counts cached tokens at full price, so the real figure is a little lower. The small Haiku classification calls (document types, relationship roles) are not included and are a fraction of a cent.

The full digest runs once per case. After that, only new or changed items are re-extracted, whether they come from Clio or from a provider reply. Extracting a new item is cheap; most of the cost of an update is re-running the conflict, issue and blocker analysis over all facts. A cheaper update would skip that step when no new fact is kept. Opening the page again costs nothing while the facts and the reader's last-visit date are unchanged: the headline and lead are cached on those.

---

## Not built / known limits

- OCR of the scanned medical records bundles (they appear as placeholder items only).
- Email or SMS notifications to providers. Providers see "updates since your last view" when they open their link.
- Per-fact sharing controls. Sharing is controlled per section.
- **Provider page content.** The model labels each fact `shareable` or `internal`, and a provider page can only show `shareable` facts, but that label is model-assigned and can be wrong. Requests on a provider page are built only from `shareable` facts and grouped by what is awaited, using keyword rules for the common asks (surgery date, report, records or bills, lien or payment); a request outside those falls back to its own sentence. The attorney's review screen is the safeguard; do not share a page without reading it.
- **Source links in Clio.** The source viewer inside Brief opens the exact item and page with the quote highlighted, but the "open in Clio" link goes to the matter, not to the individual note or document, because we did not confirm Clio's per-item URLs.
- **Clio accounts.** Each person's Clio token is stored under their own login and never replaced by someone else's. Background work (a provider reply triggering a re-read) runs as the first account that connected.
- **Authors of notes.** Clio does not give us a note's author in the fields we read, so two notes by different people count as one origin when checking for conflicts. Emails are checked by sender.
- **Model variation.** Conflicts and open issues come from a model and vary somewhat between runs. The headline is cached per state of the file, but a rerun can pick different conflicts.
- **Client photo** is the largest image in the photo-ID PDF, so it is the whole ID card, not a cropped face.
- **Headline and lead** fall back to the highest-importance cited facts, without the model, when no API key is set or the model's sentences fail the number check.
- **Single matter.** One database file holds one matter. Running several matters means one database per matter. There is no matter picker in the app.
- **Provider identity.** The share link is the provider's only credential. Anyone it is forwarded to can open it and reply as that office until it expires or is revoked. Verifying the provider by an emailed code is the next step; it needs the email sending that is not built.
- **Sessions are local.** Sessions live in the same SQLite file and the app runs on localhost over http, so cookies are not marked Secure.
- **Slow document downloads.** A Clio document download that times out stops the sync. Run the pipeline again and it continues from what is already stored.
- **Keyword fallbacks.** When no API key is available, mapping of custom-field names to KPI slots and roles falls back to keyword rules. With a key, Haiku does it.
