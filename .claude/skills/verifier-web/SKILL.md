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
# Tasks (grouped view) — check for buckets/items shape, no priority field
curl -s "http://localhost:8010/tasks?view=grouped" | jq '.task_lists[0].buckets[0]'
# Expected: {"label": "...", "key": "...", "items": [...]}
# Each item has "type": "task" or "type": "group"; no "priority" field anywhere

# Verify no "groups" key at task_list level (renamed to "buckets")
curl -s "http://localhost:8010/tasks?view=grouped" | jq 'keys'
# Should show: ["task_lists"] with each list having "buckets", not "groups"

# Create a group
curl -s -X POST http://localhost:8010/tasks/<LISTID>/groups \
  -H 'Content-Type: application/json' \
  -d '{"name": "Test Group", "bucket_key": "2026-06-09", "rank": 1000}' | jq .

# PATCH overlay (rank + group_id)
curl -s -X PATCH http://localhost:8010/tasks/<LISTID>/<TASKID>/overlay \
  -H 'Content-Type: application/json' \
  -d '{"rank": 500, "group_id": 1}' | jq .

# Ungroup (group_id: null)
curl -s -X PATCH http://localhost:8010/tasks/<LISTID>/<TASKID>/overlay \
  -H 'Content-Type: application/json' \
  -d '{"rank": 500, "group_id": null}' | jq .

# PATCH group rank
curl -s -X PATCH http://localhost:8010/tasks/<LISTID>/groups/<GROUPID> \
  -H 'Content-Type: application/json' \
  -d '{"rank": 750}' | jq .

# DELETE group (members become standalone)
curl -s -X DELETE http://localhost:8010/tasks/<LISTID>/groups/<GROUPID> | jq .

# Error shape check (should 400)
curl -s -X PATCH http://localhost:8010/tasks/foo/bar/overlay \
  -H 'Content-Type: application/json' \
  -d '{}' | jq .
```

### Write endpoints (goal 4 — Google writes)

These mutate Google Tasks (due date + list membership). **Never fire them against a real list** —
they go through the `verifier-writes` skill, which seeds and tears down `zz-verifier-test` lists.
Load `verifier-writes` for the full recipe; the shapes:

```bash
# Reschedule = due-date change (POST, not PATCH). due_date is "YYYY-MM-DD" (IST) or null (NO_DATE).
curl -s -X POST http://localhost:8010/tasks/<LISTID>/<TASKID>/reschedule \
  -H 'Content-Type: application/json' \
  -d '{"due_date": "2026-06-15", "rank": 1000, "group_id": null}' | jq .
# group_id must reference a group in the DESTINATION bucket, else 422 group_wrong_bucket.

# Move to another list (insert-then-delete; overlay row migrates to the new task id).
curl -s -X POST http://localhost:8010/tasks/<LISTID>/<TASKID>/move \
  -H 'Content-Type: application/json' \
  -d '{"target_list_id": "<OTHERLISTID>"}' | jq .
# Move to the current list → 400 same_list.
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
- `.date-group` / `.date-group-label` — bucketed date groups (key = bucket key)
- `.task-item` — individual task row (standalone or within group)
- `.drag-handle` — drag affordance (⠿ braille block)
- `.group-container` — a named group container (bordered box)
- `.group-header` — group name + drag handle + delete button
- `.group-name` — clickable group name (click to rename)
- `.add-group-btn` — "+ group" affordance per bucket
- `.panel-error` — error message (present only on fetch failure)
- `.task-menu` — the ⋯ per-task menu trigger (goal 4: move-to-list)
- `.task-menu-popover` — the open menu popover
- `.move-to-list-option` — each target-list option inside the popover
- `.toast` — write-failure toast (`role="alert"`; goal 4 — appears only when a Google write fails
  and local state has rolled back)

**No `.priority-badge` selector** — priority was removed in goal 3.

**Goal-4 DnD note:** there is now ONE `<DndContext>` per task list (it spans the list's buckets), so a
task can be dragged *between* date buckets = reschedule (one `reschedule` POST + optimistic re-bucket).
A within-bucket drag still fires only an overlay PATCH (no Google write). Write-path verification
(reschedule/move, failure rollback, the `.toast`) is covered by the `verifier-writes` skill against
`zz-verifier-test` lists only.

To observe PATCH/POST/DELETE requests fired by the frontend, attach a route listener:

```python
mutations = []
page.on("request", lambda r: mutations.append(r) if r.method in ("PATCH","POST","DELETE") else None)
page.goto("http://localhost:5173")
```

## What to capture

- API responses: paste the JSON body inline in the report.
- Frontend: screenshot saved to `/tmp/` — include the path and describe what's visible.
- Network: method + URL + request body when verifying drag or group ops.
- Console errors: `page.on("console", ...)` — any `console.error` line is a finding.

## Teardown

Kill background processes after verification. The overlay DB (`backend/overlay.db`) is
gitignored and safe to leave in place — it accumulates rank/group data from test interactions.
