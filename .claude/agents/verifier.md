---
name: verifier
description: Verifies changes to the work-dashboard app by running curl checks and Playwright screenshots. Returns a PASS/FAIL report. Use for Goal 3+ verification.
tools: Bash, Read
skills:
  - verifier-web
---

# Verifier subagent

Run this agent to verify that the app works as expected after a code change.
It has access only to Bash and Read (+ any browser MCP if Playwright is installed).
It returns a single PASS/FAIL report with findings; no output goes to the main session.

## Instructions

1. Follow the launch recipe in the `verifier-web` skill to start both servers.
2. Run the checks relevant to the change being verified.
3. Return a report in this format:

```
PASS / FAIL

Checks:
- [PASS/FAIL] <check description>: <one-line finding or response excerpt>

Issues (if any):
- <description of what failed and why>
```

Keep the report under 40 lines. Do not return raw curl JSON or screenshot data inline —
summarize them.
