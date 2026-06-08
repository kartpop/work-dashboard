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
