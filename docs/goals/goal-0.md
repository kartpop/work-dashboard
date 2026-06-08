# Goal 0 — Harness bootstrap

Objective: stand up the repo skeleton and the Claude Code harness. Produce no product features. Stop when all acceptance criteria pass.

## Deliverables
- Monorepo skeleton (layout below), committed.
- A refined CLAUDE.md.
- Two path-scoped rule files.
- Google Workspace MCP wired to a personal Google account, proven by a read.
- A .gitignore covering all secrets and local files.

## Repo layout
```
prod-dashboard/
├── CLAUDE.md
├── .claude/
│   ├── rules/
│   │   ├── backend.md
│   │   └── frontend.md
│   ├── skills/                 # empty for now
│   └── settings.local.json     # gitignored
├── .mcp.json
├── docs/goals/
├── backend/                    # empty stub
└── frontend/                   # empty stub
```

## CLAUDE.md requirements
Generate the initial file with `/init`, then edit until it satisfies all of:
- Under 120 lines.
- Contains only: a one-line project description; the stack (FastAPI + React; SQLite/Postgres for the task-metadata overlay); a repo map; run/test commands; and a line instructing the agent to read `docs/goals/<current-goal>.md` before starting work.
- Includes these hard constraints verbatim:
  - Never commit OAuth tokens, `CLAUDE.local.md`, or `.claude/settings.local.json`.
  - Dashboard read paths call the Google API client directly. Do not use MCP or an LLM to read tasks, calendar, or drive.
- Must NOT contain: feature specifications, multi-step procedures, or subtree-specific conventions.

## Rules
- `.claude/rules/backend.md` — frontmatter `paths: ["backend/**"]`. FastAPI conventions: handler layout, error-response shape, where Google API clients live, async style.
- `.claude/rules/frontend.md` — frontmatter `paths: ["frontend/**"]`. React conventions: panel structure, state management.
- Both may be brief stubs now; expand as the subtrees gain content.

## MCP wiring
- Server: `taylorwilsdon/google_workspace_mcp` (covers Tasks, Calendar, Drive/Docs).
- Register via `claude mcp add` or a hand-written `.mcp.json`. Store secrets in `.claude/settings.local.json`.
- Authorize against a personal @gmail account. OAuth consent screen user type is External; add that same account as a test user.

## Acceptance criteria
- [ ] Repo skeleton committed.
- [ ] CLAUDE.md is < 120 lines, loads (verify with `/memory`), and contains no feature specs.
- [ ] backend.md and frontend.md load only when a file in their subtree is read.
- [ ] Over MCP, the agent can list the account's task lists and read tasks.
- [ ] .gitignore covers tokens, `CLAUDE.local.md`, and `.claude/settings.local.json`.

## Out of scope (defer to later goals)
Backend endpoints; React panels; any skill file; backend OAuth; the scratchpad; any runtime LLM or MCP use.
