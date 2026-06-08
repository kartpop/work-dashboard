# Goals

Read the brief for the active goal (`goal-N.md`) before starting work. One line each:

- **goal-0 — Harness bootstrap** *(done)*: repo skeleton, lean CLAUDE.md, path-scoped backend/frontend rules, Google Workspace MCP wired.
- **goal-1 — Read-only dashboard**: backend OAuth + Google API client modules; FastAPI endpoints for Tasks (all lists) and upcoming Calendar; React panels. No writes, no overlay, no AI.
- **goal-2 — Task overlay**: custom sort, priority, and group-by-date-with-custom-order, stored in a local DB keyed by task ID. No AI.
- **goal-3 — Scratchpad**: append-only capture box + store. No routing yet.
- **goal-4 — Auto-router**: scheduled job reads the scratchpad; an LLM classifies each entry to a destination (task list / doc / calendar) as structured output; deterministic code does the writes; low-confidence items go to a review queue. Includes an eval set and guardrails.
- **goal-5 — Granola**: fetch transcripts via MCP, extract action items, feed the same router/queue.
- **goal-6 — Priority / dependency views** *(optional, deferred)*: revisit only if it earns its keep.

Spanning constraint: read paths call the Google API directly — no MCP, no LLM. The only runtime LLM in the system is the goal-4 router.

## Closing out a goal

Before marking a goal done: refresh the root `README.md` if run/setup steps changed; check
whether `.claude/skills/` needs a new or updated entry for any pattern that emerged; and check
whether `.claude/rules/*.md` still describe the conventions the goal's code actually follows
(add, tighten, or correct entries — don't let them drift from the code).
