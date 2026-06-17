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
- Frontend DnD: **@dnd-kit**, one `DndContext` per list, flat SortableContext per bucket, each bucket a `useDroppable`. All DnD architecture, bug history, and rank rules live in `.claude/rules/tasks-panel.md` (path-scoped) — the seed doesn't duplicate them.
- Repo: github.com/kartpop/work-dashboard

## Key decisions
- **Single identity:** everything runs on a personal @gmail account. Dropped the projecttech4dev org dependency (not the t4d Workspace admin, so org policy would gate access). One OAuth client, one token.
- t4d calendar visibility (share into personal account) is a parked, optional experiment — not a dependency.
- Calendar is read-only in the app for v1; invites added manually in Google.
- **Ladder reordered after g3 (learning-first):** Google writes were pulled forward to g4 (was g6) because the thin read-only polish goals (layout, calendar) are independent and low-risk — the right material for a later parallel-worktrees rep, not sequential solo goals. **g4a inserted after g4** to complete the write/CRUD surface — also a g5 prerequisite (the router creates tasks). The capture→route→Granola pipeline follows the write machinery it depends on. **From g4a the tasks surface graduates to a daily-driver MVP** (real personal use against real Google lists); Calendar / Scratchpad / router stay WIP. *(Supersedes the earlier "daily-driver deferred" stance — for the tasks surface only.)*
- **Priority was dropped in g3** (unrequested g2 feature; position within a bucket is the importance signal).
- **Grouping is overlay-only** (shipped g3): users cluster tasks into named groups inside a `(list, date-bucket)`; Google still sees a flat list per list. Overlay rank + grouping override Google's order at render time. Group deletion ungroups members via FK `ON DELETE SET NULL`.
- **Groups never span buckets** (g4): a cross-bucket drag updates only the dragged task's row — `group_id` = the destination group if dropped into one, else `NULL`; source-group siblings untouched.
- **Google write surface:** g4 = task **metadata** (due date, list membership). g4a = task **content** (create, edit title/notes, **complete/uncomplete**, delete) + list rename. **Rank/grouping never sync to Google** — overlay-only. Cross-list move = insert-then-delete (the API has no between-lists move) → new task ID → overlay row migrates.
- **No confirm dialogs on writes** (deliberate reversal of the original g6 plan). Reschedule's undo is drag-back. The one genuinely irreversible op — **delete (g4a)** — gets a **deferred-delete + undo-toast**: optimistic remove, ~5s "Undo" toast, the Google `DELETE` fires only after the window closes (Undo cancels with zero Google writes). **Completion** uses an undo-toast too but writes the Google status change **immediately** (Google retains completed tasks; uncomplete is cheap) — the toast is mis-click recovery and the "it vanished" affordance. Every other write is optimistic with a pre-op snapshot; failure → rollback + error toast (the one place errors are NOT swallowed).
- **New tasks land in `NO_DATE`, top of bucket** (g4a) — matches Google's add-task default; date set via the picker (below) or drag.
- **Arbitrary due dates via a date-picker** (g4a): a date control on each task and on create calls the existing g4 `reschedule` endpoint, so dates *outside* the rendered buckets are reachable — drag-reschedule only reaches buckets that already exist. **Overdue** tasks roll up into an Overdue bucket at the top (not scattered in past-date buckets). **Manual refresh** per panel (re-run `GET /tasks`) handles staleness vs. the phone app and surfaces a recurring task's next instance after completion. **Subtasks** render flat as standalone for MVP (a `parent` task is never dropped/duplicated); hierarchy UI deferred unless the user relies on it.
- **View prefs (layout goal) persist server-side** in a `ui_prefs` key-value table, not `localStorage`.

## Harness facts established
- Claude Code reads **CLAUDE.md**, not AGENTS.md (skip AGENTS.md while solo). Loads in full every session → keep lean (<120 lines).
- Three instruction tiers: **CLAUDE.md** (always loaded, stable facts) / **`.claude/rules/`** (path-scoped via `paths:` frontmatter; loads only when touching matching files) / **skills** (`.claude/skills/<name>/SKILL.md`, on-demand).
- **Path-scoped rules are flaky** (load globally, never load, or load on Read but not Write); verify with `/context`. g4 finding: in a **team run**, rule firing is **per-teammate-context and invisible to the lead** — `backend.md` fired in the lead's session, but `tasks-panel.md` / `writes.md` were edited inside teammates' contexts so their probe was inconclusive from the lead's seat. **To probe a rule, have the teammate that touches its files echo `/context`** (carried into g4a).
- Agent-facing docs (CLAUDE.md, rules, goal briefs) = terse, imperative, checkable, only error-preventing rationale. The "why" / learning stays in chat.
- **Hooks = the hard-enforcement layer.** Registered in `.claude/settings.json`; scripts in `.claude/hooks/`. Unlike markdown the model *reads*, hooks *fire every time*. First one (PostToolUse formatter) shipped in g3. **Gotchas:** tool input arrives on **stdin as JSON** (`cat - | jq -r '.tool_input.file_path // empty'`) — no `CLAUDE_TOOL_INPUT_*` env var; hook command paths must be absolute via `${CLAUDE_PROJECT_DIR}/.claude/hooks/...`. g4 finding: the formatter **fires on *intermediate* edits** (it briefly stripped a momentarily-unused import; survived only because the final state used it).
- **Subagents:** own context window, custom system prompt, restricted tools, `skills:` preloads a skill in full. **Isolation verified in g3:** the verifier ran ~18 tool calls (~20k tokens of curl/log noise); none entered the orchestrator's context — only the ~200-token PASS/FAIL report did.
- **Three-layer verification model (g3):** `agents/verifier.md` = **WHO** (role, tool allowlist, output shape — stable); `verifier-web/SKILL.md` = **HOW** (launch recipe, endpoints, selectors — updated per goal); the invocation prompt = **WHAT** (this run's AC, written fresh). Never bake AC into the agent file.
- **Verification coverage (g4 lesson, corrected):** g4's `move` actually *worked* and the verifier correctly confirmed it — but manual use still surfaced a clipped menu (visual) and a non-optimistic destination (perceived latency). The honest lesson is narrow: **functional verification (API *or* UI) still misses *visual* and *latency* issues** — those need manual/visual review or explicit perf assertions. Genuine UI-flow checks earn their place for *state-machine* behaviors (undo-toast fires zero writes; deferred DELETE fires only post-window; picker reaches a no-bucket date) — `verifier-web` gains those in g4a. *(The non-optimistic destination is also a frontend-convention miss — insert-from-response, not refetch — which feeds the "did the frontend rule fire in the teammate's context?" question below.)*
- **Agent existence ≠ agent usage (g3):** Claude Code verified via direct curl despite the verifier existing. Enforcement: a CLAUDE.md line + the `/verify` slash command (g4) makes the right path the easy path.
- **Agent teams (g4, first run — validated):** teammates share one checkout (NOT worktree-isolated) — **file partition by layer is the safety mechanism**, and the **API contract must be frozen in the brief before spawning** (that's what made integration first-try, zero merge friction). **The lead must run every gate** — teammate sandboxes can't run project binaries (`uv`/`npm`/pytest/ruff/tsc). **Format only touched files, not whole packages** (ruff-version drift reformats untouched files → noisy diff). **Worktrees would have hurt here** — the value was a *shared* tree + a *logical* partition; isolation buys nothing when two layers share a contract (save worktrees for genuinely independent goals, g7a∥b). Lead coordination overhead is real but **front-loaded** into writing the contracts; post-spawn integration is mechanical.
- **Closing checklist** lives in `docs/goals/README.md` (read at the start of the next goal). Ran live for g2, g3, g4. Only the human guarantees it runs.

## Architecture principles
- **Read paths use the Google API directly — no MCP, no LLM.** MCP-in-Claude-Code is a dev-time tool; the backend calls Google's client libs at runtime.
- **Layering:** merge/group/order logic in `backend/app/overlay/` (owns group CRUD); `app/google/*` stays one-API-call-per-function (fetch+reshape + thin write wrappers — no orchestration; g4 added `update_due_date`/`insert_task`/`delete_task`, g4a adds task-content update + `update_tasklist`); write orchestration in `backend/app/writes/` (reschedule/move in g4; create/edit/delete in g4a); routers thin.
- **Endpoint conventions:** orchestration with multi-step side effects → **POST** named command (`/reschedule`, `/move`). Single-resource field updates → **PATCH**: `/overlay` for local fields, bare `/tasks/{list}/{task}` for Google content (title/notes). Create = `POST /tasks/{list}`; delete = `DELETE`; list rename = `PATCH /lists/{id}`. Mirrors Google's `tasks.patch` / `tasklists.patch`.
- **PATCH partial-update semantics (g3):** distinguish "field omitted" from "explicitly null" with a module-level `_UNSET` sentinel as the service default + Pydantic `model_fields_set` in the router. Applies to any nullable-on-PATCH field.
- **Prefer DB-level fallbacks to app logic** where the schema can express the rule (`ON DELETE SET NULL`). Render robustness over crashes: orphaned state degrades to standalone rendering; SQLite migrations need `render_as_batch=True`.
- The **only** runtime LLM is the auto-router (g5): structured output (entry -> destination + confidence); deterministic code does the writes; low-confidence -> review queue; grade routing with a small eval set.
- **Frontend mutation conventions:** *(local/overlay writes, g2–g3)* optimistic update, rank computed in the component, PATCH outside `setState`, never awaited, errors swallowed, one write per op, no reloads. *(Google writes, g4+)* same optimistic immediate-apply, no confirm dialogs, pre-op snapshot; failure → rollback + error toast, never swallowed. *(Destructive delete, g4a)* deferred-delete state machine: optimistic remove + undo-toast; the Google `DELETE` is held until the undo window closes; Undo cancels it.
- Skills/agents/rules emerge from real friction — don't pre-write. Same for CLAUDE.md edits. (g3: `tasks-panel.md` exists because five real DnD bugs earned it. g4a: `verifier-web` gains UI-flow checks and `writes.md` gets its first revision *because* g4 surfaced real gaps.)

## Harness learning (meta-goal)
Each goal **deliberately introduces or exercises one new Claude Code harness capability** (skill / rule / hook / subagent / command / plugin / agent view / agent team / dynamic workflow), chosen to fit that goal. Don't force-fit; err slightly toward complexity for educational value — but a goal whose honest job is feature-completion (g4a) is allowed to *exercise/refine* rather than *introduce*, and friction-driven refinement beats bolting on a capability that doesn't fit yet. Reference: https://code.claude.com/docs/en/agents (and /sub-agents, /agent-view, /agent-teams, /workflows).

**Ledger — what's used where:**

| Capability | Introduced | Notes |
| :-- | :-- | :-- |
| MCP (dev-time) | g0 | Google Workspace MCP in Claude Code; runtime uses Google client libs directly. |
| Path-scoped rules | g0 | backend + frontend rules; g2 overlay exception; g3 `buckets` rename + **`tasks-panel.md`** (DnD architecture + bug log); g4 **`writes.md`** (write safety). |
| Skill | g1 | `google-api-integration` (fetch conventions). |
| Skill | g2 | `verifier-web` (cold-start recipe; report shape). Updated each goal as the surface changes; g4a adds UI-flow (Playwright) checks. |
| Subagent | g3 ✅ | `verifier` — preloads `verifier-web`, tools = Bash + Read, PASS/FAIL <40 lines. Isolation confirmed (~20k tokens kept out of main context). |
| Hook | g3 ✅ | PostToolUse formatter on Edit\|Write — ruff / prettier. stdin-JSON + `${CLAUDE_PROJECT_DIR}` gotchas; fires on intermediate edits (g4). |
| Slash command | g4 ✅ | `/verify` — wraps the verifier subagent with the current goal's AC; fixes the g3 verification-discipline gap. |
| Skill | g4 ✅ | `verifier-writes` — safe write verification against `zz-verifier-test` lists, with cleanup. |
| Agent team | g4 ✅ | Two teammates partitioned backend/frontend; partition held, zero merge friction; learnings banked above. |
| *(refinement)* | g4a *(next)* | **No new major capability — deliberate.** 2nd agent-team run to validate g4's gotcha-mitigations + a conclusive per-teammate rule-fire reading; `verifier-web` extended to UI-flow coverage (friction-driven, after g4's API-only check missed the move-menu wiring). |
| Dynamic workflow | g5 | Fan the router's eval cases across subagents and cross-check; `/effort ultracode` exposure also plausible here. |
| MCP (runtime-adjacent) | g6 | Granola transcripts via MCP feeding the router pipeline. |
| Agent view (parallel worktrees) | g7 | Layout ∥ Calendar — two genuinely independent low-risk goals in parallel sessions/worktrees. |
| Plugin | g8 | Package skills + verifier + hook + `/verify` as `work-dashboard-dev`. Educational capstone. |

## Goal ladder *(reordered after g3; 4a inserted post-g4; old numbering in parens)*
- 0 Harness bootstrap — **done**.
- 1 Read-only dashboard — **done** (`869040c`).
- 2 Task overlay — **done** (`dcd1307`). *(priority added here, removed in g3.)*
- 3 Task grouping & ordering — **done** (`f0f4c3f`): priority dropped; `task_group` + `group_id`; `buckets`/`items` API; group CRUD; six optimistic DnD mutations (flat SortableContext, pointerWithin-first collision); `verifier` subagent + PostToolUse hook; `tasks-panel.md` rule.
- 4 **Write-back I** *(was 6, narrowed)* — **done & verified; commit pending**: reschedule via cross-bucket drag (due-date write, group-aware drop), move-to-list (insert+delete, overlay-row migration), optimistic + snapshot-rollback, no dialogs. `DndContext` lifted to one-per-list. Harness: agent team (1st run) + `/verify` command + `verifier-writes` skill + `writes.md` rule. *(Manual-use bugs: move works, but the move-to-list menu is clipped by the group boundary and the destination insert isn't optimistic → both fixed in 4a.)*
- 4a **Write-back II: full CRUD (tasks MVP)** *(next; brief written `docs/goals/goal-4a.md`)* — create / edit (title+notes) / **complete-uncomplete** / delete tasks; **arbitrary-date picker** (reuses reschedule); **Overdue rollup**; **manual refresh**; **subtask render-robustness**; rename lists; wire g4's move-menu. Completion = immediate write + undo-toast; delete = deferred-delete + undo-toast; new tasks → `NO_DATE`; content/status edit = bare-task PATCH. **The tasks surface becomes a daily-driver MVP here.** Harness: 2nd agent-team run (validate g4 gotchas) + UI-flow verification (Playwright in `verifier-web`).
- 5 **Scratchpad + Auto-router** *(was 7+8, merged)* — append-only capture box + store; scheduled job; LLM classifies entries -> destinations; deterministic writes reuse the g4/g4a write layer; review queue; eval set + guardrails. (Only runtime LLM.) Harness: dynamic workflow on the eval set.
- 6 **Granola** *(was 9)* — fetch transcripts via MCP, extract action items, feed the same router/queue.
- 7 **Layout ∥ Calendar** *(was 4 & 5, run in parallel)* — *(a)* list visibility + side-by-side columns + `ui_prefs`; picks up cross-list **drag** (write layer already exists — it's just a new drop surface). *(b)* calendar panel: date-bucketed (reuse the bucket primitive), Meet link, today+tomorrow. Harness: agent view, two worktrees. A layout brief draft exists (the shelved original `goal-4.md`) — reuse, minus the `/verify` rep.
- 8 **Plugin capstone** *(new)* — package `work-dashboard-dev`.
- 9 (optional) Dependency / advanced views — deferred.

## Open design forks (lock in the brief for each goal)
- **g4a (mostly locked in brief):** complete/uncomplete = immediate write + undo-toast; new tasks → `NO_DATE` top, arbitrary dates via a date-picker (reuses reschedule); Overdue rollup bucket; manual refresh; delete → deferred-delete + undo-toast (~5s); content/status edit via bare-task PATCH; subtasks render flat. **Open:** does the user rely on Google Tasks subtasks day-to-day? (flips subtask hierarchy from deferred to in-scope). A cross-session *completed-tasks* view is deferred — the undo-toast covers in-session mis-clicks, and g2's `show_completed` flat mode makes a "show completed" toggle a cheap later add if wanted.
- **g5 router:** scratchpad entry format (free text only vs. light `#list` hints); eval-set size and grading rubric; review-queue UX (in-dashboard panel vs. plain table).
- **g7 layout:** the shelved brief locked `ui_prefs` schema, defaults-computed-not-written, hidden-by-default for new lists, up/down reorder — re-validate when the goal is current; add cross-list drag semantics (drop position rules from the g4 decisions carry over).
- **g7 Meet link:** copy vs. open on click (default: both — primary opens, secondary copies); "+N more" expander for beyond-today/tomorrow.

## Status
Goal 4 **done & verified** (commit pending — uncommitted on a branch off `main`; add the hash here once committed). **g4a is next** = Write-back II / full CRUD, brief written (`docs/goals/goal-4a.md`): create/edit/delete tasks + list rename + fix the g4 move-menu. Manual testing surfaced two g4 move-menu polish bugs (the move itself works): the move-to-list menu is **clipped by the group boundary** for a task low in a group, and the **destination insert isn't optimistic** (~2-3s refetch lag) — both fixed in 4a. **g4a also raises the bar for the tasks surface to a usable daily-driver MVP** (real lists): adding a complete/uncomplete toggle, an arbitrary-date picker (reusing the reschedule endpoint), an Overdue rollup, a manual refresh, and subtask render-robustness, so the full daily task loop works. **Open question for the brief:** does Kartikeya rely on Google Tasks subtasks (flips them from "render flat" to "must support nesting")?

Known DnD rough edges (tracked in `.claude/rules/tasks-panel.md`, not blocking): no DragOverlay, transform-vs-rect drift, append-only drop-on-group, approximate ungroup index, no touch support, rank precision decay. **Watch:** these sit under operations that write to Google with no confirm dialog — a mis-drop writes a due date immediately and drag-back is the undo. If mis-drops become frequent, the DragOverlay fix gets promoted from rough edge to priority.

Next action: commit g4 (branch), then run g4a in a fresh Claude Code session **as a second agent-team run** (apply the g4 gotcha-mitigations: lead runs all gates; teammates echo `/context`); review against `goal-4a.md`; then write `goal-5.md` (scratchpad + router).

<!-- Update the Status block + ladder markers + Harness ledger as goals complete. Fold durable learnings into Key decisions / Architecture principles and prune locked forks so this stays a lean live seed. -->
