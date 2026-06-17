# Work-Dashboard — chat seed

Paste at the start of a fresh planning chat to resume. (I also carry memory of this project across chats, but this guarantees the specifics.)

## What this is
A personal productivity dashboard built as a **learning vehicle** — the real aim is hands-on reps with the Claude Code harness, MCP, and agent design (CLAUDE.md / rules / skills / hooks / subagents, runtime agent pipelines). The product is the means; the harness skills are the end.

## Workflow
- Strategy + "why": the Claude.ai planning chat (has cross-chat memory).
- Execution: Claude Code in VS Code, one fresh session per goal.
- Handoff: a terse, agent-facing brief committed to `docs/goals/goal-N.md`; Claude Code reads it and executes.
- One fresh planning chat per goal, seeded by this doc.

## Stack & repo
- Monorepo: FastAPI (Python) + React (Vite + TS). SQLite local / Postgres prod, used only for the task-metadata overlay (rank, grouping) and small UI-state persistence later (`ui_prefs`, layout goal).
- Persistence: **SQLModel + Alembic** (introduced g2; g3 added `task_group` + dropped priority). Reused for the scratchpad store and review queue (g5) and `ui_prefs` (g7).
- Frontend DnD: **@dnd-kit**, flat SortableContext per bucket. All DnD architecture, bug history, and rank rules live in `.claude/rules/tasks-panel.md` (path-scoped) — the seed doesn't duplicate them.
- Repo: github.com/kartpop/work-dashboard

## Key decisions
- **Single identity:** everything runs on a personal @gmail account. Dropped the projecttech4dev org dependency (not the t4d Workspace admin, so org policy would gate access). One OAuth client, one token.
- t4d calendar visibility (share into personal account) is a parked, optional experiment — not a dependency.
- Calendar is read-only in the app for v1; invites added manually in Google.
- **Ladder reordered after g3 (learning-first):** Google writes were pulled forward to g4 (was g6) because the thin read-only polish goals (layout, calendar) are independent and low-risk — the right material for a later parallel-worktrees rep, not sequential solo goals. The capture→route→Granola pipeline follows the write machinery it depends on. Daily-driver use of the dashboard is consciously deferred.
- **Priority was dropped in g3** (unrequested g2 feature; position within a bucket is the importance signal).
- **Grouping is overlay-only** (shipped g3): users cluster tasks into named groups inside a `(list, date-bucket)`; Google still sees a flat list per list. Overlay rank + grouping override Google's order at render time. Group deletion ungroups members via FK `ON DELETE SET NULL`.
- **Groups never span buckets** (locked in g4 brief, resolves the g3 fork): a cross-bucket drag updates only the dragged task's row — `group_id` = the destination group if dropped into one, else `NULL`; source-group siblings untouched.
- **Google writes (g4+) are scoped to due date + list membership only.** Rank/grouping never sync to Google. Cross-list move = insert-then-delete (the API has no between-lists move) → new task ID → overlay row migrates. **No confirm dialogs** (deliberate reversal of the original g6 plan — todo items, drag-back is the undo); instead, failed writes roll back local state to a pre-op snapshot + error toast — the one place errors are NOT swallowed.
- **View prefs (layout goal) persist server-side** in a `ui_prefs` key-value table, not `localStorage` — locked earlier, unchanged by the reorder.

## Harness facts established
- Claude Code reads **CLAUDE.md**, not AGENTS.md (skip AGENTS.md while solo). Loads in full every session → keep lean (<120 lines).
- Three instruction tiers: **CLAUDE.md** (always loaded, stable facts) / **`.claude/rules/`** (path-scoped via `paths:` frontmatter; loads only when touching matching files) / **skills** (`.claude/skills/<name>/SKILL.md`, on-demand).
- Path-scoped rules are flaky in current builds (load globally, never load, or load on Read but not Write). Verify with `/context` and `/memory`. **g4 probe:** `tasks-panel.md` is the first substantive path-scoped rule — check it fires when the panel files are touched.
- Agent-facing docs (CLAUDE.md, rules, goal briefs) = terse, imperative, checkable, only error-preventing rationale. The "why" / learning stays in chat.
- **Hooks = the hard-enforcement layer.** Registered in `.claude/settings.json`; scripts in `.claude/hooks/`. Unlike markdown the model *reads*, hooks *fire every time*. First one (PostToolUse formatter) shipped in g3. **Gotchas (g3):** tool input arrives on **stdin as JSON** (`cat - | jq -r '.tool_input.file_path // empty'`) — there is no `CLAUDE_TOOL_INPUT_*` env var; hook command paths must be absolute via `${CLAUDE_PROJECT_DIR}/.claude/hooks/...`.
- **Subagents:** own context window, custom system prompt, restricted tools, `skills:` preloads a skill in full. **Isolation verified in g3:** the verifier ran ~18 tool calls (~20k tokens of curl/log noise); none entered the orchestrator's context — only the ~200-token PASS/FAIL report did.
- **Three-layer verification model (g3):** `agents/verifier.md` = **WHO** (role, tool allowlist, output shape — stable); `verifier-web/SKILL.md` = **HOW** (launch recipe, endpoints, selectors — updated per goal); the invocation prompt = **WHAT** (this run's AC, written fresh from the goal brief). Never bake AC into the agent file.
- **Agent existence ≠ agent usage (g3):** Claude Code verified via direct curl despite the verifier existing. Enforcement: a CLAUDE.md line now; the `/verify` slash command (g4) makes the right path the easy path.
- **Agent teams (g4, first run):** teammates are NOT worktree-isolated — file partition is the safety mechanism. Partition by layer; define the API contract in the brief before parallel work.
- **Closing checklist** lives in `docs/goals/README.md` (read at the start of the next goal). Ran live for g2 and g3. Only the human guarantees it runs.

## Architecture principles
- **Read paths use the Google API directly — no MCP, no LLM.** MCP-in-Claude-Code is a dev-time tool; the backend calls Google's client libs at runtime.
- **Layering:** merge/group/order logic in `backend/app/overlay/` (owns group CRUD); `app/google/*` stays one-API-call-per-function (fetch+reshape; from g4, thin write wrappers too — still no orchestration); write orchestration in `backend/app/writes/` (g4+); routers thin.
- **PATCH partial-update semantics (g3):** distinguish "field omitted" from "explicitly null" with a module-level `_UNSET` sentinel as the service default + Pydantic `model_fields_set` in the router. Applies to any future nullable-on-PATCH field.
- **Side-effect commands are POST, not PATCH** (g4): `/reschedule`, `/move` — they mutate Google, not just overlay fields.
- **Prefer DB-level fallbacks to app logic** where the schema can express the rule (`ON DELETE SET NULL`). Render robustness over crashes: orphaned state degrades to standalone rendering; SQLite migrations need `render_as_batch=True`.
- The **only** runtime LLM is the auto-router (g5): structured output (entry -> destination + confidence); deterministic code does the writes; low-confidence -> review queue; grade routing with a small eval set.
- **Frontend mutation conventions:** *(local/overlay writes, g2–g3)* optimistic update, rank computed in the component, PATCH outside `setState`, never awaited, errors swallowed, one write per op, no reloads. *(Google writes, g4+)* same optimistic immediate-apply, no confirm dialogs — but capture a pre-op snapshot; failed write → rollback to snapshot + error toast, never swallowed.
- Skills/agents/rules emerge from real friction — don't pre-write. Same for CLAUDE.md edits. (g3 proof: `tasks-panel.md` exists because five real DnD bugs earned it.)

## Harness learning (meta-goal)
Each goal **deliberately introduces or exercises one new Claude Code harness capability** (skill / rule / hook / subagent / command / plugin / agent view / agent team / dynamic workflow), chosen to fit that goal. Don't force-fit; err slightly toward complexity for educational value. Reference: https://code.claude.com/docs/en/agents (and /sub-agents, /agent-view, /agent-teams, /workflows).

**Ledger — what's used where:**

| Capability | Introduced | Notes |
| :-- | :-- | :-- |
| MCP (dev-time) | g0 | Google Workspace MCP in Claude Code; runtime uses Google client libs directly. |
| Path-scoped rules | g0 | backend + frontend rules; g2 overlay exception; g3 `buckets` rename + **`tasks-panel.md`** (DnD architecture + bug log). g4 adds `writes.md` (write safety). |
| Skill | g1 | `google-api-integration` (fetch conventions). |
| Skill | g2 | `verifier-web` (cold-start recipe; report shape). Updated each goal as the surface changes. |
| Subagent | g3 ✅ | `verifier` — preloads `verifier-web`, tools = Bash + Read, PASS/FAIL <40 lines. Isolation confirmed (~20k tokens kept out of main context). |
| Hook | g3 ✅ | PostToolUse formatter on Edit\|Write — ruff / prettier. stdin-JSON + `${CLAUDE_PROJECT_DIR}` gotchas documented above. |
| **Agent team** | g4 *(next)* | Two teammates, partitioned backend/frontend on the write-back goal — first genuinely cross-layer goal. |
| Slash command | g4 *(next)* | `/verify` — wraps the verifier subagent with the current goal's AC; fixes the g3 verification-discipline gap. |
| Skill | g4 *(next)* | `verifier-writes` — safe write verification against a dedicated test list, with cleanup. |
| Dynamic workflow | g5 | Fan the router's eval cases across subagents and cross-check; `/effort ultracode` exposure also plausible here. |
| MCP (runtime-adjacent) | g6 | Granola transcripts via MCP feeding the router pipeline. |
| Agent view (parallel worktrees) | g7 | Layout ∥ Calendar — two independent low-risk goals in parallel sessions/worktrees. |
| Plugin | g8 | Package skills + verifier + hook + `/verify` as `work-dashboard-dev`. Educational capstone. |

## Goal ladder *(reordered after g3 — learning-first; old numbering in parens)*
- 0 Harness bootstrap — **done**.
- 1 Read-only dashboard — **done** (`869040c`).
- 2 Task overlay — **done** (`dcd1307`). *(priority added here, removed in g3.)*
- 3 Task grouping & ordering — **done** (`f0f4c3f`): priority dropped; `task_group` + `group_id`; `buckets`/`items` API; group CRUD; six optimistic DnD mutations (flat SortableContext, pointerWithin-first collision); `verifier` subagent + PostToolUse hook; `tasks-panel.md` rule.
- 4 **Write-back I** *(was 6, narrowed)* — **next; brief written** (`docs/goals/goal-4.md`): reschedule via cross-bucket drag (due-date write, group-aware drop), move-to-list via menu (insert+delete, overlay-row migration), optimistic + snapshot-rollback, no confirm dialogs. Cross-list *drag* deferred to layout. Harness: agent team + `/verify` + `verifier-writes` + write-safety rule.
- 5 **Scratchpad + Auto-router** *(was 7+8, merged)* — append-only capture box + store; scheduled job; LLM classifies entries -> destinations; deterministic writes reuse the g4 write layer; review queue; eval set + guardrails. (Only runtime LLM.) Harness: dynamic workflow on the eval set.
- 6 **Granola** *(was 9)* — fetch transcripts via MCP, extract action items, feed the same router/queue.
- 7 **Layout ∥ Calendar** *(was 4 & 5, run in parallel)* — *(a)* list visibility + side-by-side columns + `ui_prefs`; picks up cross-list **drag** (write layer already exists — it's just a new drop surface). *(b)* calendar panel: date-bucketed (reuse the bucket primitive), Meet link, today+tomorrow. Harness: agent view, two worktrees. A layout brief draft exists (the shelved original `goal-4.md`) — reuse, minus the `/verify` rep.
- 8 **Plugin capstone** *(new)* — package `work-dashboard-dev`.
- 9 (optional) Dependency / advanced views — deferred.

## Open design forks (lock in the brief for each goal)
- **g5 router:** scratchpad entry format (free text only vs. light `#list` hints); eval-set size and grading rubric; review-queue UX (in-dashboard panel vs. plain table).
- **g7 layout:** the shelved brief locked `ui_prefs` schema, defaults-computed-not-written, hidden-by-default for new lists, up/down reorder — re-validate when the goal is current; add cross-list drag semantics (drop position rules from the g4/g6 decisions carry over).
- **g7 Meet link:** copy vs. open on click (default: both — primary opens, secondary copies); "+N more" expander for beyond-today/tomorrow.

## Status
Goal 3 **done** (`f0f4c3f`). **Ladder reordered** (writes → pipeline → parallel polish → plugin). Goal 4 = **Write-back I**, brief written (`docs/goals/goal-4.md`), not yet executed. The original layout brief is shelved for g7a.

Known DnD rough edges (tracked in `.claude/rules/tasks-panel.md`, not blocking): no DragOverlay, transform-vs-rect drift, append-only drop-on-group, approximate ungroup index, no touch support, rank precision decay. **Watch in g4:** these now sit under operations that write to Google with no confirm dialog — a mis-drop writes a due date immediately and drag-back is the undo. If mis-drops become frequent, the DragOverlay fix gets promoted from rough edge to priority.

Next action: run goal 4 in a fresh Claude Code session **as an agent team**; review against `goal-4.md`; then write `goal-5.md` (scratchpad + router).

<!-- Update the Status block + ladder markers + Harness ledger as goals complete. Fold durable learnings into Key decisions / Architecture principles and prune locked forks so this stays a lean live seed. -->
