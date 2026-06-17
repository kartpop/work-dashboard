# Goals

Read the brief for the active goal (`goal-N.md`) before starting work. One line each:

- **goal-0 — Harness bootstrap** *(done)*: repo skeleton, lean CLAUDE.md, path-scoped backend/frontend rules, Google Workspace MCP wired.
- **goal-1 — Read-only dashboard** *(done)*: backend OAuth + Google API client modules; FastAPI endpoints for Tasks (all lists) and upcoming Calendar; React panels. No writes, no overlay, no AI.
- **goal-2 — Task overlay** *(done)*: custom rank + group-by-date (per-list, IST buckets) stored in a local DB keyed by composite `(tasklist_id, task_id)`; within-bucket drag-to-reorder (midpoint rank); `GET /tasks` merge + `PATCH .../overlay`. No AI, no Google writes. *(A priority field was added here and removed in goal 3.)*
- **goal-3 — Task grouping & ordering** *(done)*: drop priority; overlay-only **user groups** inside each `(list, date-bucket)`; drag to reorder / group / ungroup within a bucket; all optimistic. API: date-bucket key `groups`->`buckets`, an item is a task or a group. Read-only on Google (overlay writes only).
- **goal-4 — Write-back I: reschedule & move** *(done; first Google writes, was goal 6, narrowed)*: reschedule via cross-bucket drag (due-date change, group-aware drop — only the dragged task's row changes); move to another list via menu (insert-then-delete, overlay row migrates to the new composite key). Optimistic, snapshot-rollback on failure, idempotent, **no confirm dialogs**. Cross-list *drag* deferred to goal 7a.
- **goal-5 — Scratchpad + Auto-router** *(was 7+8, merged)*: append-only capture box + store; scheduled job; an LLM classifies each entry to a destination (task list / doc / calendar) as structured output; deterministic code does the writes (reusing the goal-4 write layer); low-confidence items go to a review queue. Includes an eval set and guardrails.
- **goal-6 — Granola** *(was 9)*: fetch transcripts via MCP, extract action items, feed the same router/queue.
- **goal-7 — Layout ∥ Calendar** *(was 4 & 5; run in parallel worktrees)*: *(a)* choose which lists are visible; selected lists side by side (default: My Tasks + follow-ups); `ui_prefs`; picks up cross-list drag. *(b)* calendar panel: date-bucketed (IST), one-click Meet link, today + tomorrow.
- **goal-8 — Plugin capstone**: package skills + verifier + hook + `/verify` as the `work-dashboard-dev` plugin.
- **goal-9 — Dependency / advanced views** *(optional, deferred)*: priority was intentionally dropped in goal 3; revisit only if task dependencies earn their keep.

Spanning constraints:
- Read paths call the Google API directly — no MCP, no LLM. The only runtime LLM in the system is the goal-5 router.
- **Google writes begin at goal 4** and are scoped to due date + list membership only — rank/grouping never sync to Google. Local overlay writes are the only mutations before then.
- **All verification runs through the `verifier` subagent** — via the `/verify` command once it exists (goal 4). Never ad-hoc curl/Playwright in the main session; that noise stays out of the orchestrator's context.
- Write paths follow `.claude/rules/writes.md` (from goal 4): idempotent service, insert-before-delete on move, `delete_task` callable only from move, rollback-not-retry on partial failure. Verification of write paths uses the `zz-verifier-test` list only (`verifier-writes` skill), with cleanup.

## Subagent harness

`.claude/agents/` holds subagent definition files (one per agent). Agents are used to isolate
expensive or noisy work from the main session. The `verifier` agent (added in goal 3) wraps the
`verifier-web` skill and returns a PASS/FAIL report without polluting the main context with curl
output or screenshots.

The three-layer split: the agent file is the **WHO** (role, tool allowlist, output shape —
stable across goals); the skill is the **HOW** (launch recipe, endpoints, selectors — updated
per goal); the invocation prompt is the **WHAT** (this run's acceptance criteria, written fresh
from the goal brief). Never bake acceptance criteria into the agent file.

When adding a new subagent: create `<name>.md` in `.claude/agents/` with a `tools:` allowlist
and the instructions, then note it here.

## Closing out a goal

Before marking a goal done:
- Refresh the root `README.md` if run/setup steps or endpoints changed.
- Check whether `.claude/skills/`, `.claude/agents/`, `.claude/commands/`, or `.claude/rules/*.md` need a new or updated entry for any pattern that emerged — and whether a **hook** in `.claude/settings.json` would enforce it more reliably than prose (markdown is read-and-maybe-followed; a hook fires every time).
- Confirm the rules still describe the conventions the code actually follows (add, tighten, or correct entries — don't let them drift from the code).
- Record whether the path-scoped rules relevant to this goal actually loaded (`/context`) — rules are flaky in current builds; track fire/no-fire per goal.
- Write a short harness wrap-up (5–10 lines) on what this goal's harness rep taught — subagent / hook / team / workflow behaviour, gotchas. Hand it to the planning chat so the seed (`project-context.md`) gets its status / ladder / ledger update.
