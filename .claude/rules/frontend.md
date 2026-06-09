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
- **Optimistic drag/group convention (goal 3+):** All drag and group mutations are optimistic.
  The component computes the new rank from its current local state (midpoint of neighbours)
  and passes it to the hook. The hook applies the state update inside `setState`, then fires
  `apiPatch`/`apiPost`/`apiDelete` *outside* `setState` without awaiting. Never do a full
  reload (`load()`) after a drag op. A single drag always produces exactly one PATCH
  (rank ± group_id). For the DnD implementation details, known rough edges, and bug history
  see `.claude/rules/tasks-panel.md` (auto-loads when editing `frontend/src/panels/tasks/**`).
