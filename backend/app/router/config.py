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
# the structured output is small — but see CLASSIFY_MAX_CHARS: `note_text` is a
# VERBATIM echo, so the response is only small while the input is bounded. Headroom
# is free (max_tokens is a cap, not a cost), and running out of it is catastrophic
# rather than degraded: a truncated response is unparseable JSON, so the WHOLE
# classification collapses to `unknown`.
ROUTER_MAX_TOKENS = 2048

# The most capture text the classifier is ever SHOWN. A longer capture is excerpted
# to this head (`classifier._excerpt`) and any `note_text` it echoes back is discarded
# (`classify` nulls it) — code supplies the body instead.
#
# Why (goal 10a): `note_text` is the body echoed back verbatim, so the response scales
# with the input. Measured on the ~10k-char paste that broke in production: the model
# spends its whole output budget retyping the body and then returns summary,
# target_doc_path AND keywords as null — the note files to the default Doc with no
# one-liner and no keywords. Worse, the echo it produces is silently ABRIDGED (4.1k
# chars back from 9.9k in), so the body can't be trusted either. Truncating the INPUT
# is what actually fixes it: it bounds the echo's cost so the model has budget left
# for the fields we actually need, and those fields (destination, doc path, summary)
# read off the head of a capture anyway — the routing header is literally the first
# line. Below this, nothing changes: the goal-9 echo still does the prefix stripping
# it was built for.
CLASSIFY_MAX_CHARS = 1200
