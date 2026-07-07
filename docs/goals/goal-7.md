# Goal 7 — Scratchpad v2: bullet editor + notes → Google Doc

**One line:** The scratchpad becomes a Google-Docs-like bullet pad (`-` starts a bullet, Enter continues it, Tab / Shift+Tab indent/outdent, **Shift+Enter captures**), and the `note` destination graduates from *kept-local* to a **second live writer**: high-confidence notes are appended **verbatim** to one configured Google Doc under a Heading-3 timestamp, inserted at the **top** (newest-first).

## Intent / acceptance bar
The bar: **"a braindump types like a doc and files like magic."** I type three indented bullets about a strategy idea, hit Shift+Enter, and moments later the whole thing sits at the top of my notes Doc under `6-July-2026, 8:41 PM IST` — or in the review queue if the model wasn't sure. Tasks keep routing exactly as g5 built; this goal adds editor ergonomics and gives notes a real destination.

This is the second (and load-bearing) half of the router's write surface: the write set grows from `{create_task, reschedule}` to `{create_task, reschedule, append_note}` — **still nothing that edits, completes, or deletes**. Every guardrail artifact that pinned the old set (router.md, writes.md, the AST write-dependency test, the eval gate) gets its matching revision.

## What ships
- **Bullet editor (plain `<textarea>` + keydown logic — no rich-text framework).** Content stays plain text; the "bullets" are literal `- ` prefixes and space indentation:
  - A line starting `- ` is a bullet. **Enter** on a bullet line inserts a new line with the same indent + `- ` prefix; **Enter on an empty bullet** removes the marker (exits the list — Docs behavior). Enter on a non-bullet line is a plain newline. **Plain Enter never submits.**
  - **Tab** on a bullet line indents one level (two spaces per level); **Shift+Tab** outdents one level (at zero depth it's a no-op). Both `preventDefault` — Tab is captive inside the editor (accepted trade-off; **Esc blurs the editor** so keyboard users can still tab away to Capture and beyond).
  - **Shift+Enter = Capture** (Cmd/Ctrl+Enter kept as a secondary binding). The **whole editor content is captured as ONE entry, verbatim** — bullet characters and indentation included — and the editor **clears on success** (the scratchpad is a launchpad, not a document; captured text lives on in Recent / Tasks / the notes Doc).
- **Notes writer (new Google surface).**
  - New module `app/google/docs.py`, one-API-call-per-function (layering rule): `insert_note(doc_id, heading_text, body_text)` via Docs `documents.batchUpdate` — inserts at the **top of the body** (directly after the title): a **Heading 3** timestamp, then the verbatim body as normal paragraphs. Newest note always first.
  - Timestamp format: `6-July-2026, 8:41 PM IST` (day-Month-year, 12-hour clock, IST — the project's timezone convention).
  - **Scope addition — `drive.file`, never `documents`/`drive`** (ADR: `architecture/drive-access-scoping.md`): the token can only touch files **the app itself created** — Google-enforced, regardless of app code. One-time re-auth (delete `backend/.google-tokens/token.json`, re-run `uv run python -m app.google.auth`); the consent screen must show the *file-scoped* Drive wording — full-Drive/full-Docs wording means the wrong scope was requested → abort. Afterwards the owner revokes the old broad grant (owner-steps checklist below). Document re-auth in the root README alongside the existing note.
  - **Bootstrap command** (because `drive.file` can't reach a hand-made doc): `uv run python -m app.google.bootstrap` creates the notes Doc **inside `NOTES_FOLDER_ID`** (Drive `files.create` with `parents=[NOTES_FOLDER_ID]`) and prints the doc ID for `.env`. This is the **only** file-creation path, and it hard-codes the parent — no code path creates a file outside the folder.
  - **Folder-ancestry gate:** before any `batchUpdate`, verify the target doc's `parents` chain reaches `NOTES_FOLDER_ID` (`files.get`; cached per doc ID after first success; **fail-closed** on any error → entry stays re-routable, error logged).
  - **Startup scope assertion:** on boot, inspect the token's granted scopes and **refuse to start** (clear error) if they exceed the allowlist `{tasks, calendar readonly, drive.file}` — catches "re-authed broad while debugging" drift.
- **Deterministic disposal for `note`.** The classifier taxonomy (`task|note|event|unknown`) is unchanged; only the disposal step grows:
  - `note` + confidence ≥ threshold + `NOTES_DOC_ID` set → **one** `append_note`; entry → `routed→note` (with the local store row retained as the audit copy, as ever).
  - `NOTES_DOC_ID` **unset** → today's kept-local behavior, plus a logged warning. Never a crash, never a blocked pipeline.
  - Low-confidence `note` → review queue; **Confirm as `note`** in review fires the same append (today it's an acknowledge-no-write — update the ReviewPanel copy to say the note will be written to the Doc).
  - The append is **not idempotent** — the route-once state machine is the guard: mark the entry routed only **after** a successful append; on failure the entry stays re-routable and the error is logged, not swallowed (g4+ convention). Same contract as the task path.
- **Config.** Two env vars in `backend/.env`, loaded via the existing `load_dotenv` path in `main.py`: `NOTES_FOLDER_ID` (the designated parent Drive folder — the ID from the folder's URL) and `NOTES_DOC_ID` (the long document ID printed by the bootstrap). **IDs come from config only — never from LLM output or request payloads** (the router proposes a destination *class*; deterministic code picks the doc).
- **Owner-steps checklist (non-code actions).** During implementation, write and maintain `docs/goals/goal-7-owner-steps.md`: an ordered checkbox list of every step only the owner can do — create/pick the Drive folder and copy its ID into `.env`, delete the old token, re-auth, verify the consent-screen wording is file-scoped, revoke the old broad grant at myaccount.google.com/permissions, run the bootstrap against a **throwaway test folder/doc first**, paste `NOTES_DOC_ID` into `.env`, flip to the real folder/doc. Claude Code writes it; the owner executes it.
- **Guardrail revisions (all four artifacts, in lockstep):**
  - `router.md`: write set is exactly `{create_task, reschedule, append_note}`; still never `delete_task`, the status write, or `update_content` — and **never a Docs delete/overwrite: `append_note` is insert-only.**
  - `writes.md` (3rd revision): `append_note` documented as a router-only caller; the two `delete_task` callers stand, router still not a third.
  - The AST write-dependency test extends its allowed set to the three functions; the never-delete/never-status stub test gains the Docs/Drive surface: only `insert_note` and the bootstrap create may touch the Docs/Drive client — no `files.delete`, no `files.update` content overwrite, no doc-rewrite pattern anywhere.
  - **Eval set extension:** add `note`-class cases including bulleted multi-line captures and note-vs-task ambiguities; the gate must re-pass. Notes are graded on **destination only** (the body is verbatim — deterministic; timestamp format and top-insertion are unit-tested, not eval-graded).

## Locked decisions
- **Whole editor = one entry** per capture (no top-level-bullet splitting, no multi-classification schema). A dump that mixes a task and a note is the model's call as a whole — or review's.
- **Clear on capture.** Success empties the editor; failure leaves the text in place with the error shown.
- **Insert at top** of the Doc (newest-first), Heading-3 timestamp + verbatim body.
- **Verbatim means verbatim:** bullets go into the Doc as literal `- ` text lines — **no** conversion to Docs-native bullet lists (MVP; revisit only if reading them hurts).
- **Doc target = `NOTES_DOC_ID` env var** for now; unset falls back to kept-local + warning. A UI/config surface for it is deferred.
- **Drive access is folder-scoped — Option A** *(locked 2026-07-07; full ADR: `architecture/drive-access-scoping.md`)*: OAuth scope is **`drive.file` only** (never `documents`/`drive` — Google itself blocks files the app didn't create); the bootstrap creates the notes Doc inside `NOTES_FOLDER_ID`; folder-ancestry gate + startup scope assertion + AST-test extension enforce the boundary in code; IDs are config-only. Reading *hand-made* files under the folder is deferred — the first feature that needs it (likely Granola, g8) picks between hybrid `drive.readonly` and a service account (leading candidate).
- **Plain `<textarea>` with string manipulation** — no contentEditable, no Slate/Lexical/ProseMirror. The editor's value is exactly what gets captured.
- **Classifier prompt/threshold untouched** unless the extended eval says otherwise — this goal changes *disposal*, not *classification*.

## Out of scope (do not build)
- Markdown rendering / preview; rich text of any kind.
- Docs-native bullet conversion; formatting beyond the H3 heading + plain paragraphs.
- Multiple notes docs, per-entry doc choice, or routing notes to different docs by topic.
- Editing or deleting notes from the app — the Docs surface is **append-only, forever** (the note's home is Google Docs; edit it there).
- Splitting one capture into multiple routed items (locked above).
- Calendar writes (still read-only); Granola (later goal); deployment.

## Acceptance criteria
- **Editor:** `- ` starts a bullet; Enter continues at the same depth; Enter on an empty bullet exits the list; Tab indents / Shift+Tab outdents (no-op at depth 0); Tab never leaves the editor; Esc blurs it; plain Enter never submits; Shift+Enter (and Cmd/Ctrl+Enter) captures the **entire** content as one entry and clears the editor; a failed capture leaves the text intact with an error.
- **Note, high confidence, `NOTES_DOC_ID` set:** exactly **one** Docs insert — at the top of the body, H3 timestamp in the locked format, body verbatim (bullets as literal text); entry → `routed→note`; visible in the real Doc; re-running route-now routes nothing again (route-once holds).
- **`NOTES_DOC_ID` unset:** note → kept-local, warning logged, no crash.
- **Low-confidence note → review; Confirm-as-note** fires exactly one append; **Dismiss** writes nothing; the panel copy says a confirmed note writes to the Doc.
- **Docs failure** (bad ID / revoked scope): entry stays re-routable, error logged not swallowed, no partial `routed` state.
- **Guardrails:** the AST test passes with the three-function set; no code path reaches `delete_task`, the status write, `update_content`, or any Docs/Drive call besides the single insert + the bootstrap create.
- **Scoping:** the stored token carries `drive.file` (not `documents`/`drive`); boot refuses a broader token with a clear error; a write to a doc whose ancestry doesn't reach `NOTES_FOLDER_ID` is rejected by the gate (unit-tested with a doc created outside the folder); the bootstrap creates the Doc inside the folder and prints its ID.
- `docs/goals/goal-7-owner-steps.md` exists and lists every non-code owner action in order (folder setup, `.env`, token delete, re-auth + consent-wording check, old-grant revoke, bootstrap, test-doc-then-real flip).
- **Eval:** extended set (with bulleted-note + ambiguous cases) re-passes the gate; task-class behavior unchanged (zero task false-positives stands).
- Task routing, review confirm-as-task, the g6 layout, and all g4a task behaviors are intact; `tsc`, build, and backend tests pass; re-auth steps documented in the README.

## Harness upkeep (closing checklist — friction-driven only)
- `router.md` + `writes.md` revisions land **with** the code (they're part of the contract, not doc polish).
- Extend the eval set + re-run the gate; note the scorecard in the wrap-up.
- `google-api-integration` skill: add the Docs fetch/write conventions **only if** the module's shape earns a note.
- Record rule fire/no-fire (`/context`) on router-module and google-module edits.
- Refresh root `README.md` (`drive.file` re-auth + old-grant revoke, `NOTES_FOLDER_ID`/`NOTES_DOC_ID`, bootstrap command) + `docs/api-reference.md`; update `docs/goals/README.md`.
- Manual pass against a **throwaway test folder/Doc** first (bootstrap into a scratch folder), then flip to the real notes folder/Doc — the Docs writer's analog of the `zz-verifier-test` list rule.
- Keep `docs/goals/goal-7-owner-steps.md` current as steps are discovered — it's a deliverable, not an afterthought.
