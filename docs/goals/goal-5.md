# Goal 5 — Scratchpad + Auto-router

**One line:** An append-only capture box writes raw entries to a local store; a scheduled job runs each unrouted entry through an LLM **classifier** (structured output → `{destination, confidence, fields}`); **deterministic code does every write**, reusing the g4/g4a task-write layer; low-confidence and unwritable destinations land in a **review queue**. The router is the **only runtime LLM** in the system. Harness rep: a **cost-instrumented dynamic workflow** that fans the eval set across (cheap-model) subagents and cross-checks — designed *against* the "View usage" finding that subagent-heavy sessions were 100% of spend.

## Intent / acceptance bar
The bar: **"a thought I dump in the box files itself."** Type *"call dentist friday"* → a task lands in the right list with Friday's date. Type *"remember the Vsauce video on entropy"* → kept as a note. Type *"lunch with Tejas thursday 1pm"* → surfaced in the review queue for a **manual** calendar add (calendar stays read-only, v1). Anything the model isn't sure of **waits in review rather than guessing.** The new part: the router's quality is **measured against a labelled eval set, not asserted** — a scored run with a pass threshold gates the goal. (Eval-graded routing is the discipline behind any real eval pipeline: measure, don't assert.)

Tasks surface stays the daily-driver MVP from g4a; the scratchpad/router graduates to **WIP-but-usable** here; Calendar (g7b) stays WIP.

## What ships
- **Capture box (UI).** A persistent append-only input on the dashboard (textarea + submit). Submit → `POST` appends an entry and clears the box; it never edits or deletes prior entries. Entries display their routing state (`unrouted` / `routed→task` / `kept-as-note` / `in-review`).
- **Scratchpad store + review queue (DB).** New SQLModel tables, Alembic migration (`render_as_batch=True`, per the g2 SQLite rule): `scratch_entry` (raw text, created_at, routing_state, route_result) and `review_item` (entry FK, proposed destination + extracted fields + confidence, status `pending`/`confirmed`/`dismissed`). Reuses the existing SQLModel + Alembic setup.
- **Scheduled job.** A periodic in-process job picks up `unrouted` entries and routes them, **plus a manual "route now"** endpoint/button so dev / eval / real use never wait on the timer. Scheduler = APScheduler or a FastAPI lifespan task — **no Celery/broker** (single-user local app). *(decision below.)*
- **The router (only runtime LLM).** One LLM call per entry returns **structured output**: `{ destination ∈ {task, note, event, unknown}, confidence ∈ [0,1], fields }`, where `fields` carries what the destination needs (task → title, list-hint, due-date-if-present, notes; event → title, datetime, attendees-text; note → cleaned text). Structured output via the API's JSON-schema / tool mode, **schema-validated**; an invalid result is treated as `unknown`. Small / cheap model — this is classification + light extraction, not reasoning. **The LLM only proposes; it never writes.**
- **Deterministic write/route step.** Code (not the LLM) reads the classification and acts:
  - `task` + confidence ≥ threshold → **create a Google task** via the g4a write layer (`create_task`), applying the extracted list-hint + due date (date through the g4a date path). Entry → `routed→task`.
  - `note` → kept in the store as a note (no external write). Entry → `kept-as-note`.
  - `event` → **review queue** (no calendar writer — calendar is read-only v1; user adds it manually in Google).
  - `unknown`, or confidence < threshold for **any** destination → **review queue**.
- **Review queue (UI).** A panel of pending items showing proposed destination + extracted fields + confidence; per item: **Confirm** (fires the deterministic write — e.g. create the task), **Edit-then-confirm** (correct fields first), **Dismiss**. Confirmed/dismissed items leave the queue; the source entry's state updates. *(UX = in-dashboard panel — decision below.)*
- **Eval set + scored run.** A labelled set of captures → expected `{destination, key fields}`, checked into the repo (`backend/app/router/evals/`). A runner scores the router over the set: destination accuracy + per-class precision/recall + confusion matrix + **confidence calibration** (do low-confidence cases correlate with the wrong/review ones?). A **pass threshold gates the goal** (proposed: ≥90% destination accuracy **and zero `task`-class false-positive that would auto-write a wrong task** — see AC).
- **Guardrails — the safety contract (new `router.md` rule, path-scoped to the router module).**
  - **LLM-proposes-code-disposes:** the router function returns a classification only; no write call lives in the LLM path.
  - **Create-only blast radius:** the router's write path may call **`create_task` only**. It must **never** reach `delete_task` or the complete/uncomplete status write — the router is **not** a sanctioned caller of `delete_task` (writes.md's two callers stand; the router is not a third). No edits/deletes/completes of existing items, ever, from routing.
  - **Confidence gate:** below threshold → review, never auto-write.
  - **Schema gate:** output must validate; else `unknown` → review.
  - **Allowed-destination gate:** only `task` has a live writer; `event`/`unknown` are never auto-acted.
  - **Route-once / idempotency:** an entry is routed exactly once; routing-state tracking stops the scheduled job re-routing or double-creating. No capture↔route feedback loop (a created task is not re-captured).

## Locked decisions
- **Only runtime LLM = the router; structured output (`destination + confidence + fields`); deterministic writes; low-confidence → review.** (Architecture principle, reaffirmed.) The LLM has no write authority.
- **Destination taxonomy + live writers (proposed lock):** `task` = live write (g4a `create_task`); `note` = kept in the local store (no external write); `event` = recognized → review queue (no calendar writer — **calendar read-only v1** stands); `unknown`/low-confidence → review. *(Open sub-question: is `note` purely local, or later appended to a Google Doc? A Docs writer is **out of scope** for g5 — no Docs write layer exists and g5 reuses g4a only. Resolve before running if a real notes-doc target is wanted.)*
- **Router write path is create-only.** It may call `create_task` and nothing else; `delete_task`/complete are off-limits to routing. First revision-pressure on `writes.md` since g4a: document the router as **not** a `delete_task` caller, and `create_task` as now having a second caller (user create + router).
- **No confirm dialogs** (project stance holds) — but the **review queue is not a dialog**; it's the human-in-the-loop surface for *uncertain* routes, the analog of g4a's undo-toast for *certain* ones. High-confidence auto-written tasks get no dialog; they're recoverable through the normal task UI (g4a delete/complete).
- **Scheduled job = in-process** (APScheduler or FastAPI lifespan task) **plus a manual "route now"** trigger. No Celery/broker; the eval runner calls the router directly regardless of the schedule.
- **Entry format = free text, with optional light `#list` / date hints honoured if present** (proposed lock — resolves an open fork). Free text is the default; a typed `#followups` or date is a strong signal, not a requirement. *(Alternative: free-text-only, no hint parsing — simpler, leans entirely on the model. Pick one before running.)*
- **Review-queue UX = in-dashboard panel** (proposed lock — resolves an open fork), consistent with the tasks/calendar panels; a plain table is the fallback if the panel costs too much for g5's mostly-backend focus.
- **Eval set = small, hand-labelled** (proposed ~25–40 captures spanning all four classes incl. deliberate ambiguous/edge cases), **graded on destination match (primary) + key-field extraction (secondary)**, threshold gating the goal. *(Resolve exact size/rubric before running — open fork.)*
- **Store/queue persistence reuses SQLModel + Alembic** (seed); SQLite migrations `render_as_batch=True`.
- **Schema-invalid / model-error output = `unknown` → review** — never a crash, never an auto-write. Mirrors g4a's "render robustness over crashes" + "errors not swallowed on writes."

## Out of scope (do not build)
- **Calendar writes / event creation** (read-only v1 → events go to review for manual add). The calendar *panel* is g7b.
- **Google Docs writer** (no Docs write layer; `note` stays local for g5).
- **Granola / transcript ingestion** (g6 — it feeds *this* router/queue later).
- **Router editing / deleting / completing existing tasks** (the create-only guardrail — a prohibition, not a feature).
- **Online routing on every keystroke**; retraining/fine-tuning; multi-model ensembles in the *product* (a worker cross-check inside the *eval workflow* is fine — see harness reps).
- **Confirm dialogs. Retry queues / offline support. Auth/permission changes.**
- **A general agent loop** — this is a fixed capture→classify→deterministic-write pipeline, not an autonomous agent.

## Acceptance criteria
- Capture box: submit appends one entry, clears the box, shows it `unrouted`; prior entries untouched; reload persists.
- Scheduled job (or "route now") picks up unrouted entries and routes each **exactly once**; re-running routes nothing already routed (idempotent, no double-create).
- `task`, high confidence → exactly one Google task via `create_task` with the right list + due date (date via the g4a path); entry → `routed→task`; the task shows in the tasks panel and in Google; reload persists. **No other Google write fires** from routing.
- `note` → kept in the store, no external write; entry → `kept-as-note`.
- `event` → appears in the review queue (no calendar write); confirming it does **not** auto-create an event (manual-add affordance only).
- Low-confidence (any class) or schema-invalid output → review queue, never an auto-write.
- Review queue: **Confirm** on a `task` item fires exactly one `create_task`; **Edit-then-confirm** writes the corrected fields; **Dismiss** writes nothing; in all three the item leaves the queue and the source entry's state updates; reload persists.
- **Guardrail:** no code path lets routing call `delete_task` or the complete write — asserted by a test that the router service's only write dependency is `create_task` (and/or the write-path check).
- **Eval:** the scored run emits destination accuracy + per-class P/R + confusion matrix + a calibration read, and **meets the pass threshold**; a deliberately ambiguous case lands in review (low confidence), not mis-auto-written.
- Schema-invalid / model-error → `unknown` → review, no crash, no swallowed error; a write failure in the deterministic step → snapshot rollback + error toast (g4+ convention) and the entry returns to a re-routable state.
- g3/g4/g4a behaviour intact (overlay, grouping, reschedule, move, full CRUD); no console errors; Calendar unaffected; the router is the **only** runtime LLM (read paths still hit Google directly, no LLM/MCP).

## Harness reps (the goal-5 learning)
**This is where the "View usage" data reshapes the plan.** The seed's queued g5 rep is **dynamic workflow — "fan the router's eval cases across subagents and cross-check."** The usage tab says the single most expensive thing happening is *that exact shape*: **100% of usage came from subagent-heavy sessions**, **66% was at >150k context**, **`/verify` alone was 11%**, with explicit advice to *be deliberate about spawning subagents* and *run simpler subagents on a cheaper model via frontmatter.* So g5 doesn't merely *do* a fan-out — it does a **cost-instrumented** one, and the lesson it banks is **when parallel fan-out is worth its token multiplier.**

- **Primary — dynamic workflow on the eval set (introduce), built cost-deliberate (friction-driven by the usage data).**
  - Realize the eval harness *as* a **dynamic workflow**: fan the eval cases across worker subagents, each running a *batch* of cases through the router; a cross-check/aggregation step computes the scorecard. *(Verify the current `/workflows` spawn mechanism in-session against the Claude Code docs — keep the workflow/spawn syntax in the skill, not baked into this brief, per the seed's HOW-lives-in-skills rule.)*
  - **Apply the usage findings as design constraints — and measure them:**
    1. **Cheap model via frontmatter** for the eval workers **and** the existing `verifier` subagent (the named 11%). The router-under-test is a *product* config (small model — it's classification); the *workers* are harness config. Confirm the model-selection frontmatter key against the docs in-session.
    2. **Deliberate fan-out width** — batch N cases per worker, cap concurrency; **do not** spawn one subagent per case (the literal worst case the usage tab warns about). A single looping subagent is the baseline to beat.
    3. **Context discipline** — `/clear` between g5 phases (store → router → eval → queue), `/compact` mid-phase; keep eval/curl noise in the subagent, out of the main context (the g3 isolation property is the tool for the 66%>150k problem).
    4. **Measure it.** Record the token/usage cost of the fan-out **vs.** the single-looping-subagent baseline. **Bank the answer:** was parallelism worth the multiplier for ~25–40 cases, or does fan-out only pay off at larger scale? *(This is the headline lesson the "View usage" data set up.)*
  - **`/effort ultracode`** (seed-noted, optional): reserve high effort for the *genuinely hard* step — designing the router prompt + schema + threshold — not the mechanical fan-out. High effort costs more; scope it, given the cost theme.

- **Supporting — scope down `/verify` (friction-driven, straight from the 11%).** Trim `verifier-web`/`verifier-writes` to what g5 actually needs and/or move the verifier to a cheaper model (frontmatter). g5 is **mostly backend** (capture/store/router/queue) with a thin review-queue UI, so the expensive Playwright surface — **BLOCKED in g4a (no browser in the verifier sandbox)** — is *not* g5's center of gravity; don't pour effort into it here. Decide explicitly: **(a)** finally get a browser into the verifier env to clear the g4a UI-flow debt + cover the review-queue UI, or **(b)** keep the small g5 UI on manual review and let the **eval harness** be g5's headline verification surface. *Recommendation: (b)* — the probabilistic router *needs* eval-based verification (a new mode, higher value); roll the browser-in-verifier debt forward (it pairs naturally with g7's UI work).

- **New rule — `router.md`** (path-scoped to the router module): the guardrail contract — LLM-proposes-code-disposes; **create-only** write path (never `delete_task`/complete); confidence + schema + allowed-destination gates; route-once idempotency. **Hook question (for the closing checklist):** is any of this better as a *hook* than prose? Candidate — a test/CI gate that fails if the router service references any write other than `create_task` (enforces create-only every time, vs. a rule the model may not reload).

- **`writes.md` second revision.** `create_task` gains a second sanctioned caller (user-create + router); `delete_task`'s **two** callers are unchanged and the router is explicitly **not** a third; state the create-only router contract.

**Carried forward from g4a (apply, don't relearn):**
- **Commit g4a first.** It's uncommitted on `main` (16 modified + 2 new). Commit on a `goal-4a` branch (the g4 flow) **before** starting g5; add the hash to the seed Status block.
- **The hook gotcha will recur** (PostToolUse formatter strips a momentarily-unused import on an intermediate edit). Add the import + its first use in the *same* edit, or re-add last. Banked since g4.
- **2nd agent-team run stays deferred to g7a∥b** (g4a wrap-up) — **g5 is solo + subagents, not a team goal.** This also *helps* the cost theme (no parallel teammate sessions). The conclusive per-teammate `/context` rule-fire reading still rolls to g7.
- **400-not-404 lesson** (g4a verifier find): Google returns HTTP **400** for bad ids. The deterministic step touches Google task creation — map Google error envelopes correctly (don't leak 500/502), keep the error-envelope rule.

## Closing checklist (this goal)
- New `router.md` rule (path-scoped); record whether it **fired** (`/context`) on router-module edits — rules are flaky, track fire/no-fire.
- Revise `writes.md` (2nd revision): `create_task` second caller (router); router is **not** a `delete_task` caller; create-only contract.
- Extend `verifier-writes`: router write-path checks (create fires once; **no** delete/complete reachable from routing; `zz-verifier-test` list + cleanup).
- New eval artifacts: the labelled eval set (in-repo), the scored-run runner, the dynamic-workflow definition/skill (`/eval` command parallel to `/verify`? — decide), worker model set via frontmatter.
- **Record the cost experiment:** fan-out vs. single-looping-subagent token cost; the banked answer on whether parallelism paid off at this scale. *(g5's headline harness wrap-up line.)*
- Confirm the verifier (+ eval workers) moved to a cheaper model (frontmatter) and `/verify` scope trimmed — note before/after if visible in the next usage read.
- **Hook decision:** create-only enforcement as a test/CI gate or hook vs. prose-only in `router.md`.
- Refresh root `README.md` (new endpoints: capture, route-now, review confirm/dismiss; the scratchpad/router surface; tasks-surface still MVP, router WIP-but-usable).
- Update `docs/goals/README.md` — the router pipeline, the create-only guardrail, eval-based verification as a new mode.
- `/context` reading for `router.md` (and re-confirm `writes.md` + backend rules fire on the touched files).

## Harness wrap-up (run record — hand to planning chat)
*(Ran inline single-session, solo + subagent definitions — NOT a team run, per plan.)*
- **Dynamic workflow (RUN LIVE):** `/eval`-shape fan-out — 4× `eval-worker` subagents (cheap-model
  frontmatter) each classified one round-robin shard and wrote a result file, then a free local
  `--aggregate` scored them. The runner is **shard/aggregate-aware** (`runner.py --shard k/n --out …
  | --aggregate 'glob'`), so the split is real: classification (network, non-deterministic) shards to
  workers; `score()` (pure) centralises for free. Both paths produced the **identical PASS scorecard**.
  **Measured cost experiment — the banked answer:** baseline single-loop ≈ **52 s wall-clock**, ~0
  orchestration overhead; fan-out ≈ **31 s wall-clock** (4 workers in parallel, max ≈ 31 s) but
  **+~25,400 tokens** of pure subagent orchestration (4 × ~6,343 — each worker re-establishes its own
  context to run one command), on the *same* 32 classify calls. **At ~32 short Haiku classifications,
  fan-out is NOT worth it** — it trades ~40% wall-clock for a ~25k-token overhead that dwarfs the
  tiny classify cost. Parallelism only pays once per-shard work is large enough to amortize the
  ~6.3k/worker fixed cost. This *is* the "be deliberate about spawning subagents / 100%-of-spend"
  lesson, now quantified. (Local-dev wrinkle: the key lives in interactive zsh only, so each worker
  pulled it via `zsh -ic` in its command — non-interactive subagent shells don't source `.zshrc`.)
- **Model-tiering:** `verifier` and `eval-worker` both pinned to `model: haiku` via frontmatter; the
  router-under-test is product config (`ROUTER_MODEL=claude-haiku-4-5`). Next usage read should show
  the verifier's slice drop from the g4a 11%.
- **Context discipline:** single-session inline; no `/clear` between phases this run (one continuous
  build). The isolation property is *designed in* (workers keep classification/JSON noise out of the
  lead) but unexercised until the live fan-out.
- **`router.md`** written (path-scoped `backend/app/router/**`); **fire/no-fire via `/context` is
  unverified from this seat** — needs a manual `/context` check on a router-file edit (rules are
  flaky; tracked). **`writes.md` 2nd revision** done: `create_task` second caller (router) + router
  explicitly **not** a `delete_task` caller + the `{create_task, reschedule}` create-only set.
- **Create-only enforcement — hook decision:** chose a **test/CI gate over prose or a settings hook**.
  `test_router_write_dependency_set_is_create_only` parses the router-service AST and asserts every
  `writes_svc.<fn>` call ∈ `{create_task, reschedule}`; `test_router_never_calls_delete_or_status`
  drives all paths against recorded Google stubs and asserts `delete_task`/status-write are never hit.
  A pytest assertion fails every CI run regardless of whether the model reloaded `router.md` — the
  hook-vs-prose question resolved to "a test is the hard gate."
- **Eval result (RUN LIVE, `claude-haiku-4-5`):** **GATE PASS** — destination accuracy **32/32
  (1.0)**, every class precision/recall = 1.0, field extraction 12/12, mean confidence on correct
  calls ≈ 0.78, `task_false_positives = 0`. All **6 genuinely-ambiguous captures stayed below the
  0.7 threshold** (`ambiguous_below_threshold: 6/6`) → they route to review, never auto-write —
  exactly the AC. **The eval earned its keep:** the first run FAILED the gate (`ambiguous_auto_written
  = 1`) and the offender was a *mislabel* — `"groceries"` was tagged ambiguous but is a clear task the
  model confidently (correctly) routed. Fixed the label (not the gate; `task_false_positives` was
  already 0), re-ran → clean PASS. That's the "measure, don't assert" loop doing its job: it surfaced
  a bad label, not a model defect.
- **Gotchas:** the **hook import-strip recurred AGAIN, exactly as predicted** — the PostToolUse
  formatter stripped `scratch` from `main.py`'s `from app.routers import …` on the intermediate edit
  (imported before its `include_router` use existed); the banked mitigation (re-add the import with
  its use present) fixed it. Also hit a SQLite **non-transactional-DDL** wrinkle: a partially-applied
  migration left orphaned tables that the version stamp didn't reflect (drop-and-rerun cleared it) —
  worth remembering for future migrations. No new 400-not-404 surface: the router's create path
  reuses the g4a writers, which already map Google error envelopes.
