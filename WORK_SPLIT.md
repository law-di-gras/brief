# Work split: Brief

Internal build plan for the two-person team. Architecture and workflow are in `README.md`.

**Deadline: 4:00 PM, hard close.** Submit by 3:50. Submission order is presentation order.

## The contract (both, first 20 minutes)

1. Freeze `schema.sql`. Changes after this are additive and announced.
2. **B** writes `dev/load_seed.py`, which loads `sapini-clio-data.json` into `items` with fake IDs.
3. **A** writes `dev/fixtures/facts.json`: about 20 facts, 2 conflicts, 1 open issue and 4 dependencies in the exact schema.
4. Folder ownership: **A** owns `backend/pipeline/`. **B** owns `backend/product/`, `frontend/` and `main.py`.
5. The only function crossing the line is `run_pipeline(matter_id) -> run_stats`, which B calls from `/sync`.

A only writes to the database. B only reads from it.

## Person A: data and intelligence (~5h45), owner: [name]

| Task | Time |
|---|---|
| Contract + facts fixture | 0:20 |
| OAuth, read-only Clio client, `llm.py` wrapper that logs tokens | 0:45 |
| Sync: normalize, `item_date`, hashing, `updated_since` | 0:45 |
| Documents: download, page text, scan placeholders, doc classification, photo | 0:40 |
| Extraction + `validate.py` + drop logging | 1:15 |
| First full run, tune prompts (generic only) | 0:30 |
| Analysis: conflicts, open issues, blocker graph, ranking | 1:15 |
| Incremental test, cost numbers, README pipeline sections | 0:15 |

## Person B: product and sharing (~5h45), owner: [name]

| Task | Time |
|---|---|
| Contract + seed loader | 0:20 |
| Deterministic sections + KPI field mapping | 1:00 |
| Edition builder: headline + lead, number check, caching, visits | 0:45 |
| Attorney page: blocker card, corrections, source viewer, full file, date picker | 1:30 |
| Provider side: roles, drafts, suggested message, tokens, view log, approval queue, review screen, provider page | 1:15 |
| Polish, README product sections, 90-second video, form | 0:55 |

## Sync points

| Time | What happens |
|---|---|
| 9:20 | Contract frozen, fixtures committed |
| 10:00 | A pushes `llm.py` |
| 11:30 | A pushes `validate.py` |
| **12:00** | B switches to A's real database. Check together that real conflicts and a root blocker appear from the generic pipeline. If real facts aren't flowing, B helps A for 30 minutes. |
| 2:45 | Full end-to-end run, then the incremental test (add a note in Clio, re-sync, headline changes) |
| 3:15 | Code freeze. A writes the form answers, B finishes the video. |
| 3:50 | Submit |

## Risks to check by noon

- **Blocker labels too noisy to merge.** Fallback: show the standoff as a three-quote conflict instead of a graph.
- **Number check over-drops** ("three" vs "3"). Normalize number words or check digits only.
- **Manual Clio UI edits for the video.** Confirm with Swans they are allowed.
- **Calendar times are UTC.** Check the "coming up" day boundaries.
- **Past calendar entries are not overdue items.** Only pending tasks with a past due date count as overdue.
