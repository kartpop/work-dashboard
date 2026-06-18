---
name: eval-runner
description: How to run the router eval set — both the single-looping baseline and the cost-instrumented dynamic-workflow fan-out (shard across eval-worker subagents, then aggregate). Use whenever scoring the goal-5 auto-router or running /eval.
---

# Router eval runner — launch recipe (HOW)

The labelled set lives at `backend/app/router/evals/cases.jsonl`; the runner is
`backend/app/router/evals/runner.py`. `score()` is a pure function; only the classify step hits
the network (the one runtime LLM). All commands run from `backend/` in the uv venv and need
`ANTHROPIC_API_KEY`. The router-under-test uses a small model (`ROUTER_MODEL`, default
`claude-haiku-4-5`) — that is *product* config, not harness config.

## A. Baseline — single looping run (the number to beat)

```
cd backend && uv run python -m app.router.evals.runner
```

Prints the scorecard (destination accuracy, per-class P/R, confusion matrix, calibration,
field-extraction, task false-positives) and `GATE: PASS/FAIL`. Note the wall-clock and, if you
want token cost, wrap with `/cost` before/after or read the Anthropic usage dashboard. This is the
**baseline** for the cost experiment.

## B. Dynamic workflow — fan-out across cheap-model workers

> **Verify the current spawn mechanism against the Claude Code docs in-session** (`/workflows`,
> /sub-agents). The shape below is the intent; the exact spawn syntax lives here in the skill, not
> baked into the goal brief.

1. **Fan out.** Spawn N `eval-worker` subagents (cheap model via their frontmatter), each with a
   distinct shard. **Batch, do NOT spawn one worker per case** — that is the literal worst case the
   "View usage" tab warns about. For ~32 cases, N=4 (≈8 cases each) is a sensible width; cap
   concurrency. Each worker runs:
   ```
   cd backend && uv run python -m app.router.evals.runner --shard k/N --out /tmp/eval-shard-k.json
   ```
   and returns only `SHARD k/N: wrote <count> → <path>` — the per-case JSON and classification
   noise stay in the worker's context (the g3 isolation property, applied to the 66%>150k problem).
2. **Aggregate (cheap, local, no API).** The lead combines the shard files and scores:
   ```
   cd backend && uv run python -m app.router.evals.runner --aggregate '/tmp/eval-shard-*.json'
   ```
   This is pure `score()` — no model calls — so it is free and fast.

## C. The cost experiment (the banked goal-5 lesson)

Run A and B on the *same* eval set and record both: token cost and wall-clock. The question to
answer in the wrap-up: **was the fan-out worth its token multiplier at ~32 cases, or does
parallelism only pay off at larger scale?** Expectation to confirm/refute: at this size the fan-out
adds subagent-overhead tokens (each worker re-establishes context) for little wall-clock win,
because the classify calls are short and cheap; fan-out pays off when the set is large enough that
the per-worker overhead amortizes. Bank the measured answer.

## Discipline (from the usage read)

- Cheap model in the worker **and** verifier frontmatter (`model: haiku`).
- `/clear` between g5 phases; `/compact` mid-phase; keep eval/curl noise inside subagents.
- Reserve `/effort ultracode` for designing the router prompt/schema/threshold — not the mechanical
  fan-out.
