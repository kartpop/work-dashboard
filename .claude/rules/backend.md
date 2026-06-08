---
paths: ["backend/**"]
---

# Backend conventions (FastAPI)

- Handlers live under `backend/app/routers/`, one router module per resource; wire them up in
  `backend/app/main.py`.
- Error responses are JSON: `{"error": {"code": "<machine_code>", "message": "<human message>"}}`,
  raised via FastAPI `HTTPException`/exception handlers — never bare strings or stack traces.
- Google API clients (Tasks, Calendar, Drive) live in `backend/app/google/`, one module per
  service, and are the only place that calls the Google APIs directly (see CLAUDE.md hard
  constraint: no MCP/LLM in read paths).
- Use `async def` for all route handlers and I/O (DB, HTTP); keep blocking calls out of the event
  loop via `run_in_executor` if a sync client is unavoidable.
