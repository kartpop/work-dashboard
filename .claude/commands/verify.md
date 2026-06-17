---
description: Verify the active goal's acceptance criteria via the verifier subagent (never ad-hoc curl in the main session).
argument-hint: "[goal number, e.g. 4 — defaults to the highest-numbered goal-N.md]"
allowed-tools: Read, Bash(ls *), Agent
---

Verify the dashboard against the active goal's acceptance criteria. **All verification runs through
the `verifier` subagent** — do NOT run curl/Playwright/servers yourself in this session (that noise
must stay out of the main context; this is the goal-3 lesson the `/verify` command exists to enforce).

## Steps

1. Pick the goal file: if `$ARGUMENTS` names a number N, use `docs/goals/goal-N.md`; otherwise use the
   highest-numbered `docs/goals/goal-*.md`.
2. Read that file's **"Acceptance criteria"** section. These are the WHAT — they are written fresh per
   goal and must NOT be baked into the agent file or the skills.
3. Launch the **`verifier` subagent** (the Agent tool, `subagent_type: "verifier"`). The agent file is
   the WHO (role, tool allowlist, PASS/FAIL output shape); it preloads the `verifier-web` skill (launch
   recipe, endpoints, selectors). In the invocation prompt:
   - Paste the acceptance-criteria checklist verbatim as the checks to run.
   - For any goal that writes to Google (goal 4+), instruct it to ALSO load the **`verifier-writes`**
     skill and exercise every write-path check against the dedicated `zz-verifier-test` list ONLY,
     cleaning up afterwards — never against real task lists.
   - Tell it to return the standard PASS/FAIL report (<40 lines), no raw curl/screenshot dumps.
4. Relay the subagent's PASS/FAIL report to me. If anything FAILED, summarize the failing checks and
   stop for a decision — do not silently "fix and re-verify" without surfacing what broke.

## Preconditions to remind the agent about (it handles them via the skill)
- Backend on :8010, frontend on :5173, both started per `verifier-web`.
- Overlay DB migrated (`alembic upgrade head`).
- For goal 4+ write checks: the OAuth token must carry the read/write `tasks` scope. If write calls
  return 403/insufficient-scope, that's a token problem (the user must re-run
  `uv run python -m app.google.auth`), not a code failure — report it as a BLOCKED check, not a FAIL.
