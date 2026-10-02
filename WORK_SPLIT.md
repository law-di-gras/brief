# Work split: Brief

Internal build plan for the two-person team. Architecture and workflow are in `README.md`.
**Keep this file and `dev/fixtures/` out of the submitted repo.**

**Re-planned at 10:45, assuming the contract and OAuth are not done yet.** If something is already done, put its time toward the cut list below. Code freeze is 3:15, and the form goes in by 3:50 (4:00 is a hard close, and submission order is presentation order). That leaves about 4h30 of build time each, so eat lunch at the desk.

---

## The contract (both, first 20 minutes)

1. Freeze `schema.sql` from the README. Changes after this are additive and announced.
2. **B** writes `dev/load_seed.py`, which loads `sapini-clio-data.json` into `items` with fake IDs.
3. **A** writes `dev/fixtures/facts.json`: about 20 facts, 2 conflicts, 1 open issue and 4 dependencies in the exact schema.
4. Folder ownership: **A** owns `backend/pipeline/`. **B** owns `backend/product/`, `frontend/` and `main.py`.
5. Two functions cross the line, both owned by A and called by B:
   - `run_pipeline(matter_id) -> run_stats`, called from `/sync` and after each provider reply
   - `build_edition(matter_id, since) -> edition_json`, called from `/edition`

A writes the pipeline tables. B writes only `visits`, `shares`, `share_views` and `provider_replies`.

---

## Person A: data and intelligence (~4h35), owner: [name]

| Task | Time |
|---|---|
| Contract + facts fixture | 0:20 |
| OAuth, read-only Clio client, `llm.py` wrapper that logs tokens | 0:30 |
| Sync: normalize, `item_date`, `source`, hashing, `updated_since` | 0:30 |
| Documents: page text, scan placeholders, Haiku doc classification, photo | 0:25 |
| Extraction + `validate.py` + drop logging | 0:55 |
| First full Sapini run, tune prompts (generic only) | 0:20 |
| Analysis: conflicts + open issues (one call), blocker graph in `graph.py` | 0:50 |
| `edition.py`: headline + lead, number check, caching | 0:25 |
| Portal items: `run_pipeline` reads new `provider_replies` as items | 0:10 |
| Cost numbers from `runs`, check README claims are true | 0:10 |

After the freeze, A writes the form answers.

## Person B: product and provider side (~4h30), owner: [name]

| Task | Time |
|---|---|
| Contract + seed loader | 0:20 |
| Deterministic sections: masthead, KPIs (Haiku maps custom fields once), still waiting, coming up, last client contact, firm spend | 0:45 |
| Attorney page: headline + lead, timeline strip, blocker card, corrections, source viewer, simple full-file table | 1:20 |
| Provider side: role classification, `provider.py` sections, tokens, snapshot, refresh/revoke, view log, review screen (section toggles), provider page | 1:05 |
| Replies: `provider_replies`, reply box, `POST /p/{token}/reply`, attorney inbox | 0:30 |
| Provider panel on the attorney page (opens, last opened, new replies, "N updates to share") | 0:15 |
| Polish before the freeze | 0:15 |

After the freeze, B records the 90-second video.

---

## Sync points

| Time | What happens |
|---|---|
| 11:05 | Contract frozen, fixtures committed |
| 11:30 | A pushes `llm.py` |
| 12:30 | A pushes `validate.py` |
| **1:15** | **Hard checkpoint.** B switches to A's real database. Check together that real conflicts and a root blocker appear from the generic pipeline. If real facts aren't flowing, B stops and helps A for 30 minutes. |
| 2:00 | A pushes `edition.py`, B wires in the headline and lead |
| 2:45 | End-to-end test, which is also the video ending: create a share for one provider, open the link, submit a reply, run the pipeline, watch the blocker clear and the headline change |
| 3:15 | Code freeze. A writes the form, B records the video. |
| 3:50 | Submit |

---

## 90-second video (B records, A narrates or reviews)

| Time | Shot |
|---|---|
| 0:00–0:10 | Hook line over the Clio tab screen |
| 0:10–0:35 | Attorney front page: timeline, headline, click a sentence to show its source |
| 0:35–0:50 | Root blocker marked disputed, coverage conflict badge on the KPI |
| 0:50–1:10 | Review screen, create share link, provider page with coverage held back and the open requests |
| 1:10–1:25 | Provider types a surgery date, re-sync, blocker clears and the headline changes |
| 1:25–1:30 | Trust rules on screen, closing line |

---

## Cut list (cut in this order if behind)

1. Full-file view
2. Client photo
3. Red markers on the timeline (keep the plain timeline)
4. Other treatment on file
5. Open-issue aging (keep conflicts)
6. "What your patient told us"

**Never cut:** source links and the validator, the root blocker, the provider share link and view log, and the reply box. The reply box is what covers point 02 of the challenge.

---

## Risks to check by the 1:15 checkpoint

- **Blocker labels too noisy to merge.** Fallback: show the standoff as a three-quote conflict instead of a graph.
- **Number check over-drops** ("three" vs "3"). Normalize number words or check digits only.
- **Reply never reaches the attorney page.** Test that a portal item gets extracted and that its fact can resolve a dependency, not just appear in the inbox.
- **Prompt injection through the reply box.** Submit "ignore previous instructions" as a reply once and confirm nothing changes except one dropped or harmless fact.
- **Calendar times are UTC.** Check the "coming up" day boundaries.
- **Past calendar entries are not overdue items.** Only pending tasks with a past due date count as overdue.
