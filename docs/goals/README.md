# Goals

Read the brief for the active goal (`goal-N.md`) before starting work. One line each:

- **goal-0 — Harness bootstrap** *(done)*: repo skeleton, lean CLAUDE.md, path-scoped backend/frontend rules, Google Workspace MCP wired.
- **goal-1 — Read-only dashboard** *(done)*: backend OAuth + Google API client modules; FastAPI endpoints for Tasks (all lists) and upcoming Calendar; React panels. No writes, no overlay, no AI.
- **goal-2 — Task overlay** *(done)*: custom rank + group-by-date (per-list, IST buckets) stored in a local DB keyed by composite `(tasklist_id, task_id)`; within-bucket drag-to-reorder (midpoint rank); `GET /tasks` merge + `PATCH .../overlay`. No AI, no Google writes. *(A priority field was added here and removed in goal 3.)*
- **goal-3 — Task grouping & ordering** *(done)*: drop priority; overlay-only **user groups** inside each `(list, date-bucket)`; drag to reorder / group / ungroup within a bucket; all optimistic. API: date-bucket key `groups`->`buckets`, an item is a task or a group. Read-only on Google (overlay writes only).
- **goal-4 — Write-back I: reschedule & move** *(done & verified; first Google writes, was goal 6, narrowed)*: reschedule via cross-bucket drag (due-date change, group-aware drop — only the dragged task's row changes); move to another list via menu (insert-then-delete, overlay row migrates to the new composite key). Optimistic, snapshot-rollback on failure, idempotent, **no confirm dialogs**. *(Two move-menu bugs surfaced in manual use — the move works, but its menu is clipped by the group boundary and the destination insert isn't optimistic; both fixed in 4a.)*
- **goal-4a — Write-back II: full task CRUD (tasks MVP)** *(done)*: create / edit (title + notes) / **complete-uncomplete** / delete tasks; **arbitrary-date picker** (reuses reschedule); **Overdue rollup** (render-only, top of each list); **manual refresh**; **subtask render-robustness** (flat); rename task lists; fixed the g4 move-menu (portal escapes the group clip + optimistic destination via insert-from-response). All Google content writes. **No confirm dialogs** — completion writes immediately with an undo-toast, delete defers behind a ~5s undo-toast (Undo = zero Google writes). New endpoints: `POST /tasks/{list}`, `PATCH /tasks/{list}/{task}` (title/notes/status), `DELETE /tasks/{list}/{task}`, `PATCH /lists/{id}`. `delete_task` now has **two** sanctioned callers (move-delete + user delete). **From this goal the tasks surface is a daily-driver MVP** (real use); Calendar & Scratchpad stay WIP. *(Executed inline, single-session — the documented 2nd agent-team run was deferred.)*
- **goal-5 — Scratchpad + Auto-router** *(was 7+8, merged)*: append-only capture box + store; scheduled job; an LLM classifies each entry to a destination (task list / doc / calendar) as structured output; deterministic code does the writes (reusing the g4/g4a write layer); low-confidence items go to a review queue. Includes an eval set and guardrails.
- **goal-6 — Granola** *(was 9)*: fetch transcripts via MCP, extract action items, feed the same router/queue.
- **goal-7 — Layout ∥ Calendar** *(was 4 & 5; run in parallel worktrees)*: *(a)* choose which lists are visible; selected lists side by side (default: My Tasks + follow-ups); `ui_prefs`; picks up cross-list drag. *(b)* calendar panel: date-bucketed (IST), one-click Meet link, today + tomorrow.
- **goal-8 — Plugin capstone**: package skills + verifier + hook + `/verify` as the `work-dashboard-dev` plugin.
- **goal-9 — Dependency / advanced views** *(optional, deferred)*: priority was intentionally dropped in goal 3; revisit only if task dependencies earn their keep.

Spanning constraints:
- Read paths call the Google API directly — no MCP, no LLM. The only runtime LLM in the system is the goal-5 router.
- **Google writes begin at goal 4.** g4 = task metadata (due date, list membership). g4a = task content (create, title, notes, **complete/uncomplete**, delete) + list rename. Rank/grouping **never** sync to Google — they stay overlay-only. Local overlay writes are the only mutations before goal 4.
- **Tasks-surface MVP from goal 4a.** The tasks panel is meant to be usable day-to-day from 4a onward (real Google lists — capture, schedule incl. arbitrary dates + overdue, organize, edit, complete, delete); Calendar (g7b) and Scratchpad/router (g5) remain WIP until their goals.
- **No confirm dialogs on writes.** Reschedule's undo is drag-back; the one genuinely irreversible op (delete, g4a) gets a deferred-delete + undo-toast; every other write is optimistic with snapshot-rollback + error toast on failure.
- **All verification runs through the `verifier` subagent** — via the `/verify` command (goal 4). Never ad-hoc curl/Playwright in the main session; that noise stays out of the orchestrator's context. **From g4a: UI *behaviors* are verified through the UI (Playwright)** — e.g. an undo firing zero writes, or a deferred delete firing only after its window — which endpoint checks can't assert. (g4's move worked and the verifier was right; manual use still caught a clipped menu and a latency lag — visual/latency issues that need manual or perf review, not more functional checks.)
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
have the teammate that touches its files echo `/context`.

## Closing out a goal

Before marking a goal done:
- Refresh the root `README.md` if run/setup steps or endpoints changed.
- Check whether `.claude/skills/`, `.claude/agents/`, `.claude/commands/`, or `.claude/rules/*.md` need a new or updated entry for any pattern that emerged — and whether a **hook** in `.claude/settings.json` would enforce it more reliably than prose (markdown is read-and-maybe-followed; a hook fires every time).
- Confirm the rules still describe the conventions the code actually follows (add, tighten, or correct entries — don't let them drift from the code).
- Record whether the path-scoped rules relevant to this goal actually loaded — `/context` in the session (or in the relevant teammate's context for team runs); rules are flaky in current builds, so track fire/no-fire per goal.
- Write a short harness wrap-up (5–10 lines) on what this goal's harness rep taught — subagent / hook / team / workflow behaviour, gotchas. Hand it to the planning chat so the seed (`project-context.md`) gets its status / ladder / ledger update.
