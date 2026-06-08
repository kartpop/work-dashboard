# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A personal work dashboard that surfaces Google Tasks, Calendar, and Drive alongside a small
task-metadata overlay.

## Stack

- Backend: FastAPI (Python)
- Frontend: React
- Storage: SQLite locally, Postgres in production, for the task-metadata overlay only

## Repo map

```
CLAUDE.md
.claude/
├── rules/            # path-scoped conventions (backend.md, frontend.md)
└── skills/           # empty for now
.mcp.json             # Google Workspace MCP registration
docs/goals/           # goal specs, one per milestone
backend/              # FastAPI app
frontend/             # React app
```

## Before starting work

Read `docs/goals/<current-goal>.md` before starting work. It defines the objective, scope, and
acceptance criteria for the active milestone — do not work outside that scope.

## Run / test

Stubs only at this stage; backend and frontend have no runnable app yet. Commands will be added
here once each subtree has a build.

## Hard constraints

- Never commit OAuth tokens, `CLAUDE.local.md`, or `.claude/settings.local.json`.
- Dashboard read paths call the Google API client directly. Do not use MCP or an LLM to read tasks, calendar, or drive.
