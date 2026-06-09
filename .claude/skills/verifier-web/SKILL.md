---
name: verifier-web
description: Launch recipe and observation protocol for verifying changes to this dashboard (FastAPI backend on :8010, React/Vite frontend on :5173). Use whenever the verify skill requires a handle on this app's surfaces.
---

# Web verifier — work-dashboard

Covers the two runtime surfaces: the FastAPI backend (`:8010`) and the React frontend (`:5173`).
Both must be running before you drive either surface.

## Prerequisites

- Google OAuth token already minted at `backend/.google-tokens/token.json`. If absent, run
  `cd backend && uv run python -m app.google.auth` once interactively (opens a browser).
- Overlay DB migrated: `cd backend && uv run alembic upgrade head` (safe to re-run; no-ops if
  already at head).
- Node deps installed: `cd frontend && npm install` (skip if `node_modules/` exists and
  `package.json` hasn't changed).

## Launch

Start each in a background tmux pane (or `run_in_background`) so both are up before you drive
them.

```bash
# Backend
cd backend && uv run uvicorn app.main:app --reload --port 8010

# Frontend
cd frontend && npm run dev
```

Wait for the backend to print `Application startup complete` and the frontend to print
`Local: http://localhost:5173` before sending requests.

## Backend surface (API)

Drive with `curl` or `httpx`. The base URL is `http://localhost:8010`.

```bash
# Smoke test
curl -s http://localhost:8010/health | jq .

# Tasks (grouped view, default)
curl -s "http://localhost:8010/tasks?view=grouped" | jq '.task_lists[].title'

# Tasks (flat view)
curl -s "http://localhost:8010/tasks?view=flat" | jq .

# Show completed
curl -s "http://localhost:8010/tasks?show_completed=true" | jq '.task_lists[0].groups[0].tasks | length'

# PATCH overlay (rank or priority)
curl -s -X PATCH http://localhost:8010/tasks/<LISTID>/<TASKID>/overlay \
  -H 'Content-Type: application/json' \
  -d '{"priority": 2}' | jq .

# Error shape check (should 400)
curl -s -X PATCH http://localhost:8010/tasks/foo/bar/overlay \
  -H 'Content-Type: application/json' \
  -d '{}' | jq .
```

## Frontend surface (GUI)

Drive with Playwright. The origin is `http://localhost:5173`.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://localhost:5173")
    page.wait_for_selector(".panel")          # panels rendered
    page.screenshot(path="/tmp/dashboard.png")
    browser.close()
```

Key selectors:
- `.panel` — each surface panel (Tasks, Calendar, …)
- `.task-list-section` — one per Google task list
- `.date-group` / `.date-group-label` — bucketed date groups
- `.task-item` — individual task row
- `.drag-handle` — drag affordance (⠿ braille block)
- `.priority-badge` — priority toggle button (`·` / `Low` / `Med` / `High`)
- `.panel-error` — error message (present only on fetch failure)

To observe PATCH requests fired by the frontend, attach a route listener before navigating:

```python
patches = []
page.on("request", lambda r: patches.append(r) if r.method == "PATCH" else None)
page.goto("http://localhost:5173")
```

## What to capture

- API responses: paste the JSON body inline in the report.
- Frontend: screenshot saved to `/tmp/` — include the path and describe what's visible.
- Network: PATCH URL + request body when verifying reorder or priority changes.
- Console errors: `page.on("console", ...)` — any `console.error` line is a finding.

## Teardown

Kill background processes after verification. If you used tmux panes, `kill` the PIDs captured
at launch. The overlay DB (`backend/overlay.db`) is gitignored and safe to leave in place across
runs — it accumulates real rank/priority data from test interactions, which is harmless.
