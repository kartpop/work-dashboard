---
paths: ["backend/**"]
---

# Backend conventions (FastAPI)

- Handlers live under `backend/app/routers/`, one router module per resource; wire them up in
  `backend/app/main.py`.
- Error responses are JSON: `{"error": {"code": "<machine_code>", "message": "<human message>"}}`.
  Raise `app.errors.ApiError(status_code, code, message)`; the registered `StarletteHTTPException`
  handler in `app/main.py` shapes it into that envelope — never hand-roll an error `JSONResponse`
  or return bare strings/stack traces.
- Google API clients (Tasks, Calendar, Drive) live in `backend/app/google/`, one module per
  service, and are the only place that calls the Google APIs directly (see CLAUDE.md hard
  constraint: no MCP/LLM in read paths). See `.claude/skills/google-api-integration/SKILL.md`
  for the credentials/pagination/async conventions those modules follow. These modules do
  fetch+reshape only — no sorting, grouping, or merging with overlay data.
- Merge, sort, and group logic lives exclusively in `backend/app/overlay/service.py`. Routers
  call `overlay_svc.get_merged_task_lists(...)` and stay thin. Do not put merge/sort logic in
  routers or in `app/google/*`.
- The overlay persistence layer (`backend/app/overlay/`) uses SQLModel + Alembic. Run
  `alembic upgrade head` from `backend/` before starting the server. The `overlay.db` SQLite
  file lives in `backend/` and is gitignored.
- Use `async def` for all route handlers and I/O (DB, HTTP); wrap blocking calls (e.g. the
  Google API client's `.execute()`) in `asyncio.to_thread(...)` — see the private sync
  `_fetch_*` / public async `get_*` split in `app/google/tasks.py` and `calendar.py`.
