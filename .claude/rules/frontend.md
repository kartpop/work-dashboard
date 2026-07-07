---
paths: ["frontend/**"]
---

# Frontend conventions (React)

- Each dashboard surface (Tasks, Calendar, Drive, overlay) is a self-contained panel component
  under `frontend/src/panels/`, composed on a single dashboard page — avoid cross-panel imports.
- Local UI state stays in the component; data fetched from the backend is owned by a thin
  per-panel hook (e.g. `useTasksPanel`) so panels can be developed and tested independently.
- No global state library unless a concrete cross-panel sharing need appears — prefer lifting
  state to the dashboard page over adding one.
- "Self-contained panel" means no panel-to-panel imports — it doesn't forbid shared leaf
  utilities. Cross-cutting helpers with no panel-specific knowledge (the backend fetch
  wrapper `api.ts`, `formatDate.ts`) live at `frontend/src/` root and may be imported by any
  panel hook.
- **MVP layout (goal 6):** `DashboardPage` renders `PinnedTasksRow` (the full-width top row) then
  `OtherTasksSection` (collapsed, ephemeral state) and the calendar. `PinnedTasksRow` owns ONE
  resizable grid holding all three top-row columns — My Tasks | Follow-ups (the pinned pair, under
  one shared `DndContext` for cross-list drag) + the scratchpad. The scratchpad is passed in as a
  `scratchpad` **prop** (a `<CapturePanel>` node built by `DashboardPage`) so `TasksPanel.tsx`
  imports no sibling panel. `DndListGroup` is now **children-based** (owns sensors + `handleDragEnd`
  over its `lists`; the caller renders the columns) so a `ResizeHandle` can sit as a grid sibling
  between the two pinned columns. Column widths are `fr` fractions (default 30/30/40) in ephemeral
  state — dragging a handle shifts width between the two adjacent columns; below a breakpoint the
  grid stacks and handles hide. No width **persistence** / `ui_prefs` / visibility chooser yet
  (deferred to goal 9). Pinned columns pass `compactDates` → the per-row date collapses to just the
  calendar-picker icon (the bucket header carries the date; Today/Tomorrow headers show weekday +
  `dd/mm/yyyy` via `bucketHeading`). The pinned lists are matched **by title** against the live
  Google lists via the static `PINNED_LIST_TITLES` constant (exported from `TasksPanel.tsx`); a
  missing title renders an empty-column hint, not a crash. Tasks-surface state is one lifted
  `useTasksPanel` shared by `PinnedTasksRow` / `OtherTasksSection` / `TasksToasts`; the write toasts
  are rendered once (`position: fixed`).
- **Optimistic drag/group convention (goal 3+):** All drag and group mutations are optimistic.
  The component computes the new rank from its current local state (midpoint of neighbours)
  and passes it to the hook. The hook applies the state update inside `setState`, then fires
  `apiPatch`/`apiPost`/`apiDelete` *outside* `setState` without awaiting. Never do a full
  reload (`load()`) after a drag op. A single drag always produces exactly one PATCH
  (rank ± group_id). For the DnD implementation details, known rough edges, and bug history
  see `.claude/rules/tasks-panel.md` (auto-loads when editing `frontend/src/panels/tasks/**`).
