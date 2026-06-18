"""Router configuration (goal 5).

The router is the ONLY runtime LLM in the system. It does classification + light
extraction, not reasoning, so it runs on a small/cheap model — this is a product
decision stated in the goal-5 brief, not a quality compromise.
"""

from __future__ import annotations

import os

# Small / cheap model — the router classifies and lightly extracts; it never reasons.
ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "claude-haiku-4-5")

# Below this confidence, a task/note is NOT auto-acted — it lands in the review
# queue instead (the confidence gate from the guardrail contract).
CONFIDENCE_THRESHOLD = float(os.environ.get("ROUTER_CONFIDENCE_THRESHOLD", "0.7"))

# Max tokens for the classification response. This is extraction, not generation;
# the structured output is small.
ROUTER_MAX_TOKENS = 1024
