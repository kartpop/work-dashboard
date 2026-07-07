# Goals

Read the brief for the active goal (`goal-N.md`) before starting work. One line each:

> **Objective shift (from goal 6):** the primary objective is now **prod-usability for the owner's
> daily personal use** — ship the MVP surface, then keep it reliable. Harness learning is secondary:
> no goal introduces a capability for its own sake; `.claude/` files are updated at the end of each
> goal, friction-driven, via the closing checklist below. Goals 6–7 are the MVP set; Granola,
> layout-prefs/calendar polish, and the plugin capstone move behind them. An actual deployment goal
> (hosting + Postgres) is deliberately unwritten until the MVP features settle — local-first for now.

- **goal-0 — Harness bootstrap** *(done)*: repo skeleton, lean CLAUDE.md, path-scoped backend/frontend rules, Google Workspace MCP wired.
- **goal-1 — Read-only dashboard** *(done)*: backend OAuth + Google API client modules; FastAPI endpoints for Tasks (all lists) and upcoming Calendar; React panels. No writes, no overlay, no AI.
- **goal-2 — Task overlay** *(done)*: custom rank + group-by-date (per-list, IST buckets) stored in a local DB keyed by composite `(tasklist_id, task_id)`; within-bucket drag-to-reorder (midpoint rank); `GET /tasks` merge + `PATCH .../overlay`. No AI, no Google writes. *(A priority field was added here and removed in goal 3.)*
- **goal-3 — Task grouping & ordering** *(done)*: drop priority; overlay-only **user groups** inside each `(list, date-bucket)`; drag to reorder / group / ungroup within a bucket; all optimistic. API: date-bucket key `groups`->`buckets`, an item is a task or a group. Read-only on Google (overlay writes only).
- **goal-4 — Write-back I: reschedule & move** *(done & verified; first Google writes, was goal 6, narrowed)*: reschedule via cross-bucket drag (due-date change, group-aware drop — only the dragged task's row changes); move to another list via menu (insert-then-delete, overlay row migrates to the new composite key). Optimistic, snapshot-rollback on failure, idempotent, **no confirm dialogs**. *(Two move-menu bugs surfaced in manual use — the move works, but its menu is clipped by the group boundary and the destination insert isn't optimistic; both fixed in 4a.)*
- **goal-4a — Write-back II: full task CRUD (tasks MVP)** *(done)*: create / edit (title + notes) / **complete-uncomplete** / delete tasks; **arbitrary-date picker** (reuses reschedule); **Overdue rollup** (render-only, top of each list); **manual refresh**; **subtask render-robustness** (flat); rename task lists; fixed the g4 move-menu (portal escapes the group clip + optimistic destination via insert-from-response). All Google content writes. **No confirm dialogs** — completion writes immediately with an undo-toast, delete defers behind a ~5s undo-toast (Undo = zero Google writes). New endpoints: `POST /tasks/{list}`, `PATCH /tasks/{list}/{task}` (title/notes/status), `DELETE /tasks/{list}/{task}`, `PATCH /lists/{id}`. `delete_task` now has **two** sanctioned callers (move-delete + user delete). **From this goal the tasks surface is a daily-driver MVP** (real use); Calendar & Scratchpad stay WIP. *(Executed inline, single-session — the documented 2nd agent-team run was deferred.)*
- **goal-5 — Scratchpad + Auto-router** *(done; brief `goal-5.md`)*: append-only capture box + local store (`scratch_entry` / `review_item`, new Alembic migration); in-process scheduler (+ manual `route-now`); an LLM classifies each entry as structured output → `{destination, confidence, fields}` — the **only runtime LLM** (small/cheap `claude-haiku-4-5`). Destinations: `task` = live write via the g4a layer (**create-only** — the router is *not* a `delete_task` caller; `create_task` gains a 2nd caller; its write set is exactly `{create_task, reschedule}`); `note` = kept local; `event` → review queue (calendar read-only v1, manual add); `unknown`/low-confidence → review. **Deterministic code does every write; the LLM never writes.** Ships a scored, threshold-gated eval set (`app/router/evals/`) + guardrails (LLM-proposes/code-disposes, confidence + schema + allowed-destination gates, route-once idempotency), the `router.md` rule, the `writes.md` 2nd revision, and the `/eval` cost-instrumented dynamic-workflow harness rep. **Eval-based scoring is g5's headline verification mode** — the probabilistic router is *measured, not asserted*.
- **goal-6 — MVP layout: pinned lists + cross-list drag** *(done; brief `goal-6.md`)*: full-width top row `My Tasks | Follow-up | Scratchpad` (scratchpad rightmost, enlarged); pinned lists static-in-code by title (`PINNED_LIST_TITLES`, missing title → empty-column hint); drag tasks **between** the pinned lists under one shared `DndContext` (`DndListGroup`) — the g4 `move` write layer gained optional `due_date` **and** `group_id` so a cross-list + cross-bucket + into-group drop is one orchestrated write; all other lists in a collapsed **Other tasks** section (each its own single-list context); calendar below the fold. No `ui_prefs` yet. *(6a daily-use polish: the top row is one **resizable** grid — 3 columns default 30/30/40 with a drag handle between each pair, ephemeral widths, stacks below 1080px; pinned rows drop their per-row date to just the picker icon — the bucket header carries it, with Today/Tomorrow headers gaining weekday + `dd/mm/yyyy`; long titles ellipsize with the full text on hover. `DndListGroup` became children-based so a resize handle can sit between the pinned columns. Playwright is now a backend dev dep — browser build still needs a one-time `uv run playwright install chromium`.)*
- **goal-7 — Scratchpad v2: bullet editor + notes → Google Doc** *(brief `goal-7.md`)*: Docs-like bullet ergonomics in a plain textarea (`- ` bullets, Enter continues, Tab/Shift+Tab indent/outdent, **Shift+Enter captures** the whole editor as ONE entry and clears it); `note` graduates from kept-local to a **second live writer** — verbatim append into one env-configured Google Doc (`NOTES_DOC_ID`), inserted at the **top** under an H3 timestamp (`6-July-2026, 8:41 PM IST`). Router write set becomes exactly `{create_task, reschedule, append_note}` (insert-only; still never delete/status/content edits) — `router.md`, `writes.md`, the AST write-dependency test, and the eval gate all get matching revisions. Needs the Docs OAuth scope (one-time re-auth).
- **goal-8 — Granola** *(was 6)*: fetch transcripts via MCP, extract action items, feed the same router/queue.
- **goal-9 — Layout prefs ∥ Calendar** *(was 7, shrunk; parallel worktrees)*: *(a)* the residue goal-6 didn't absorb — list-visibility chooser + `ui_prefs` persistence + drag into non-pinned lists. *(b)* calendar panel polish: date-bucketed (IST), one-click Meet link, today + tomorrow.
- **goal-10 — Plugin capstone** *(was 8)*: package skills + verifier + hook + `/verify` as the `work-dashboard-dev` plugin.
- **goal-11 — Dependency / advanced views** *(optional, deferred; was 9)*: priority was intentionally dropped in goal 3; revisit only if task dependencies earn their keep.
- **Future (unwritten): deploy** — hosting + Postgres + secrets/token handling for one user; write the brief once the MVP set (6–7) has settled in daily use.

Spanning constraints:
- Read paths call the Google API directly — no MCP, no LLM. The only runtime LLM in the system is the goal-5 router.
- **Router write set:** `{create_task, reschedule}` through goal 6; goal 7 adds `append_note` (Google Docs, **insert-only**) — and nothing else, ever: no delete, no status write, no content edits, no Docs overwrite. `note` stays kept-local until goal 7 ships.
- **Google writes begin at goal 4.** g4 = task metadata (due date, list membership). g4a = task content (create, title, notes, **complete/uncomplete**, delete) + list rename. Rank/grouping **never** sync to Google — they stay overlay-only. Local overlay writes are the only mutations before goal 4.
- **Tasks-surface MVP from goal 4a.** The tasks panel is meant to be usable day-to-day from 4a onward (real Google lists — capture, schedule incl. arbitrary dates + overdue, organize, edit, complete, delete); Calendar (g7b) and Scratchpad/router (g5) remain WIP until their goals.
- **No confirm dialogs on writes.** Reschedule's undo is drag-back; the one genuinely irreversible op (delete, g4a) gets a deferred-delete + undo-toast; every other write is optimistic with snapshot-rollback + error toast on failure.
- **All verification runs through the `verifier` subagent** — via the `/verify` command (goal 4). Never ad-hoc curl/Playwright in the main session; that noise stays out of the orchestrator's context. **From g4a: UI *behaviors* are verified through the UI (Playwright)** — e.g. an undo firing zero writes, or a deferred delete firing only after its window — which endpoint checks can't assert. (g4's move worked and the verifier was right; manual use still caught a clipped menu and a latency lag — visual/latency issues that need manual or perf review, not more functional checks.) *(Reality check: g4a built these UI-flow checks but they were **BLOCKED — no browser in the verifier sandbox** — so those behaviors are currently verified by code + endpoints only. Getting a browser into the verifier env, or a manual pass, is the open gap; the g5 decision rolls it forward.)*
- Write paths follow `.claude/rules/writes.md`: idempotent service, insert-before-delete on move, rollback-not-retry on partial failure. `delete_task` has exactly **two** sanctioned callers (g4a): the move-delete (post-successful-insert) and the user delete endpoint (post-undo-window). Verification of write paths uses the `zz-verifier-test` list only (`verifier-writes` skill), with cleanup.

## Subagent & team harness

`.claude/agents/` holds subagent definition files (one per agent). Agents isolate expensive or
noisy work from the main session. The `verifier` agent (goal 3) wraps the `verifier-web` skill and
returns a PASS/FAIL report without polluting the main context with curl output or screenshots.

The three-layer split: the agent file is the **WHO** (role, tool allowlist, output shape — stable
across goals); the skill is the **HOW** (launch recipe, endpoints, selectors — updated per goal);
the invocation prompt is the **WHAT** (this run's acceptance criteria, written fresh from the goal
brief). Never bake acceptance criteria into the agent file.

When adding a new subagent: create `<name>.md` in `.claude/agents/` with a `tools:` allowlist and
the instructions, then note it here.

**Agent teams** (first run: g4). Teammates share one checkout — NOT worktree-isolated — so a
**file partition by layer is the safety mechanism**, and the API contract between layers must be
frozen *in the brief before spawning* (that's what made g4's integration first-try). Known team
gotchas to plan for: teammate sandboxes can't run project binaries (`uv`/`npm`), so **the lead must
run every gate** (pytest/ruff/tsc); the PostToolUse formatter fires on *intermediate* edits; format
only the files the goal touched, not whole packages (ruff-version drift reformats untouched files);
and **path-scoped rule firing is per-teammate-context and invisible to the lead** — to probe a rule,
have the teammate that touches its files echo `/context`. *(g4a's planned 2nd team run was deferred — it ran inline, single-session; the 2nd team run and the conclusive per-teammate `/context` reading move to g7a∥b, the next genuinely-parallel opportunity.)*

## Closing out a goal

Before marking a goal done:
- Refresh the root `README.md` if run/setup steps or endpoints changed.
- Check whether `.claude/skills/`, `.claude/agents/`, `.claude/commands/`, or `.claude/rules/*.md` need a new or updated entry for any pattern that emerged — and whether a **hook** in `.claude/settings.json` would enforce it more reliably than prose (markdown is read-and-maybe-followed; a hook fires every time).
- Confirm the rules still describe the conventions the code actually follows (add, tighten, or correct entries — don't let them drift from the code).
- Record whether the path-scoped rules relevant to this goal actually loaded — `/context` in the session (or in the relevant teammate's context for team runs); rules are flaky in current builds, so track fire/no-fire per goal.
- Write a short harness wrap-up (5–10 lines) on what this goal's harness rep taught — subagent / hook / team / workflow behaviour, gotchas. Hand it to the planning chat so the seed (`project-context.md`) gets its status / ladder / ledger update.
