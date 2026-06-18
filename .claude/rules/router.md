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
- **Create-only blast radius.** The only Google task writes reachable from routing are
  **`writes_svc.create_task`** (content) and **`writes_svc.reschedule`** (the g4a date path, to set
  the new task's due date — non-destructive metadata). Routing must **NEVER** reach
  `delete_task`, the complete/uncomplete status write, or `update_content`. The router is **not** a
  sanctioned `delete_task` caller (writes.md's two callers stand; the router is not a third).
- **Confidence gate.** A `task` or `note` is auto-acted only when `confidence >= CONFIDENCE_THRESHOLD`
  (`config.py`). Below threshold → review queue, never an auto-write.
- **Schema gate.** The classifier output must validate against `RouterClassification`. A model error,
  refusal, or unparseable result collapses to `unknown` (`classifier.py` returns
  `unknown_classification()` and never raises) → review.
- **Allowed-destination gate.** Only `task` has a live writer. `note` is kept locally; `event` and
  `unknown` are never auto-acted — they go to review (calendar is read-only v1).
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
  that would auto-write.

## Model tiering

The router runs on a **small/cheap model** (`config.ROUTER_MODEL`, default `claude-haiku-4-5`) — this
is classification + light extraction, not reasoning. That is a product decision, not a compromise.
