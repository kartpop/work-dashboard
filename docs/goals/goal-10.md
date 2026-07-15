# Goal 10 — Meeting-notes (MOM) formatter + routing daily-driver fixes

**One line:** Long pasted meeting notes (an LLM-generated MOM of a transcript) file into the
notes Docs **with their structure kept but their headings demoted** — the entry chrome stays
exactly **H3 one-liner → H4 timestamp → optional H5 keywords** and the body contributes **no
other heading, ever** — plus a **routing-header contract** fixing both observed routing bugs:
the first few words of a capture (everything before the first `-` or newline) are
**order-insensitive routing words** — destination keyword, date, doc path — that **take
precedence over the body** (`tomorrow task …` ≡ `task tomorrow …`; `notes daily syncup …`
files by its header no matter what the body reads like, never bounced to review) — and a
review-queue note editor that shows the **raw capture, un-mangled**.

*(Renumbering: Granola — previously goal 10, previously goal 9 — moves to **goal 11**. The
README ladder is updated in the same commit as this brief.)*

## Intent / acceptance bar

After a meeting I paste the MOM my transcript tool produced — `## Agenda`, `### Action items`,
nested bullets, the lot — prefixed `notes daily syncup`, and it files into the
`conversations/meetings/internal/daily syncup` Doc looking like a document, not a text dump:
the bullets are still bullets, the section titles are still visually distinct, but **opening
the Doc's outline shows only my entries' H3/H4/H5 chrome** — a pasted `## Agenda` can never
pollute the heading-extraction search goal 9 set up. The bar for the routing fixes: the first words
of a capture are how I steer it — `tomorrow task pay the plumber` and `task tomorrow pay the
plumber` are the same instruction and both land under Tomorrow's bucket, every time;
`notes daily syncup - <MOM>` files as a note into the daily-syncup Doc **because the header
says so**, irrespective of what the body reads like, and is never bounced to review on
confidence; only a capture whose leading words are non-determinate is routed by its body
(goal-9 content inference, unchanged). And when something does land in review, the editor
shows my full raw text in a usable multi-line box, not a truncated LLM extraction. Nothing about the safety posture moves: LLM-proposes /
code-disposes, insert-only write set `{create_task, reschedule, append_note}`, `drive.file`
only, ids never from LLM output.

## What ships

- **1. Structured-body rendering in `insert_note` (the formatter).** The note body — still
  `note_text` under the goal-9 truncation guard, words **verbatim** — is parsed as light
  markdown and rendered with Docs styling instead of being inserted as one flat text run:
  - **Headings (`#`…`######`) → bold NORMAL_TEXT lines** (marker stripped, words kept). Never
    a `HEADING_*` paragraph — the H3/H4/H5-only invariant is the point of this goal. Depth
    may be conveyed by indent; it must not be conveyed by heading style.
  - **Bullets / numbered lists** (`- `, `* `, `1. `, nested by indent) → real Docs bullets
    (`createParagraphBullets`), nesting preserved.
  - **Inline `**bold**`** → bold text runs (markers consumed). Everything unrecognized passes
    through verbatim — a plain one-liner note renders byte-identical to today.
  - **Deterministic, code-only.** This is a *renderer*, not an LLM step: no new LLM call, no
    third verbatim relaxation — every word of the body still comes from the capture; only
    markdown *markers* are consumed as styling. Still ONE `documents.batchUpdate`, insert-only,
    top-insert; styling requests apply only to the just-inserted range. The Docs method
    surface does not grow (`batchUpdate` only — AST test unchanged).
- **2. The routing header (fixes both observed routing bugs).** The first few words of a
  capture — the segment before the first `-` delimiter or newline — are **routing words**: a
  destination keyword (`task`, `note`/`notes`), date words (`tomorrow`, `friday`), and/or
  doc-path words (`daily syncup`, `dashboard`), in **any order** (`task tomorrow …` ≡
  `tomorrow task …`). A determinate header **takes precedence over the body** — `notes daily
  syncup - <MOM>` is a note filed to daily-syncup even if the body reads like a task list.
  Only when there is no header, or the header doesn't determine something, does the LLM
  infer that thing from the body (goal-9 content inference, unchanged as the fallback).
  - **The LLM interprets the header; code enforces its precedence.** The full contract goes
    into the system prompt (segment definition, order-insensitivity, header-beats-body,
    worked examples) — the LLM is the right interpreter for the **open-vocabulary** parts:
    free word order, multi-word doc paths, named weekdays. But prompt instructions alone are
    exactly what already failed (`notes daily syncup …` bounced to review with the hierarchy
    already in the prompt), so dispose adds thin deterministic guards for the
    **closed-vocabulary** tokens:
    - **Header detection is code:** the segment before the first `-`/newline, capped at
      ~8 words; longer or absent → no header, body inference as today.
    - **Destination keywords force the destination.** A header containing `task` → forced
      `task`; `note`/`notes` → forced `note`; the confidence gate is bypassed **for
      destination only** on a forced capture — an explicit keyword is user intent, not a
      probability, and must never bounce to review. (Neither or both keywords → the LLM's
      destination + the gate, as today.)
    - **Unambiguous date words backstop a null date.** A header containing `today` /
      `tomorrow` / `day after (tomorrow)` with a null LLM `due_date` → code resolves it
      (IST, same `_today_ist` base). Named weekdays stay LLM-resolved, eval-graded.
      `_create_task_from_fields` gains the raw text as an arg.
    - **Doc-path matching stays the LLM's** (multi-word, fuzzy), validated path→id exactly
      as today; doc choice still never gates review (goal 9). A forced note whose fields the
      LLM didn't produce (it proposed `task`) degrades safe: body = raw minus the header,
      no summary/keywords, default Doc unless the proposed path validates.
  - Applies to auto-route **and** review-confirm (same helpers), so a confirmed item gets
    the same guarantees.
  - Eval cases reproduce both bugs first (`tomorrow <task>` phrasings; the daily-syncup
    capture near-verbatim), then pin the contract: order permutations grading identically,
    header-vs-body precedence, multi-word leaves, `day after` / weekday dates, and
    no-header body-inference cases. The gate grows a **header-contract subset**: zero
    review bounces on keyword-headed captures + a clear-relative-date resolution threshold.
- **3. Review-queue note editor un-mangled.** Two grounded defects when a long note lands in
  review: the editor prefills from `fields.note_text` **without** the goal-9 truncation guard
  (`ReviewPanel.tsx` — the auto-route path is guarded, the review prefill trusts the
  low-confidence extraction it just declined to auto-file), and the body box is a fixed
  3-row textarea.
  - The guard moves server-side: when building a `note` review item, `_new_review_item`
    stores the **guarded** body (raw text when `note_text` is missing/short) in
    `fields_json`, so every consumer — editor prefill and confirm fallback — sees the same
    un-mangled text. Frontend keeps its `?? entry_text` fallback.
  - The note-body textarea grows with content (auto-size, sensible max + scroll), preserving
    newlines — a pasted MOM is reviewable, not a keyhole.
- **4. Guardrail artifacts revised in lockstep (same commit as the code).** AST
  write-dependency test unchanged in surface but re-asserted (renderer adds requests, not
  methods; router write set still exactly `{create_task, reschedule, append_note}`); unit
  tests pin the renderer's markdown→requests mapping including "no `HEADING_*` from body
  input, ever"; eval set + gate grow the header-contract cases; `router.md` / `writes.md`
  amendments (see harness upkeep).

## Draft decisions (2026-07-15)

*This brief was drafted from capture notes; overturn any of these in planning if wrong.*

- **The formatter is deterministic code, not an LLM step.** "LLM meeting notes formatter"
  in the capture note means *formatting the LLM-generated MOM* — the MOM's authoring LLM is
  upstream (transcript tool); in-app the render is a pure markdown transform. No new runtime
  LLM, no verbatim relaxation.
- **Rendering applies to every note body**, not a detected "meeting note" subtype — a body
  with no markdown renders exactly as today, so no classifier change and no new mode.
- **Heading demotion is absolute:** body input can produce bold/indent/bullets, never a
  `HEADING_*` paragraph. This is the goal-9 "extract all H4s" invariant made law.
- **The routing header is LLM-interpreted, code-enforced** (2026-07-15, per owner). Neither
  extreme works alone: prompt-only is exactly the observed failure (the hierarchy and date
  rules were already in the prompt and the LLM still under-confidently bounced an explicit
  header), and code-only means hand-rolling a brittle mini-grammar for free word order +
  multi-word doc paths + weekday phrases — the open-vocabulary parts the LLM is good at. So
  the prompt carries the full contract, and dispose deterministically enforces only the
  **closed-vocabulary** tokens: destination keywords force the destination (confidence gate
  bypassed for destination only), unambiguous date words backstop a null `due_date`.
  Everything else about dispose is unchanged — path→id resolution, truncation guard,
  insert-only.
- **Header definition is deterministic:** the segment before the first `-`/newline, capped
  at ~8 words; longer or absent → no header (goal-9 body inference unchanged).
- **The date backstop parses only `today`/`tomorrow`/`day after (tomorrow)`** — the
  unambiguous tokens from the observed bug. Weekday phrases stay LLM-resolved and
  eval-graded; if they keep failing, widening the backstop is a future decision.
- **Review-item fields are guarded at creation** (server-side, single source of truth)
  rather than re-guarded in the frontend.

## Out of scope (do not build)

- Granola / transcript **fetching** (MCP, service account, any new scope) — that is goal 11;
  this goal formats what the user pastes.
- Heading-based search itself (still deferred; this goal protects its substrate).
- Full markdown support (tables, links, code fences, images) — headings, bullets, numbered
  lists, inline bold only; everything else passes through verbatim.
- Re-rendering / migrating existing Doc entries.
- Any new Docs/Drive method, any write-set change, any scope change.
- Editing routed notes, re-routing, or a "meeting" destination type.

## Acceptance criteria

- **Formatter:** a fixture MOM (H2/H3 headings, nested bullets, numbered list, inline bold)
  pasted with a `notes daily syncup` prefix files into the matching hierarchy Doc; the
  resulting requests contain **zero** `HEADING_*` styles from body content (unit-tested at
  the request-builder level); bullets nest; heading words survive verbatim minus markers; a
  plain one-liner note produces byte-identical requests to today. Still one insert-only
  `batchUpdate`; goal-9 degraded shapes (no summary / no keywords) unchanged.
- **Routing header:** `tomorrow task pay the plumber` and `task tomorrow pay the plumber`
  both file under tomorrow's bucket — the backstop covers a classifier null (unit test
  injects it) and the eval order-permutation pairs grade identically; keyword-headed
  captures never enter review for low confidence (unit tests: forced dispose on a
  low-confidence and on a wrong-destination classification); the daily-syncup case routes
  to the right Doc; the header-vs-body precedence case (a `notes <leaf>` header over a
  task-looking body) stays a note; review-confirm gets the same guards; eval gate PASS
  including the header-contract subset (zero review bounces on keyword-headed captures).
- **Review editor:** a review item built from a mangled/short `note_text` prefills the raw
  capture text (endpoint test on `fields_json`); the note textarea auto-grows and preserves
  newlines (verifier check).
- AST test green (no new Docs/Drive methods; router write set unchanged); `tsc`, frontend
  build, backend tests, eval gate all green. No Alembic migration expected — flag it in
  review if one appears.

## Harness upkeep (closing checklist — friction-driven only)

- `writes.md`: `insert_note` structured-body rendering + the no-body-headings invariant.
- `router.md`: the routing-header contract — the prompt section plus the dispose-side
  closed-vocabulary guards — and the guarded review-item fields.
- Eval set + gate revised in lockstep (header-contract subset — including the two bug
  captures near-verbatim as regression cases).
- `verifier-web`: MOM-paste + review-editor checks.
- README ladder: goal-10 line + Granola → g11 (done with this brief; verify at close).
- Record rule fire/no-fire (`/context`); wrap-up to the planning chat (incl. the Granola →
  g11 renumber for the seed).
