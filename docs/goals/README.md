# Goals

Read the brief for the active goal (`goal-N.md`) before starting work. One line each:

- **goal-0 — Harness bootstrap** *(done)*: repo skeleton, lean CLAUDE.md, path-scoped backend/frontend rules, Google Workspace MCP wired.
- **goal-1 — Read-only dashboard** *(done)*: backend OAuth + Google API client modules; FastAPI endpoints for Tasks (all lists) and upcoming Calendar; React panels. No writes, no overlay, no AI.
- **goal-2 — Task overlay** *(done)*: custom rank + group-by-date (per-list, IST buckets) stored in a local DB keyed by composite `(tasklist_id, task_id)`; within-bucket drag-to-reorder (midpoint rank); `GET /tasks` merge + `PATCH .../overlay`. No AI, no Google writes. *(A priority field was added here and is removed in goal 3.)*
- **goal-3 — Task grouping & ordering**: drop priority; add overlay-only **user groups** inside each `(list, date-bucket)`; drag to reorder / group / ungroup within a bucket; all optimistic (no full reload on a single op). API: date-bucket key `groups`->`buckets`, an item is a task or a group. Read-only on Google (overlay writes only).
- **goal-4 — Tasks panel layout**: choose which lists are visible; render selected lists side by side (default: My Tasks + follow-ups). Read-only.
- **goal-5 — Calendar panel**: date-bucketed view (IST); one-click Google Meet link (copy/join) from event conference data; main view scoped to today + tomorrow (further-out deferred). Read-only.
- **goal-6 — Write-back to Google Tasks** *(first Google writes)*: reschedule (cross-bucket / due-date change); move a task between lists (cross-list); group-aware cross-bucket/cross-list drag with position set by drop location; overlay row migrates to the new composite key on a cross-list move. Confirm-before-write + idempotent.
- **goal-7 — Scratchpad**: append-only capture box + store. No routing yet.
- **goal-8 — Auto-router**: scheduled job reads the scratchpad; an LLM classifies each entry to a destination (task list / doc / calendar) as structured output; deterministic code does the writes; low-confidence items go to a review queue. Includes an eval set and guardrails.
- **goal-9 — Granola**: fetch transcripts via MCP, extract action items, feed the same router/queue.
- **goal-10 — Dependency / advanced views** *(optional, deferred)*: priority was intentionally dropped in goal 3; revisit only if task dependencies earn their keep.

Spanning constraints:
- Read paths call the Google API directly — no MCP, no LLM. The only runtime LLM in the system is the goal-8 router.
- **Google writes begin at goal 6.** Everything before is read-only on Google; local overlay writes (rank, grouping) are the only mutations through goal 5.

## Subagent harness

`.claude/agents/` holds subagent definition files (one per agent). Agents are used to isolate
expensive or noisy work from the main session. The `verifier` agent (added in goal 3) wraps the
`verifier-web` skill and returns a PASS/FAIL report without polluting the main context with curl
output or screenshots.

When adding a new subagent: create `<name>.md` in `.claude/agents/` with a `tools:` allowlist
and the instructions, then note it here.

## Closing out a goal

Before marking a goal done:
- Refresh the root `README.md` if run/setup steps changed.
- Check whether `.claude/skills/`, `.claude/agents/`, or `.claude/rules/*.md` need a new or updated entry for any pattern that emerged — and whether a **hook** in `.claude/settings.json` would enforce it more reliably than prose (markdown is read-and-maybe-followed; a hook fires every time).
- Confirm the rules still describe the conventions the code actually follows (add, tighten, or correct entries — don't let them drift from the code).
