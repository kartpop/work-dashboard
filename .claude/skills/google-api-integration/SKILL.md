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

## Docs / Drive writes (goal 7 — `app/google/docs.py`)

The notes writer added a Docs/Drive client. Conventions specific to it:

- **Scope is `drive.file` only** — never `documents`/`drive` (ADR
  `docs/goals/architecture/drive-access-scoping.md`). Google enforces the token can touch only files
  the app *created*, so there is exactly one create path (`create_doc_in_folder`, hard-coding
  `parents=[folder_id]`), used only by the `app.google.bootstrap` command.
- **Docs edits go through `documents.batchUpdate`** with a list of request dicts applied in order
  (later requests see earlier edits' index shifts). Inserting at the **top of the body** = index `1`;
  build the block as one `insertText`, then `updateParagraphStyle` ranges over it (heading vs body).
  Indices are UTF-16 offsets — plain ASCII/newlines count as 1.
- **Insert-only.** This client never calls `files.delete` or a content-overwriting `files.update`;
  the AST guardrail test (`test_docs_module_write_surface_is_insert_only`) pins that surface. Read a
  file's parents for the folder-ancestry gate via `files.get(fields="parents")`.
- Same sync `_fn` / `async def` + `asyncio.to_thread` split as the other client modules.

## Calendar day window + multi-calendar merge (goal 7b — `app/google/calendar.py`)

The header-strip day fetch is the first client that queries **more than one calendar** and does an
in-module merge (a deliberate, narrow exception to "no merging in `app/google/*`" — it's a
same-shape union, not overlay logic):

- **IST day window:** `_ist_day_bounds(day)` returns `timeMin`/`timeMax` as that IST day's midnight
  → next midnight (`+05:30` offsets); fetch with `singleEvents=True, orderBy="startTime"`. Keep the
  bounds a pure helper so a unit test can pin it for an arbitrary date.
- **Meet link:** `_extract_meet_link` = `hangoutLink`, else the `video` entry in
  `conferenceData.entryPoints`, else `None` (all-day/no-conference events → `None`).
- **Multi-calendar:** query `primary` **plus** every id in `EXTRA_CALENDAR_IDS` (comma-separated
  env, config-only — never LLM/request input). `_merge_events` dedupes by `iCalUID` (first list
  wins → pass primary first so an invited-attendee duplicate keeps the primary copy) and sorts by
  start. Extras are **best-effort** (per-calendar try/except → logged warning); a `primary` failure
  propagates as the `502`.
