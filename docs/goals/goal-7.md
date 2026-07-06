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
  - **Scope addition:** Google Docs write scope joins the OAuth consent → **one-time re-auth** (delete `backend/.google-tokens/token.json`, re-run `uv run python -m app.google.auth`). Document in the root README alongside the existing re-auth note.
- **Deterministic disposal for `note`.** The classifier taxonomy (`task|note|event|unknown`) is unchanged; only the disposal step grows:
  - `note` + confidence ≥ threshold + `NOTES_DOC_ID` set → **one** `append_note`; entry → `routed→note` (with the local store row retained as the audit copy, as ever).
  - `NOTES_DOC_ID` **unset** → today's kept-local behavior, plus a logged warning. Never a crash, never a blocked pipeline.
  - Low-confidence `note` → review queue; **Confirm as `note`** in review fires the same append (today it's an acknowledge-no-write — update the ReviewPanel copy to say the note will be written to the Doc).
  - The append is **not idempotent** — the route-once state machine is the guard: mark the entry routed only **after** a successful append; on failure the entry stays re-routable and the error is logged, not swallowed (g4+ convention). Same contract as the task path.
- **Config.** `NOTES_DOC_ID` env var in `backend/.env` — the long document ID from the Doc's URL (`docs.google.com/document/d/<THIS>/edit`). Loaded via the existing `load_dotenv` path in `main.py`.
- **Guardrail revisions (all four artifacts, in lockstep):**
  - `router.md`: write set is exactly `{create_task, reschedule, append_note}`; still never `delete_task`, the status write, or `update_content` — and **never a Docs delete/overwrite: `append_note` is insert-only.**
  - `writes.md` (3rd revision): `append_note` documented as a router-only caller; the two `delete_task` callers stand, router still not a third.
  - The AST write-dependency test extends its allowed set to the three functions; the never-delete/never-status stub test gains the docs surface (asserts no Docs call other than the single insert).
  - **Eval set extension:** add `note`-class cases including bulleted multi-line captures and note-vs-task ambiguities; the gate must re-pass. Notes are graded on **destination only** (the body is verbatim — deterministic; timestamp format and top-insertion are unit-tested, not eval-graded).

## Locked decisions
- **Whole editor = one entry** per capture (no top-level-bullet splitting, no multi-classification schema). A dump that mixes a task and a note is the model's call as a whole — or review's.
- **Clear on capture.** Success empties the editor; failure leaves the text in place with the error shown.
- **Insert at top** of the Doc (newest-first), Heading-3 timestamp + verbatim body.
- **Verbatim means verbatim:** bullets go into the Doc as literal `- ` text lines — **no** conversion to Docs-native bullet lists (MVP; revisit only if reading them hurts).
- **Doc target = `NOTES_DOC_ID` env var** for now; unset falls back to kept-local + warning. A UI/config surface for it is deferred.
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
- **Guardrails:** the AST test passes with the three-function set; no code path reaches `delete_task`, the status write, `update_content`, or any Docs call besides the single insert.
- **Eval:** extended set (with bulleted-note + ambiguous cases) re-passes the gate; task-class behavior unchanged (zero task false-positives stands).
- Task routing, review confirm-as-task, the g6 layout, and all g4a task behaviors are intact; `tsc`, build, and backend tests pass; re-auth steps documented in the README.

## Harness upkeep (closing checklist — friction-driven only)
- `router.md` + `writes.md` revisions land **with** the code (they're part of the contract, not doc polish).
- Extend the eval set + re-run the gate; note the scorecard in the wrap-up.
- `google-api-integration` skill: add the Docs fetch/write conventions **only if** the module's shape earns a note.
- Record rule fire/no-fire (`/context`) on router-module and google-module edits.
- Refresh root `README.md` (Docs scope re-auth, `NOTES_DOC_ID`) + `docs/api-reference.md`; update `docs/goals/README.md`.
- Manual pass against a **throwaway test Doc** first (set `NOTES_DOC_ID` to a scratch doc), then flip to the real notes Doc — the Docs writer's analog of the `zz-verifier-test` list rule.
