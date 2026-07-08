# Goal 7d — Scratchpad daily-driver fixes: capture keybind, review-queue sync, Recent polish

**One line:** Six friction fixes from daily use — drop the accidental-fire Shift+Enter capture, make
a to-review capture show up in the Review queue *immediately* (not 10–45s later), move/reconsider
"Route now", truncate long Recent entries (with copy + tooltip), give routed Recent items a green
border/text cue mirroring the red "In review" one, and fix the invisible calendar-strip meeting
text in dark mode.

## Intent / acceptance bar

Pure polish on the shipped scratchpad — **no new Google write surface, no new LLM behavior, no
schema change**. The bar: the scratchpad stops fighting me — I don't file captures I didn't mean to,
an ambiguous capture lands in the Review queue the moment it lands in Recent, and Recent reads at a
glance (short lines, green = filed, red = needs me).

## What ships

1. **Remove the Shift+Enter capture keybinding.** Shift+Enter is firing accidental captures during
   normal editing. Remove it. Capture is now **button-only** — the "Capture" button (click, or the
   keyboard path **Esc → Tab → Enter**: Esc blurs the editor, Tab focuses the Capture button, Enter
   activates it). Cmd/Ctrl+Enter **stays** as the deliberate power-user secondary (it is not the
   accidental one; two-key combo). Plain Enter still continues a bullet; Tab still indents; Esc
   still blurs. The g7a **deferred-capture undo toast stays exactly as-is** — it now fires on the
   button/Cmd-Enter path instead of Shift+Enter; its mechanics (held POST, ref-based timer, unmount
   flush, undo-by-never-sending) are unchanged. Update the textarea placeholder — it currently says
   "Shift+Enter files it…"; change to reflect the button/Cmd-Enter capture.
   - **Capture the decision:** add a goal-7d line to `docs/goals/README.md` noting Shift+Enter capture
     was removed as an accidental-fire hazard and **may be reintroduced later** if the need returns.
2. **Review queue must sync with Recent on capture.** Today an ambiguous capture appears in RECENT
   as "In review" the moment the held POST fires (~5s), but only shows in the **Review queue** on the
   next 45s poll — a 10–45s lag. Root cause: `capture()` in `useScratchPanel.ts` prepends the POST's
   returned entry to `entries` (drives RECENT) but never refetches `/review`. Fix: when a capture's
   response lands in a review state (`in_review`), refresh the review items too (call `load()`, or
   fetch `/review`, right after the capture resolves) so RECENT and the Review queue update together.
   Confirm/dismiss/route-now already `load()` — this closes the one path that doesn't.
3. **"Route now" — move to the Recent header (and gate it).** It's currently in the **Review queue**
   header, which is the wrong place: it routes *unrouted* entries (the ~15-min backstop for captures
   that failed inline routing), and those live in RECENT, not the review list. Move the button to the
   **Recent** header row. Since routing is instant (g7c), it's a rarely-needed retry — **only render
   it when at least one unrouted entry exists** (otherwise hide it; no dead button). Keep the same
   handler and busy/disabled behavior.
4. **Truncate long Recent entries + copy + tooltip.** A RECENT item currently renders the whole
   captured text (`{e.text}`), so a long note blows out the row. Show **only the first line, clamped
   to one line with a trailing "…"** when it overflows. Add a **copy-to-clipboard button** on the
   row (`navigator.clipboard.writeText(e.text)` — full text, not the truncated view). Show the full
   text on **hover** (native `title` tooltip is fine). Applies to Recent rows only.
5. **Green badge for every filed state.** The **state badge** (the chip: "→ Task" / "Note" /
   "Resolved" / "In review") is the only colored element on the row — coloring the whole body was
   distracting, so keep the cue on the chip. Today `.scratch-badge.state-routed_task` reads green and
   `state-in_review` reads amber, but `kept_note` / `resolved` fall through to the neutral default —
   give those two the **same green** (`#047857`, border + text) so *every* filed state reads "done".
   In-review stays amber/red (`#b45309`). This is the behavior Task already had; it just wasn't
   applied to Note/Resolved. Reuse the existing palette; the body/row and the dimmed routed-tail
   styling (`scratch-entry--dim`) are untouched. *(Amended from the original "whole-row border+text"
   — badge-only, per owner review.)*
6. **Fix invisible calendar-strip meeting text in dark mode.** In the header calendar strip,
   accepted-meeting blocks (`.strip-block.sb-accepted`) set a hardcoded **light** background
   (`#ffedd5`) but inherit `color: var(--text-h)` from `.strip-block` — in dark mode that resolves
   to a light text color, so light-on-light makes the meeting titles unreadable (see the
   screenshot). Fix: give the accepted-block text a **fixed dark color** that reads on the
   light-orange background in **both** themes (set an explicit dark `color` on `.sb-accepted`
   instead of inheriting the theme text var), or make the block background theme-aware. Pending
   blocks (`.sb-pending`, theme-mix background + `var(--done)` text) already read fine — leave them.
   Verify in both light and dark mode; block hover / `+N` badge / title ellipsis behavior unchanged.

## Locked decisions

- **Shift+Enter capture is removed, not remapped.** Button + Esc→Tab→Enter + Cmd/Ctrl+Enter is the
  capture surface. Reintroducing a single-key capture is a deliberate future choice, recorded in
  `docs/goals/README.md`.
- **Undo toast unchanged.** The deferred-capture undo mechanism (g7a) is untouched — only its
  trigger changes.
- **Review-queue sync = refetch on capture**, not a websocket/optimistic review-item construction —
  reuse the existing `load()` path; keep the endpoints dumb.
- **Route now moves to Recent and is conditional** on unrouted entries existing.
- **Recent truncation = first line + ellipsis**, full text via copy button + native `title` tooltip.
  No modal, no expand/collapse.
- **Green cue = whole-row border + text** on routed/resolved states, mirroring the red in-review
  treatment; low-key, reuses existing colors.
- **Calendar-strip fix = accepted-block text color** (a fixed dark color on the light-orange block),
  not a redesign of the strip. Pending blocks untouched.

## Out of scope (do not build)

- Any router/classifier/write-surface change — the write set stays exactly
  `{create_task, reschedule, append_note}`.
- Reintroducing a single-key capture shortcut (future, if the need returns).
- A rich expand/preview for Recent entries; a custom tooltip component.
- `ui_prefs` persistence of anything; new endpoints or schema changes.
- Task-panel color cues (already shipped in g7a) — this goal is scratchpad-only.

## Acceptance criteria

- **Keybind:** Shift+Enter no longer captures (it does nothing beyond normal editing); the Capture
  button and Cmd/Ctrl+Enter both capture; Esc→Tab→Enter reaches and fires the button; plain
  Enter/Tab/Esc editor behavior unchanged; placeholder text updated; the undo toast still fires and
  Undo still sends **zero** `POST /scratch`.
- **Review sync:** a capture the router sends to review appears in **both** RECENT ("In review") and
  the **Review queue** within one render of the capture resolving — no 45s-poll wait.
- **Route now:** absent when there are no unrouted entries; present in the **Recent** header when at
  least one exists; still routes and refreshes.
- **Recent truncation:** a multi-line / long capture shows one clamped line + "…"; the copy button
  copies the **full** text; hovering shows the full text.
- **Green cue:** the state badge (chip only, not the row body) reads green for every filed state
  (`routed_task` / `kept_note` / `resolved`) and amber/red for in-review; dimmed routed-tail styling
  still applies. **Visual AC — eyeball review** (per the g4 lesson: functional checks can't judge
  visual quality).
- **Calendar strip:** accepted-meeting titles are legible in **both** light and dark mode; pending
  blocks unchanged; hover/`+N`/ellipsis behavior intact. **Visual AC — eyeball both themes.**
- `docs/goals/README.md` has a goal-7d line recording the Shift+Enter removal + possible future
  return.
- `tsc`, frontend build, and all backend tests pass; capture→route→task/note, the undo toast, the g6
  layout, and g7c review-queue editing are all intact.

## Harness upkeep (closing checklist — friction-driven only)

- Frontend-only change — likely no rule edits. If the capture-keybind surface changed enough to
  matter, one-line touch-up in `frontend.md`; don't force it.
- Record rule fire/no-fire (`/context`) on the scratch-panel edits.
- Update `docs/goals/README.md` (goal-7d line + the Shift+Enter-removal note); wrap-up to the
  planning chat so the seed's ladder/status reflects 7d.
