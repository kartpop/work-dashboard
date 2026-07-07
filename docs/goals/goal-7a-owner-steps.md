# Goal 7a — owner steps (non-code actions)

Claude Code renamed every **live** reference from "Work Dashboard" → **"Dashboard"** in the repo.
The remaining pieces are outside the code — the GitHub repo, the git remote, and the notes Doc's
cosmetic title. Do them in order. None of these are urgent: the app runs fine before you do them
(GitHub auto-redirects old URLs; the Doc title is cosmetic).

> **Scope of the rename:** live docs + app strings only. **Not** touched: historical goal briefs
> (`goal-0`…`goal-7`) and the ADR (records, left as written), git history / commit messages (never
> rewritten), and the absolute filesystem paths in `.claude/settings.json` (they point at the real
> local folder — see step D).

## A. Rename the GitHub repo

- [ ] On GitHub, open the repo → **Settings → General** → rename `work-dashboard` → `dashboard`.
- [ ] GitHub keeps redirects from the old URLs, so existing clones/links keep working for a while,
      but update the remote anyway (next step).

## B. Point the git remote at the new URL

- [ ] `git remote set-url origin git@github.com:kartpop/dashboard.git`
      (or the https form: `https://github.com/kartpop/dashboard.git`).
- [ ] `git remote -v` to confirm, then `git push` to check it still pushes.

## C. Rename the notes Doc in Drive (cosmetic)

- [ ] In Google Drive, rename the existing notes Doc to **`Dashboard — Notes`** (the bootstrap now
      titles fresh Docs this way; renaming the existing one just keeps them consistent).
- [ ] **`NOTES_DOC_ID` in `backend/.env` is unchanged** — the title is cosmetic; the id is the same
      file. Do **not** re-run the bootstrap (that would create a second Doc).

## D. (Optional) Local folder rename — read the caveat first

- [ ] The local checkout is still at `.../src/personal/work-dashboard/`. You **may** rename it to
      `.../dashboard/`, but be aware: **Claude Code keys project history, memory, and scratchpads to
      the absolute path** — renaming the folder resets session continuity, and the paths in
      `.claude/settings.json` would need updating to match.
- [ ] **Recommended:** keep the local folder name as-is (there's no functional cost), or accept the
      history reset knowingly. This is why `.claude/settings.json` still contains `work-dashboard`
      paths — they are real filesystem paths, not brand strings.

---

Notes:
- No auth / scope / token changes in this goal — nothing to re-mint. (Goal 7's `drive.file` grant is
  unchanged.)
- Never commit `backend/.env` or `backend/.google-tokens/` (already gitignored).
