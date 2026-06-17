"""Google write orchestration (goal 4+).

Sequences Google API write calls with overlay-row updates. Routers stay thin
and call into this service; the thin per-call wrappers live in
`app.google.tasks`. See `.claude/rules/writes.md` for the safety invariants.
"""
