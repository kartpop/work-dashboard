---
name: google-api-integration
description: Conventions for adding a new read-only Google API client module under backend/app/google/ (Tasks, Calendar, Drive, ...). Use when wiring up a new Google service or extending an existing one.
---

# Google API integration conventions

Patterns that repeated across `app/google/tasks.py` and `app/google/calendar.py`. Follow them
when adding a new service module (e.g. `drive.py`).

## Credentials

Always get credentials via `app.google.auth.load_credentials()`. It loads the persisted token
from `backend/.google-tokens/token.json`, refreshes it if expired, and raises `RuntimeError`
with a clear message if no token exists yet.

Never run the interactive consent flow (`InstalledAppFlow.run_local_server`) from request-handling
code — it blocks on a browser prompt, which a server process must not do. That flow lives only in
`auth.authorize()`, run once via `uv run python -m app.google.auth`.

If a new service needs a scope `load_credentials` doesn't request yet, add it to `auth.SCOPES`
and re-run the authorize step to mint a token covering the new scope.

## Sync client, async boundary

`googleapiclient.discovery.build(...)` and `.execute()` are blocking. Keep a private sync
`_fetch_*` function that does the Google call, and expose an `async def get_*` wrapper that runs
it via `asyncio.to_thread(...)`. Routers only ever call the async wrapper.

## Pagination

Use `app.google._paging.list_all(resource, **list_kwargs)` to walk `nextPageToken` and collect
every `items` page into one list — needed for both `tasklists().list()` / `tasks().list()` and
will be needed again for `files().list()` (Drive).

## Error normalization

Routers wrap any exception from a `get_*` call in `app.errors.ApiError(status_code, code, message)`,
which shapes the response as `{"error": {"code": ..., "message": ...}}` per the backend
convention. Pick a `code` that names the failing service, e.g. `google_tasks_unavailable`.

## Shaping responses

Don't forward raw Google API payloads. Map to a small, stable dict (id/title/status/etc.) in the
`_fetch_*` function — this keeps the frontend decoupled from upstream field churn and keeps
endpoints "dumb" (fetch + reshape, no ranking or merging).
