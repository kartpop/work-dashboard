# Goal 8a — Stable notes target across releases (client-id durability)

**One line:** Guarantee that each user's app-created notes **folder + Doc stay the same
file across every release** — and that the two things they depend on (the OAuth **client
id** and the **`overlay.db` volume**) are documented as hard invariants — so a deploy never
silently orphans a user's notes or 404s every note write.

## Why (the bug this closes)

Goal 8 stores each user's notes folder/Doc ids in `user_settings` and reuses them
idempotently (`ensure_notes_target`: `if not row.notes_doc_id: create`). That keeps the id
**string** stable as long as `overlay.db` persists. But under **`drive.file`**, per-file
access is keyed to the **OAuth client id that created the file** — a different client id is
a different app to Google and gets **404** on files it didn't create, even for the same
user + scope + Drive ([Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth),
[rclone](https://forum.rclone.org/t/google-drive-changing-client-id-and-scope-drive-file-write-access/6693)).

So the notes target actually rests on **two independent invariants**:

| Invariant | Guarantees | Breaks if… |
| :-- | :-- | :-- |
| `overlay.db` volume persists | the stored id string is reused (no new Doc created) | `docker compose down -v`, volume deleted, host migration without the volume |
| OAuth **`client_id`** stays the same | the app keeps `drive.file` access to that Doc | a new OAuth client / new GCP project (rotating the **secret** is fine) |

The nasty interaction: if the client id changes **but the DB survives**, the idempotency
guard reuses the now-unreachable id forever — **every note write 404s, with no recovery**,
per user, silently. That is *worse* than a lost volume (which at least re-bootstraps clean).

## What ships

- **1. Self-heal stale ids (code).** `app.settings.service.ensure_notes_target` probes a
  stored id's reachability before the reuse guard: `app.google.docs.file_accessible` does a
  plain `files.get` (a **read** — no new mutation surface, AST insert-only test unaffected).
  - A **definite 404** (client-id change, or user-deleted file) → drop the id and
    re-bootstrap **in the same call**. Folder 404 → clear folder **and** Doc (the Doc lived
    inside it); Doc-only 404 → keep the still-ours folder, recreate just the Doc in it.
  - Any **other** error (403 / 5xx / transient) → **do not clear** — propagate and fail
    closed, so a blip never nukes a good id (entry stays re-routable).
  - **Cached per process** (`_verified_targets`, in-memory not DB): the healthy path pays the
    probe once per user per process; a restart — i.e. a **deploy**, exactly when the client
    id could have changed — re-probes each user once. Zero steady-state cost.
- **2. Document the two invariants (docs).** `docs/deploy.md` gains a **"Durable per-user
  config — two invariants"** section; `goal-8-owner-steps.md` gains a **"Never change the
  OAuth client id; never `down -v`"** warning next to the client + backup steps. The self-heal
  is a safety net, not a license to churn the client id (it still orphans the old Doc).

## Out of scope

- Off-box backup (still deferred — goal 8 locked decision stands).
- Migrating a user's existing notes content into a re-bootstrapped Doc (a client-id change
  that trips the self-heal starts a *fresh* Doc; the old one is orphaned in the user's Drive,
  recoverable by hand — acceptable at this scale, and avoidable by not changing the client id).
- Any change to the `drive.file`-only scope or the folder-ancestry gate (ADR stands).

## Acceptance criteria

- Reachable stored ids are reused with **no** Drive create (probe returns accessible).
- A **folder 404** re-bootstraps both folder + Doc and persists the new ids; a **Doc-only
  404** keeps the folder and recreates the Doc inside it.
- A **non-404 probe error** raises `ApiError` and leaves the stored ids untouched.
- The probe is **cached per process** — a second `ensure_notes_target` in the same process
  does not re-probe.
- `docs/deploy.md` + `goal-8-owner-steps.md` state both invariants; `tsc`/build unaffected
  (backend-only); AST insert-only test + full backend suite green.

*(Tests: `backend/tests/test_settings.py`.)*
