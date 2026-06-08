# Goal 1 — Read-only dashboard

Objective: a working read-only dashboard showing Google Tasks (all lists) and upcoming Calendar events, fetched by the FastAPI backend via the Google API directly and rendered in React panels. Stop when all acceptance criteria pass.

## Deliverables
- Backend OAuth to a personal Google account; token persisted to a local gitignored file. Reuse the existing Google Cloud OAuth client. Also fix the "GOOGLE_CLIENT_SECRET_PATH" variable in .mcp.json so that it points to a relative path instead of absolute path - else this won't work when others pull the repo and try to build.
- Google API client modules under `backend/app/google/`, one per service (tasks, calendar). These are the only place that calls Google APIs.
- FastAPI endpoints:
  - `GET /tasks` — the account's task lists with their tasks.
  - `GET /calendar/upcoming` — the next N events (start time, and title when available).
- A React dashboard page with two panels (Tasks, Calendar), each backed by a thin per-panel hook.
- If repeated Google API patterns emerge (pagination, token refresh, error normalization), capture them in `.claude/skills/google-api-integration/SKILL.md`.

## Constraints
- Read-only. No create/update/delete of tasks or events.
- No task-metadata overlay (sort / priority / grouping) — that is goal 2.
- No LLM and no MCP in any read path (per CLAUDE.md hard constraint).
- Calendar reads against the personal account; test events are fine.
- Endpoints stay dumb: fetch and return. No ranking, merging, or derived ordering yet.

## Acceptance criteria
- [x] Backend completes Google OAuth and persists a token (gitignored).
- [x] `GET /tasks` returns live data covering all the account's task lists.
- [x] `GET /calendar/upcoming` returns live upcoming events.
- [x] All Google API calls live only under `backend/app/google/`.
- [x] Dashboard renders both panels with live data via per-panel hooks.

## Out of scope (defer to later goals)
Writes of any kind; task overlay / sort / priority / grouping; scratchpad; router; Granola; any runtime LLM or MCP.
