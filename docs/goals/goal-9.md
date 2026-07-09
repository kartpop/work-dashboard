# Goal 9 — Notes hierarchy: user-defined folder/Doc tree + hierarchical routing

**One line:** The single "Dashboard — Notes" Doc grows into a **user-defined folder/Doc tree**
in the user's Drive: a settings tree-widget edits the hierarchy (leaves = Docs, inner nodes =
folders), the router routes each note to the best-matching Doc (explicit prefix *or* content
inference; the default Doc remains the fallback), and the Doc entry shape becomes
**H3 timestamp → H4 one-liner → optional H5 keywords → body → delimiter** — deliberately
setting up heading-based search later.

*(Renumbering: Granola — previously goal 9 — moves to **goal 10**. Update the README ladder and
the planning-chat seed accordingly.)*

## Intent / acceptance bar

I keep per-topic notes docs — "conversations/john/growth", "conversations/jane", "ideas" — and
when I type `john growth — discussed promotion timeline` (or even just a thought that's
*obviously about* John's growth), Shift-free capture files it into the **john/growth Doc**, not
the catch-all. The bar: I edit the tree in settings, the folders/Docs exist in my Drive seconds
later; a captured note lands in the right Doc with the routing prefix stripped but the body
otherwise verbatim; RECENT shows *which* Doc it landed in; and when the router can't
disambiguate, the review queue lets me pick the Doc from a dropdown. Nothing about the safety
posture moves: `drive.file` only, LLM-proposes/code-disposes, IDs never from LLM output, no
Drive file is ever deleted.

## What ships

- **1. The notes index — one JSON tree per user.** `user_settings` gains `notes_index`
  (JSON, Alembic migration): a tree of nodes `{node_id, name, kind: "folder"|"doc",
  drive_id, children}`. **Leaves are Docs, inner nodes are folders**, arbitrary depth
  (capped, see validation). The tree is rooted **under the existing app-created
  "Dashboard Notes" folder** (`notes_folder_id`); the existing default Doc
  (`notes_doc_id`, "Dashboard — Notes") stays **outside the tree** and remains the routing
  fallback. `node_id` is a stable app-generated key (uuid) so the diff can tell *rename*
  from *delete+add*; `drive_id` is the materialized Drive file/folder id. Existing users
  migrate to an empty tree — behavior identical to today until they edit settings.
  - **Validation (422 on violation):** sibling names unique (case-insensitive); names ≤ 60
    chars, no newlines/control chars; depth ≤ 5; ≤ 50 leaf Docs total. These caps also bound
    the classifier prompt (the hierarchy is injected into it — see item 4).
- **2. Settings: interactive tree widget.** A new "Notes hierarchy" section on the settings
  page: expandable tree with inline **add child / rename / delete** per node and an
  add-top-level control. Each materialized node shows a read-only Drive link. Endpoints:
  `GET /settings/notes-index` (the tree, with drive ids) and `PUT /settings/notes-index`
  (the edited tree; response = the persisted tree after Drive materialization). Frontend
  conventions stand (per-panel hook, thin fetch wrapper); this is settings-page UI, not a
  dashboard panel.
  - **Doc→folder conversion:** adding a child under an existing *doc* node **orphans that
    Doc** (same as delete — the file stays in Drive, never written again) and creates a
    folder of the same name in its place. The widget warns before applying. (Moving a
    Drive file's parents is NOT sanctioned — no `addParents`/`removeParents`.)
- **3. Eager Drive materialization on save.** `PUT /settings/notes-index` diffs the incoming
  tree against the stored one **by `node_id`** and applies Drive ops before persisting:
  - **New folder** → `files.create` (folder mime) under its parent folder's drive id —
    `create_folder` gains a `parent_id` arg (root notes folder when top-level). Still
    `files.create`; the app's entire reachable set stays under "Dashboard Notes".
  - **New doc** → the existing `create_doc_in_folder` under its parent folder.
  - **Rename** (same `node_id`, new name) → **the one NEW sanctioned Drive mutation:**
    `rename_file` in `app/google/docs.py` — a **metadata-only** `files.update` whose request
    body is **exactly `{"name": ...}`** (never content, never parents, never `trashed`).
    Settings-path-only caller; **never reachable from the router** (AST-asserted). The Drive
    name and the routing name never drift.
  - **Delete** (node absent) → **orphan-only**: drop the node from the index; the Drive
    file/folder is untouched — it never gets another write from the app, and the user keeps
    it in Drive. Re-adding the same name later creates a **fresh** Doc (no re-attach).
  - **Partial failure:** apply ops child-after-parent, persisting each created/renamed
    `drive_id` as it succeeds (mirrors `ensure_notes_target`'s folder-before-doc commit
    pattern); on a Drive error, persist what succeeded, return the error — a retry of the
    same PUT is idempotent by `node_id` (re-uses existing drive ids, only fills gaps).
    Never lose a created id; never fail into a state that re-creates duplicates.
- **4. Router: hierarchy-aware note routing.** The classifier's system prompt gains a
  **dynamic per-user section**: the rendered hierarchy as **paths only** (e.g.
  `conversations/john/growth`), plus the default-Doc fallback rule. **Drive ids never enter
  the prompt; the LLM never emits an id** (ADR layer 3 stands — it proposes a *path*,
  deterministic code maps path → stored id).
  - **Schema:** `RouterFields` gains `target_doc_path: Optional[str]` (the proposed leaf
    path, null = default Doc) and `keywords: Optional[list[str]]` (see item 5). `note_text`
    becomes load-bearing: **the body with ONLY the routing prefix stripped** — the prompt
    instructs, emphatically, that everything else is preserved **verbatim** (no rewording,
    no summarizing, no dropped words); no prefix → `note_text` = the raw text unchanged.
  - **Matching = prefix + content inference.** An explicit path-ish prefix (`john growth …`,
    `conversation john growth …`) scores high; a content match with no prefix (`discussed
    comp with john` → `conversations/john/growth`) is allowed too; nothing fits → null →
    default Doc.
  - **Dispose (deterministic):** validate `target_doc_path` against the index — exact leaf
    match (case-insensitive) → that Doc's stored id; no match or null → the default Doc.
    **Doc choice never gates review**: the note-vs-task/review confidence gate is unchanged;
    a wrong-doc guess is low-stakes (the note is still filed and its path is visible in
    RECENT). **Truncation guard:** if the stripped `note_text` is missing, empty, or
    suspiciously short (< 50% of the raw text's length), fall back to the **raw text
    verbatim** — a mangled extraction must never silently lose words.
  - `ScratchEntry` gains `routed_doc_path` (nullable, Alembic migration): the path actually
    disposed to (null = default Doc), set on `kept_note` — auto-route and confirm-as-note
    both. `GET /scratch` returns it.
  - Route-once, per-user creds, the scheduler backstop, and the insert-only write set
    `{create_task, reschedule, append_note}` are all **unchanged**.
- **5. Doc entry shape: H3 → H4 → H5.** For **all** notes from this goal (hierarchy Docs and
  the default Doc alike — uniform shape is what makes later heading-extraction search work):
  - **H3** timestamp (unchanged format).
  - **H4** the one-liner summary (moves from bold-normal-text to a named heading style;
    missing summary → skip, as today).
  - **H5** keywords — a new **optional** LLM output: a few extracted keywords rendered as
    one comma-separated H5 line. The prompt must say extraction is optional — **when no
    natural keywords exist the LLM omits them; never force it** — and empty/missing keywords
    → skip the line, never block the write.
  - Body (prefix-stripped, otherwise verbatim) → the existing `borderBottom` delimiter.
  - Still ONE `documents.batchUpdate`, insert-only, top-insert — `insert_note` grows the
    keyword line + heading styles, no new Docs method surface. Old entries are not migrated.
- **6. RECENT shows the destination.** The `kept_note` chip becomes **`Note: <leaf>`**
  (e.g. `Note: growth`); default Doc → plain `Note`. Hover shows the full path
  (`conversations / john / growth`) via the tooltip. Data comes from `routed_doc_path`.
- **7. Review queue: destination-Doc dropdown.** The note-type editor (7c) gains a
  **destination dropdown**: `Dashboard — Notes (default)` + every leaf path from the user's
  index, prefilled with the classifier's `target_doc_path` when it validates (else default).
  Confirm-as-note passes it via the existing override fields; the server re-validates
  against the index (unknown path → 422 — the dropdown only offers real leaves, so a 422
  means a stale tree). Switching a review item task→note shows the dropdown too (default
  preselected). Task-type editing is unchanged.
- **8. Self-heal extends to hierarchy Docs (8a pattern).** Before writing to a hierarchy
  Doc, probe it with the existing `file_accessible` (per-file, cached per process — the
  8a cache keys by `(user_id, drive_id)` now): a definite **404** (client-id change /
  user-deleted file) re-creates the Doc **at the same path** (re-creating missing ancestor
  folders the same way) and updates the index; any non-404 error fails closed and leaves
  the entry re-routable. The default-Doc/root-folder self-heal is unchanged.
- **9. Guardrail artifacts revised in lockstep (same commit as the code — the g5/g7
  pattern).**
  - **AST write-dependency test:** the router's write set stays exactly
    `{create_task, reschedule, append_note}`; the Docs/Drive method surface grows by
    **exactly one** `files().update` — asserted to be called only from the settings/rename
    path (never imported by the router) — plus the parented `create_folder`. Still no
    `files().delete`, no content-overwriting update, no `addParents`/`removeParents`.
  - A **unit test pins the rename body** to exactly `{"name": ...}`.
  - **Eval set:** a fixture hierarchy is injected for eval runs; new cases cover explicit
    prefix, content inference, no-match→default, and prefix-stripping fidelity (the graded
    check: `note_text` == raw minus prefix on clear cases). Gate: existing thresholds
    unchanged **plus** doc-path accuracy ≥ 0.9 on the clear hierarchy subset; keywords and
    the one-liner stay un-graded (cosmetic, spot-checked).
  - `router.md` / `writes.md` amendments; the **ADR gets an addendum** (metadata-only
    rename sanctioned, settings-path-only; orphan-only delete stance).

## Locked decisions (2026-07-09)

- **Interactive tree widget** in settings (not a parsed text outline) — node identity
  (`node_id`) rides the widget, making rename-vs-delete diffs unambiguous.
- **Rename renames the Drive file too**: one new metadata-only `files.update(name)` —
  never content, never parents, never trash; settings-path-only; AST + unit-test pinned.
- **Delete = orphan, always.** The app never deletes or trashes a Drive file. Re-add =
  fresh Doc. Doc→folder conversion = orphan + create (with a UI warning).
- **Eager materialization on save** — folders/Docs are created when the tree is saved, not
  lazily on first note; ids stored in the index; routing just maps path → id.
- **Prefix + content inference** — the hierarchy goes into the system prompt (paths only)
  and the LLM matches freely; default Doc when nothing fits; **doc choice never sends a
  note to review** (the confidence gate stays about note-vs-task-vs-unknown).
- **The verbatim lock is relaxed a second time, deliberately:** the body written to the Doc
  is `note_text` — the raw capture with **only the routing prefix stripped**, under an
  emphatic preserve-verbatim prompt instruction, a deterministic truncation guard
  (< 50% length → raw text wins), and eval-graded stripping fidelity. The one-liner (7c)
  and now the optional keywords are the only other LLM-authored lines.
- **H4 one-liner + optional H5 keywords, uniform for all notes going forward** — named
  heading styles (H3/H4/H5) are the substrate for a later heading-extraction search
  feature; that feature itself is **not** built now.
- **IDs are config-only, everywhere** (ADR layer 3): paths in the prompt and in LLM output;
  ids only in the DB index; the review dropdown submits paths, server-validated.
- **Scope unchanged:** `drive.file` only; no new OAuth scopes; consent untouched.

## Out of scope (do not build)

- The search feature itself (heading extraction, search UI) — this goal only shapes the
  entries for it.
- Reading/importing hand-made Drive files; any scope beyond `drive.file` (Granola-era
  question, now goal 10).
- Moving Drive files between folders (`addParents`/`removeParents`), deleting/trashing
  files, re-attaching orphaned Docs.
- Re-routing already-routed entries; editing routed notes; moving a routed note between
  Docs after the fact.
- Sharing hierarchies between users, templates, or any cross-user feature.
- Backfilling H4/H5 styling onto existing Doc entries.

## Acceptance criteria

- Settings: building the example tree (`conversations/{john/{growth, progression/{…}},
  jane}`) creates the matching nested folders + Docs in Drive under "Dashboard Notes" and
  persists all ids; a second identical PUT is a no-op (no duplicate Drive files). Rename
  updates the Drive file's name and nothing else; delete leaves the Drive file untouched
  and removes it from the index; validation rejects dup siblings / over-depth / bad names
  (422). Endpoint tests cover diff-by-`node_id`, partial-failure retry idempotency, and
  two-user isolation (user B never sees or mutates user A's index).
- Routing: `john growth — discussed promotion timeline` files into the john/growth Doc with
  the prefix stripped and the rest verbatim; a clear content-inference case lands in the
  right Doc; an unmatched note lands in the default Doc; `routed_doc_path` is persisted and
  returned. Classifier failure / missing key still degrades exactly as today (capture never
  lost). Truncation guard: a too-short `note_text` falls back to the raw body (unit test).
- Doc entry: request-builder unit tests pin H3 timestamp → H4 one-liner → H5 keywords →
  body → delimiter, plus every degraded shape (no summary / no keywords / both missing →
  goal-7 shape). Insert-only holds.
- RECENT: a hierarchy-routed note shows `Note: <leaf>` with the full path on hover; a
  default-Doc note shows `Note`.
- Review: the note editor offers exactly default + the user's leaf paths, prefilled from
  the proposal; the confirmed choice is where the note lands (endpoint tests incl. the
  override + 422 on a stale path).
- Self-heal: a 404'd hierarchy Doc is re-created at the same path on next write, index
  updated; non-404 fails closed (tests alongside `test_settings.py`).
- AST test passes with the new pinned surface (router set unchanged; `files().update`
  reachable only from settings); rename-body unit test green; eval gate PASS including the
  new hierarchy cases + doc-path threshold.
- `tsc`, frontend build, Alembic migrations (`notes_index`, `routed_doc_path`), and all
  backend tests green.

## Harness upkeep (closing checklist — friction-driven only)

- `router.md`: hierarchy-in-prompt + path-not-id contract + the 2nd verbatim relaxation
  (same commit as the code).
- `writes.md`: the `rename_file` metadata-only sanction + orphan-only delete stance +
  `insert_note`'s H4/H5 shape.
- ADR `drive-access-scoping.md`: addendum for the metadata-only rename.
- `google-api-integration` skill: parented folder create + rename conventions if the module
  shape earns it.
- Eval set + gate revised in lockstep (fixture hierarchy; stripping-fidelity + doc-path
  grading); `verifier-web`: settings-tree + routed-path checks.
- Record rule fire/no-fire (`/context`); wrap-up to the planning chat (incl. the Granola →
  g10 renumber for the seed).
