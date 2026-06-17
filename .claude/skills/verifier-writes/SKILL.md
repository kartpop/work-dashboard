---
name: verifier-writes
description: Safe verification recipe for Google write paths (reschedule, move). Exercises writes ONLY against dedicated zz-verifier-test lists, then cleans up. Preload alongside verifier-web whenever a goal writes to Google (goal 4+).
---

# Write-path verifier — work-dashboard

Goal 4 introduced the first Google writes (reschedule = due-date change; move = insert+delete across
lists). These touch the user's real Google Tasks. **Never exercise a write against a real list.** All
write checks run against throwaway lists whose titles start with `zz-verifier-test`.

Use this together with `verifier-web` (which has the launch recipe, the `:8010`/`:5173` surfaces, and
the frontend selectors). This skill adds: how to seed test data, drive the write endpoints, confirm the
effect in Google, and clean up.

## Preconditions
- The OAuth token must carry the **read/write** scope `https://www.googleapis.com/auth/tasks` (not
  `tasks.readonly`). If write calls return 403 / "insufficient authentication scopes", that is a
  **BLOCKED** check, not a FAIL — the user must re-run `cd backend && uv run python -m app.google.auth`
  to re-consent. Report it as BLOCKED and stop the write checks.
- The backend (`:8010`) is running per `verifier-web`.

All Python below runs in the backend venv so `app.google.auth` + `googleapiclient` + the token resolve:
`cd backend && uv run python - <<'PY' ... PY`.

## 1. Seed throwaway lists + tasks
Creates (or reuses) two test lists and a few tasks. Prints ids as JSON for the curl steps. NO real
list is ever named or touched.

```bash
cd backend && uv run python - <<'PY'
import json
from googleapiclient.discovery import build
from app.google.auth import load_credentials

svc = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)

def ensure_list(title):
    for tl in svc.tasklists().list(maxResults=100).execute().get("items", []):
        if tl["title"] == title:
            return tl["id"]
    return svc.tasklists().insert(body={"title": title}).execute()["id"]

src = ensure_list("zz-verifier-test")
dst = ensure_list("zz-verifier-test-2")

# a dated task (today, UTC midnight) and an undated task
import datetime
today = datetime.date.today().isoformat()
t_dated = svc.tasks().insert(tasklist=src, body={"title": "vt-dated", "due": today + "T00:00:00.000Z"}).execute()
t_undated = svc.tasks().insert(tasklist=src, body={"title": "vt-undated"}).execute()
t_move = svc.tasks().insert(tasklist=src, body={"title": "vt-move"}).execute()

print(json.dumps({"src": src, "dst": dst,
                  "dated": t_dated["id"], "undated": t_undated["id"], "move": t_move["id"]}))
PY
```

## 2. Drive the write endpoints (curl against :8010)
Substitute the ids printed above. `due_date` is an IST date `YYYY-MM-DD` or `null` (NO_DATE).

```bash
# Reschedule the undated task to today's bucket → expect 200, due set
curl -s -X POST "http://localhost:8010/tasks/$SRC/$UNDATED/reschedule" \
  -H 'Content-Type: application/json' \
  -d "{\"due_date\": \"$(date +%F)\", \"rank\": 1000, \"group_id\": null}" | jq .

# Reschedule the dated task to NO_DATE → expect 200, due cleared
curl -s -X POST "http://localhost:8010/tasks/$SRC/$DATED/reschedule" \
  -H 'Content-Type: application/json' \
  -d '{"due_date": null, "rank": 2000, "group_id": null}' | jq .

# reschedule with a group_id that is NOT in the destination bucket → expect 422 group_wrong_bucket
#   (first POST /tasks/$SRC/groups with some bucket_key, then reference it with a different due_date)

# Move vt-move from src → dst → expect 200 with new_task_id
curl -s -X POST "http://localhost:8010/tasks/$SRC/$MOVE/move" \
  -H 'Content-Type: application/json' \
  -d "{\"target_list_id\": \"$DST\"}" | jq .

# Move to the SAME list → expect 400 same_list
curl -s -X POST "http://localhost:8010/tasks/$SRC/$UNDATED/move" \
  -H 'Content-Type: application/json' \
  -d "{\"target_list_id\": \"$SRC\"}" | jq .
```

## 2b. Content CRUD write checks (goal 4a)
All against `$SRC` (a `zz-` list). Keep created titles prefixed `vt-` so cleanup catches them.

```bash
# Create → 201, undated (NO_DATE). Capture its id as $NEW.
curl -s -X POST "http://localhost:8010/tasks/$SRC" \
  -H 'Content-Type: application/json' -d '{"title": "vt-created", "rank": 1000}' | jq .
# Empty title → 400 empty_title
curl -s -X POST "http://localhost:8010/tasks/$SRC" \
  -H 'Content-Type: application/json' -d '{"title": "   "}' | jq .

# Edit title only / notes only (each: exactly the one field reaches Google)
curl -s -X PATCH "http://localhost:8010/tasks/$SRC/$NEW" \
  -H 'Content-Type: application/json' -d '{"title": "vt-renamed"}' | jq .
curl -s -X PATCH "http://localhost:8010/tasks/$SRC/$NEW" \
  -H 'Content-Type: application/json' -d '{"notes": "vt note"}' | jq .
# Empty body → 400 no_fields; empty title → 400 empty_title; missing task → 404

# Complete then uncomplete (status rides the same PATCH)
curl -s -X PATCH "http://localhost:8010/tasks/$SRC/$NEW" \
  -H 'Content-Type: application/json' -d '{"status": "completed"}' | jq .
curl -s -X PATCH "http://localhost:8010/tasks/$SRC/$NEW" \
  -H 'Content-Type: application/json' -d '{"status": "needsAction"}' | jq .

# Delete (immediate backend delete + overlay row removal) → confirm gone in step 3
curl -s -X DELETE "http://localhost:8010/tasks/$SRC/$NEW" | jq .

# Rename the list, then rename it back to a zz- name (NEVER leave a non-zz title)
curl -s -X PATCH "http://localhost:8010/lists/$SRC" \
  -H 'Content-Type: application/json' -d '{"title": "zz-verifier-test-renamed"}' | jq .
curl -s -X PATCH "http://localhost:8010/lists/$SRC" \
  -H 'Content-Type: application/json' -d '{"title": "zz-verifier-test"}' | jq .
```
Checks: completed task carries a `completed` timestamp in Google, then clears on uncomplete; the
deleted task is absent from `GET /tasks` and its overlay composite key is gone. **The list title
must end as a `zz-` name** so the cleanup guard still recognises it.

## 3. Confirm the effect in Google (source of truth, not just the API echo)
```bash
cd backend && uv run python - <<'PY'
from googleapiclient.discovery import build
from app.google.auth import load_credentials
svc = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)
SRC=__import__("os").environ["SRC"]; DST=__import__("os").environ["DST"]
def dump(tl):
    return [(t["title"], t.get("due")) for t in svc.tasks().list(tasklist=tl, showHidden=True).execute().get("items", [])]
print("SRC:", dump(SRC)); print("DST:", dump(DST))
PY
```
Checks: the rescheduled-to-today task now has a `due` ~today; the NO_DATE task has no `due`; `vt-move`
is GONE from SRC and PRESENT in DST (exactly once — no duplicate, confirming insert-before-delete +
successful delete). Also `GET /tasks?view=grouped` should show the moved task's overlay migrated (old
composite key absent).

## 4. Frontend optimistic / rollback (Playwright, selectors from verifier-web)
- Cross-bucket drag (a `vt-` task between two date buckets) → row appears at the drop position
  immediately; exactly one `reschedule` POST observed; no console error.
- Move via the `.task-menu` (⋯) popover → `.move-to-list-option` → task disappears from source.
- Force-failure / rollback: stop the backend (or block the POST) then perform a reschedule drag →
  local state rolls back to the pre-op position, a `.toast` (role="alert") appears, no console crash.

## 5. Cleanup (always, even on failure)
Deletes only the tasks the run created; leaves the empty `zz-` lists for reuse.
```bash
cd backend && uv run python - <<'PY'
from googleapiclient.discovery import build
from app.google.auth import load_credentials
svc = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)
for title in ("zz-verifier-test", "zz-verifier-test-2"):
    tl = next((x for x in svc.tasklists().list(maxResults=100).execute().get("items", []) if x["title"] == title), None)
    if not tl: continue
    for t in svc.tasks().list(tasklist=tl["id"], showHidden=True).execute().get("items", []):
        if t["title"].startswith("vt-"):
            svc.tasks().delete(tasklist=tl["id"], task=t["id"]).execute()
PY
```
Also delete any overlay rows / groups created against the `zz-` list ids if they linger
(`DELETE /tasks/<zzlist>/groups/<id>`). Never delete tasks whose title does not start with `vt-`, and
never touch a list whose title does not start with `zz-verifier-test`.
