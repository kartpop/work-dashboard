"""The router classifier — the ONLY runtime LLM in the system (goal 5).

One Anthropic call per entry returns a schema-validated `RouterClassification`
(structured output). It *proposes* a destination + extracted fields and nothing
more: there is **no write call anywhere in this module** (LLM-proposes,
code-disposes — see router.md). Any error, refusal, or schema-invalid result
collapses to `unknown` → the deterministic step sends it to review. Never raises.

This module talks to Anthropic directly (the runtime LLM), exactly as the read
paths talk to Google directly — no MCP, no agent loop.
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime

import anthropic

from app.router import config
from app.router.schema import RouterClassification, unknown_classification

_log = logging.getLogger("router.classifier")

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

_SYSTEM = """You are a routing classifier for a personal productivity dashboard. \
You read one short captured thought and decide where it belongs. You ONLY classify \
and extract — you never take any action.

Destinations:
- "task": an actionable to-do ("call the dentist friday", "buy milk", "email Sam the deck").
  Extract: title (imperative, concise), list_hint (only if the user named a list, e.g. \
"#followups" or "work list"; else null), due_date (resolve relative dates to YYYY-MM-DD in \
IST using TODAY below; else null. "tomorrow" = TODAY + 1 day; "day after" / "day after \
tomorrow" = TODAY + 2 days; also handle named weekdays like "friday" and "next monday"), \
notes (any trailing detail; else null).
- "note": a thought to remember, not an action ("remember the Vsauce video on entropy", \
"idea: a CLI for X"). Extract: note_text (the cleaned thought), and summary (a single \
short phrase — a few words — capturing the note's essence, like a headline; NOT a rewrite \
of the note, NOT a full sentence).
- "event": something with other people at a specific time ("lunch with Tejas thursday 1pm", \
"standup moved to 10"). Extract: title, event_datetime (free text), attendees (free text).
- "unknown": genuinely ambiguous or unclassifiable input.

Confidence is your probability in [0,1] that BOTH the destination and the key fields are \
correct. Be honest and well-calibrated: use a LOW confidence (<0.7) for ambiguous inputs \
("Tejas?", "the thing from earlier") so they are sent for human review rather than guessed. \
A clear, unambiguous capture should score high (>0.9).

Output ONLY the structured classification."""


def _today_ist() -> str:
    return datetime.now(_IST).date().isoformat()


async def classify(text: str) -> RouterClassification:
    """Classify one captured entry. Returns `unknown` on any failure (never raises)."""
    try:
        client = anthropic.AsyncAnthropic()
        user = f"TODAY (IST): {_today_ist()}\n\nCaptured thought:\n{text.strip()}"
        resp = await client.messages.parse(
            model=config.ROUTER_MODEL,
            max_tokens=config.ROUTER_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=RouterClassification,
        )
        result = resp.parsed_output
        if result is None:
            # Refusal or unparseable output → schema gate fails → unknown.
            return unknown_classification()
        # Clamp a malformed confidence into range rather than trusting it blindly.
        result.confidence = max(0.0, min(1.0, result.confidence))
        return result
    except Exception:
        # Model error, auth error, network error — never crash the pipeline. Log
        # it, though: silently collapsing to `unknown` otherwise hides a misconfig
        # (e.g. a missing ANTHROPIC_API_KEY) as "every capture is unclassifiable".
        _log.exception("classifier call failed; routing to unknown")
        return unknown_classification()
