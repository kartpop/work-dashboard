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
  - **`writes_svc.append_note`** (goal 7): a high-confidence `note` is appended **verbatim,
    insert-only** to the top of the configured notes Doc under an H3 timestamp. **Never a Docs
    delete or overwrite** — `append_note` only inserts.
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
- `evals/` — the labelled set + the scored runner; `score()` is a pure function (unit-tested without
  the API). The gate: clear-case destination accuracy ≥ 0.90 **and** zero task-class false positives
  **and** zero ambiguous cases auto-written. Notes are graded on **destination only** — the body is
  verbatim (deterministic) and the timestamp/top-insertion are unit-tested, not eval-graded.

## Model tiering

The router runs on a **small/cheap model** (`config.ROUTER_MODEL`, default `claude-haiku-4-5`) — this
is classification + light extraction, not reasoning. That is a product decision, not a compromise.
