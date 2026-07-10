---
paths: ["backend/app/router/**"]
---

# Auto-router safety (goal 5)

The router is the **only runtime LLM** in the system. It reads a captured thought and
*proposes* where it goes; deterministic code *disposes*. Read this before editing anything
under `backend/app/router/`.

## The contract (LLM-proposes / code-disposes)

- **No write lives in the LLM path.** `classifier.py` returns a `RouterClassification` and
  nothing else — it imports the Anthropic SDK, never `app.writes` or `app.google`. Every Google
  write is in `service.py`. If you find yourself importing a writer into `classifier.py`, stop.
- **Insert-only blast radius (goal 7).** The router's *entire* Google-write dependency set is
  exactly **`{create_task, reschedule, append_note}`** — the AST test pins it.
  - **`writes_svc.create_task`** (task content) + **`writes_svc.reschedule`** (the g4a date path to
    set the new task's due date — non-destructive metadata).
  - **`writes_svc.append_note`** (goal 7): a high-confidence `note` is appended **insert-only** to
    the top of the configured notes Doc under an H3 timestamp. **Never a Docs delete or
    overwrite** — `append_note` only inserts. **Goal 7c amendment:** the Doc entry now carries
    **one LLM-authored line** — the classifier's `summary` one-liner (bold, between the timestamp
    and the body). The *raw text stays verbatim*; the summary is the only generated line. The write
    set and insert-only contract are **unchanged** (still `append_note`, no new writer); a
    missing/empty summary degrades to the goal-7 shape.
  Routing must **NEVER** reach `delete_task`, the complete/uncomplete status write, `update_content`,
  or any `files.delete` / `files.update` content rewrite. The router is **not** a sanctioned
  `delete_task` caller (writes.md's two callers stand; the router is not a third).
- **Confidence gate.** A `task` or `note` is auto-acted only when `confidence >= CONFIDENCE_THRESHOLD`
  (`config.py`). Below threshold → review queue, never an auto-write.
- **Schema gate.** The classifier output must validate against `RouterClassification`. A model error,
  refusal, or unparseable result collapses to `unknown` (`classifier.py` returns
  `unknown_classification()` and never raises) → review.
- **Allowed-destination gate.** `task` and (from goal 7) `note` have live writers. A `note` writes to
  the Doc when `NOTES_DOC_ID` is set, else it degrades to **kept-local + a logged warning** (never a
  crash, never a blocked pipeline). `event` and `unknown` are never auto-acted — they go to review
  (calendar is read-only v1). **Doc/folder IDs come from config only, never from LLM output** — the
  router proposes a destination *class*; `service.py` picks the doc (`_notes_doc_config`).
- **Route-once / idempotency.** `route_entry` no-ops unless `routing_state == UNROUTED`; routing flips
  the state, so the scheduled job and `route-now` never re-route or double-create. A created task is
  not re-captured (no capture↔route loop).

## Layering

- `classifier.py` — the runtime LLM (structured output). No writes, no DB.
- `service.py` — deterministic dispose: reads the classification, performs/withholds writes,
  persists `routing_state`, builds review items. A Google-write failure leaves the entry `UNROUTED`
  (re-routable) and raises `ApiError` — never swallowed, never half-written.
- `scheduler.py` — in-process periodic `route_unrouted` (no Celery). `route-now` calls the same fn.
  **Goal 7c:** capture routes **inline** in `POST /scratch` (`route_entry` runs in the request; the
  response carries the routed state). The scheduler is demoted to a **retry backstop** for entries
  inline routing left `UNROUTED` — default interval stretched to ~15 min. Capture is persisted before
  routing, so a routing failure never loses it (2xx, entry `UNROUTED`).
- `evals/` — the labelled set + the scored runner; `score()` is a pure function (unit-tested without
  the API). The gate: clear-case destination accuracy ≥ 0.90 **and** zero task-class false positives
  **and** zero ambiguous cases auto-written. Notes are graded on **destination only** — the body is
  verbatim (deterministic) and the timestamp/top-insertion are unit-tested, not eval-graded. The
  goal-7c `summary` one-liner is **not eval-graded** (cosmetic, spot-checked — not a write decision).

## Model tiering

The router runs on a **small/cheap model** (`config.ROUTER_MODEL`, default `claude-haiku-4-5`) — this
is classification + light extraction, not reasoning. That is a product decision, not a compromise.

## Goal 9: hierarchy-aware note routing

- **Hierarchy in the prompt, path-not-id contract.** The classifier's system prompt gains a
  **dynamic per-user section** (`classifier._filing_section`): the user's notes hierarchy rendered
  as **paths only** (e.g. `conversations/john/growth`) plus the default-Doc fallback rule. **Drive
  ids NEVER enter the prompt and the LLM NEVER emits an id** (ADR layer 3 stands) — it proposes a
  `target_doc_path`; deterministic code (`settings.service.resolve_note_target`) maps path → stored
  id (case-insensitive exact leaf match; unknown/null → the default Doc). `route_entry` passes the
  leaf paths via `classify(text, doc_paths)`.
- **Doc choice never gates review.** The confidence gate is still about note-vs-task-vs-unknown; a
  wrong-doc guess is low-stakes (the note is still filed, its path shows in RECENT). Confirm-as-note
  re-validates a non-null `target_doc_path` against the index (**422** `unknown_doc_path` on a stale
  path — the dropdown only offers real leaves).
- **The 2nd verbatim relaxation.** The body written to the Doc is `note_text` — the raw capture with
  **only the routing prefix stripped**, under an emphatic preserve-verbatim prompt instruction and a
  deterministic **truncation guard** (`service._guarded_note_body`: a missing/empty/`< 50%`-length
  `note_text` falls back to the **raw text verbatim** — a mangled extraction never silently loses
  words). The one-liner (`summary`, the H3 headline) and the optional `keywords` (H5) are the only
  other LLM-authored lines; both degrade to skip when absent (the timestamp falls back to H3).
- **`routed_doc_path`** (nullable, on `ScratchEntry`) records where a `kept_note` landed (null =
  default Doc), set on both auto-route and confirm-as-note; `GET /scratch` returns it.
- Write set unchanged: still exactly `{create_task, reschedule, append_note}` (AST-pinned). The
  metadata rename (`docs.rename_file`) is **settings-path-only** and never reachable from the router
  (AST-asserted). Eval gate adds **doc-path accuracy ≥ 0.9** on the clear hierarchy subset; keywords
  + the one-liner stay un-graded.

## Goal 8: per-user routing

Routing is per-user. `route_entry(session, user, creds, entry)` /
`route_unrouted(session, user, creds)` / `confirm_review(session, user, creds, item_id, ...)` take
the current `User` + their live `creds`; every Google call uses those creds and every
`scratch_entry` / `review_item` is written/read with `user_id`. The notes Doc is the **user's own**,
resolved via `app.settings.service.ensure_notes_target(session, creds, user_id)` (app-created folder +
Doc on first need) — the `NOTES_DOC_ID`/`NOTES_FOLDER_ID` env vars and the "kept-local when unset"
degrade are gone; a note always has a home. The scheduler backstop iterates users and loads each
user's creds (`app.google.auth.load_credentials`) per tick. The insert-only write set
`{create_task, reschedule, append_note}` and the AST test are unchanged.
