# ADR — Google Drive / Docs write-access scoping

**Status:** locked 2026-07-07 (owner-confirmed).
**Applies to:** every Google Drive / Docs surface the app ever grows — starting with the goal-7 notes writer.

## Problem

From goal 7 the app writes to Google Docs. Requirement: the app must be able to touch **only files
under one designated Drive folder** (`NOTES_FOLDER_ID`) — nothing else in the account — with the
strongest enforcement available, not just "the code passes the right ID".

## The constraint that shapes everything

**Folder-level OAuth consent does not exist in Google's model.** No scope grants "this folder and
its contents". The available tiers:

| Scope | Grants | Google-enforced boundary |
| :-- | :-- | :-- |
| `documents` | read/write **every Doc** in the account | none — app code is the only guard |
| `drive` | read/write **everything in Drive** | none |
| `drive.file` | only files **the app itself created** (or explicitly picked via the Google Picker) | **yes** — other files are invisible to the token (404), regardless of app code |

Two notes on the edges:
- The Picker grant is **per-item**; selecting a *folder* does not reliably cascade to its contents.
  The Picker is not a back door to folder scoping.
- The only Google mechanism where folder access truly cascades is **sharing** — sharing a folder
  with another *identity* (person or service account). That is the basis of the deferred Option B.

## Decision — Option A: `drive.file` + app-created docs + layered code defenses

- **Layer 1 — OAuth scope (the real wall):** request `drive.file` only. Never `documents`, never
  `drive`. The Docs API's `documents.batchUpdate` accepts `drive.file`. A compromised token or
  buggy code **cannot touch any file the app didn't create** — enforced by Google's servers.
  Consequence: the app can't reach a hand-made doc, so a **bootstrap command** creates the notes
  Doc inside `NOTES_FOLDER_ID` (Drive `files.create` with `parents=[NOTES_FOLDER_ID]`) and prints
  its ID for `.env`. Every future doc the app needs is created the same way, so the app's entire
  reachable file set lives under the folder.
- **Layer 2 — folder-ancestry gate (app-enforced):** `drive.file` doesn't stop the app *creating*
  files elsewhere, and config could point at a wrong (app-created) doc. So: the single
  doc-creation function hard-codes `parents=[NOTES_FOLDER_ID]` (no other create path exists), and
  before any `batchUpdate` the write path verifies the target doc's `parents` chain reaches
  `NOTES_FOLDER_ID` (`files.get`; cached per doc ID after first success; **fail-closed** on any
  error).
- **Layer 3 — ID hygiene:** `NOTES_FOLDER_ID` / `NOTES_DOC_ID` come from config (`.env`) only.
  The LLM router **never supplies a document ID** — it proposes a destination *class*; deterministic
  code picks the doc (LLM-proposes / code-disposes). IDs never arrive via request payloads either.
- **Layer 4 — startup scope assertion:** on boot, inspect the token's granted scopes and **refuse
  to start** if they exceed the allowlist `{tasks, calendar readonly, drive.file}`. Catches
  "re-authed broad while debugging" drift — the classic way scoped designs rot.
- **Layer 5 — static guardrails:** the AST write-dependency test covers the Docs/Drive surface —
  only `insert_note` and the bootstrap create may touch the Docs/Drive client; no `files.delete`,
  no `files.update` content overwrite, no doc-rewrite pattern anywhere. `writes.md` / `router.md`
  document the contract.
- **Layer 6 — consent-time check:** the consent screen must show the file-scoped Drive wording
  ("…only the specific Google Drive files you use with this app"). Full-Drive or full-Docs wording
  means the code requested the wrong scope — **abort the re-auth**.
- **Layer 7 (reduced for single-user local use):** two nearly-free actions only — after re-authing
  narrower, **revoke the old broad grant** at myaccount.google.com/permissions (one-time); tokens
  and `.env` never committed (existing hard rule). Secrets manager, separate prod OAuth client, and
  periodic access reviews are **deferred to the unwritten deploy goal**.

Threat-model note (why code-level isn't enough alone, even single-user): app-code gates (layers
2–5) cover the owner's own bugs and future LLM-written drift; the `drive.file` scope is what covers
**token leakage** — a stolen `drive.file` token can only touch app-created files, a stolen
`documents` token can rewrite every Doc in the account. Layer 1 is the one defense code cannot
provide.

## Deferred — reading hand-made files under the folder

`drive.file` means "all files under the folder" really means "all **app-created** files under the
folder". The first feature that needs to read hand-made files (likely Granola, goal 8) triggers a
choice:

1. **Hybrid scopes:** add `drive.readonly` beside `drive.file` — Google still enforces that the app
   can never *write* anything it didn't create; reads are folder-gated in code only. Acceptable if
   write safety is the concern.
2. **Option B — service account (leading candidate):** share the parent folder to a service
   account's email with Editor permission; the backend authenticates as it for all Drive/Docs work
   (Tasks/Calendar stay on the user token). Google's **sharing** model then enforces the folder
   boundary server-side, for hand-made files too, with no consent screens — also the natural shape
   for headless deployment. Caveats: the SA owns files it creates (own quota; ownership-transfer
   friction on consumer accounts), and its key is itself a secret to manage.

## Never

The plain `documents` or `drive` scopes. If a future feature seems to need them, that is the
trigger to do Option B instead.

## Addendum (goal 9) — metadata-only rename + orphan-only delete

The user-defined notes hierarchy (goal 9) grows a folder/Doc tree under the app-created notes
folder, edited from settings. Two decisions extend — not weaken — the stance above:

- **One new sanctioned mutation: metadata-only rename.** `docs.rename_file` is a `files.update`
  whose body is **exactly `{"name": ...}`** — never content, never `parents`, never `trashed`. It
  keeps the Drive name in sync with the routing name so they never drift. It is **settings-path-only**
  (called only from the tree-materialization path) and **never reachable from the router**
  (AST-asserted, alongside the existing router write-dependency test). The Docs/Drive AST guard now
  permits `files().update` but **pins it to `_rename_file`**; a unit test pins the body. Layer 1 is
  untouched: `drive.file` still means Google only lets the token rename files the app created.
- **Delete is orphan-only — the app never deletes or trashes a Drive file.** Removing a node from the
  hierarchy drops it from the index; the underlying Drive file/folder is left in the user's Drive and
  simply never written to again. Re-adding a name later creates a fresh Doc (no re-attach). This keeps
  the app's Drive-mutation surface free of any `files.delete` forever (still AST-asserted).
- **New folders/Docs are still app-created** (`files.create`, now with an optional `parent_id` so the
  tree nests under the root notes folder) — the app's entire reachable file set stays app-created and
  under the notes folder, so layer 2's ancestry gate still holds for every hierarchy Doc.
- IDs stay **config-only** (layer 3): the classifier proposes a *path*, deterministic code maps
  path → stored id; the review dropdown submits paths, server-validated; Drive ids never enter the
  prompt or a request payload. No new OAuth scope; consent wording unchanged (`drive.file`).

## Process rule

Any goal that changes auth scopes, tokens, or Google-side setup ships an **owner-steps checklist**
(`docs/goals/goal-N-owner-steps.md`): an ordered checkbox list of every non-code action only the
owner can perform (create/pick the folder, edit `.env`, delete the token, re-auth, verify the
consent wording, revoke the old grant, run the bootstrap, …). Claude Code writes it during
implementation; the owner executes it.
