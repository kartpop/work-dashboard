---
description: Score the goal-5 auto-router against the labelled eval set and report the gate (PASS/FAIL). Runs the cost-instrumented dynamic-workflow fan-out by default.
argument-hint: "[baseline | fanout] — default fanout (shard across eval-worker subagents)"
allowed-tools: Read, Bash(cd backend && uv run *), Agent
---

Score the router classifier against the labelled eval set and report whether it meets the goal-5
gate. Load the **`eval-runner`** skill for the launch recipe (baseline vs. fan-out commands, the
cost experiment, and the discipline notes) — the HOW lives in the skill, not here.

## Steps

1. Confirm `ANTHROPIC_API_KEY` is set. If not, STOP and tell me — without it the classifier routes
   everything to `unknown` and the scorecard is meaningless.
2. **If `$ARGUMENTS` is `baseline`:** run the single-looping baseline directly
   (`uv run python -m app.router.evals.runner`) and relay the scorecard + GATE line. Note the
   wall-clock / token cost so it can be compared to the fan-out.
3. **Otherwise (default — fan-out):** run the dynamic workflow per the skill:
   - Spawn **4** `eval-worker` subagents (`subagent_type: "eval-worker"`, cheap model via their
     frontmatter), shards `0/4 … 3/4`, each writing `/tmp/eval-shard-k.json`. **Batch — never one
     worker per case.** Each returns only a one-line summary (the classification noise stays in the
     worker's context).
   - Then aggregate locally (no API): `uv run python -m app.router.evals.runner --aggregate
     '/tmp/eval-shard-*.json'`.
4. Relay the scorecard verbatim and the **GATE: PASS/FAIL**. If it FAILED, summarize the failing
   metric (clear accuracy < 0.90, or task false-positives > 0, or an ambiguous case auto-written)
   and STOP for a decision — do not silently tweak the prompt and re-run.
5. If both baseline and fan-out were run, record the **token/wall-clock cost of each** — that
   comparison is the headline harness lesson of goal 5.
