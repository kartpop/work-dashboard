# Goal 7 — owner steps (non-code actions)

Claude Code wrote the code; **only you** can do the Google-side / secrets steps below. Do them in
order. The `drive.file` scoping decision they enforce is the ADR
`docs/goals/architecture/drive-access-scoping.md`.

> Do the whole flow against a **throwaway test folder + Doc first**, confirm a note lands, then
> repeat the folder/`.env` steps for the real notes folder. Never point `.env` at the real Doc
> until the test pass is green.

## A. Drive folder

- [ ] In Google Drive, create (or pick) the folder that will hold your notes Doc. For the first
      run make a **throwaway** folder (e.g. `dashboard-notes-test`).
- [ ] Open the folder and copy its id from the URL: `drive.google.com/drive/folders/<THIS_IS_THE_ID>`.
- [ ] In `backend/.env` add: `NOTES_FOLDER_ID=<that id>`. (Leave `NOTES_DOC_ID` unset for now.)

## B. Re-authorize with the narrower Drive scope

The app now requests `drive.file` (files it creates only) in addition to Tasks + Calendar. A token
can't widen its own scope, so re-mint it:

- [ ] Stop the backend.
- [ ] Delete the old token: `rm backend/.google-tokens/token.json`.
- [ ] Run `cd backend && uv run python -m app.google.auth` — a browser opens.
- [ ] **On the consent screen, verify the Drive line reads file-scoped** — wording like *"See,
      edit, create, and delete only the specific Google Drive files you use with this app."*
      If you instead see full-Drive or full-Docs wording (*"…all your Google Drive files"* /
      *"…all your Google Docs documents"*), **abort** — the wrong scope was requested; do not grant.
- [ ] Approve. Confirm `backend/.google-tokens/token.json` now lists `.../auth/drive.file`.

## C. Bootstrap the notes Doc (the only file-create path)

- [ ] With `NOTES_FOLDER_ID` set and the new token in place, run
      `cd backend && uv run python -m app.google.bootstrap`.
- [ ] It prints a line like `NOTES_DOC_ID=1AbC...`. Paste that line into `backend/.env`.
- [ ] Restart the backend. It will **refuse to start** if the token carries any scope beyond
      `{tasks, calendar.readonly, drive.file}` — that's the guard working, not a bug.

## D. Verify against the throwaway Doc

- [ ] Capture a bulleted note in the scratchpad and hit **Shift+Enter**.
- [ ] Click **Route now** (or wait for the scheduler). A high-confidence note should appear at the
      **top** of the throwaway Doc under a heading like `6-July-2026, 8:41 PM IST`, bullets verbatim.
- [ ] Capture something ambiguous → it should land in the **review queue**; **Confirm as note**
      there should also append to the Doc; **Dismiss** should write nothing.

## E. Flip to the real folder/Doc

- [ ] Repeat A + C for your real notes folder: update `NOTES_FOLDER_ID`, re-run the bootstrap,
      replace `NOTES_DOC_ID` with the new id. (Re-auth is **not** needed again — the scope is
      unchanged.)
- [ ] Restart the backend and capture one real note to confirm.

## F. Revoke the old broad grant (one-time cleanup)

- [ ] Go to <https://myaccount.google.com/permissions>, open this app, and **remove any older,
      broader grant** left from earlier testing so only the current narrow grant remains.

---

Notes:
- If `NOTES_DOC_ID` is unset, notes safely stay **kept-local** with a logged warning — nothing
  crashes. So you can run the app before finishing this checklist; notes just won't reach a Doc yet.
- Never commit `backend/.env` or `backend/.google-tokens/` (already gitignored).
