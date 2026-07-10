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
  Extract: title (imperative, concise), target_list (which of the two lists it belongs to: \
"My Tasks" for the user's OWN to-dos — the default when unsure; "Follow-ups" ONLY when the \
task is about waiting on or chasing someone else, e.g. "follow up with Ravi on the contract", \
"ping Sam about the deck", "check if finance approved the invoice", or an explicit "#followups"), \
due_date (resolve relative dates to YYYY-MM-DD in IST using TODAY below; else null. \
"tomorrow" = TODAY + 1 day; "day after" / "day after tomorrow" = TODAY + 2 days; also handle \
named weekdays like "friday" and "next monday"), notes (any trailing detail; else null).
- "note": a thought to remember, not an action ("remember the Vsauce video on entropy", \
"idea: a CLI for X"). Extract:
  - note_text: the note body with ONLY the routing prefix stripped (see FILING below). \
Everything else is preserved **VERBATIM** — do NOT reword, summarize, or drop a single \
word. If there is no routing prefix, note_text is the raw text unchanged.
  - summary: a single short phrase (a few words) capturing the note's essence, like a \
headline; NOT a rewrite of the note, NOT a full sentence.
  - target_doc_path: which Doc in the user's hierarchy (FILING below) this note belongs \
to; null if none fits.
  - keywords: a few keywords, OPTIONAL — only when natural ones exist; omit otherwise.
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


def _filing_section(doc_paths: list[str] | None) -> str:
    """The dynamic per-user FILING block appended to the system prompt (goal 9).

    Renders the user's notes hierarchy as **paths only** (never Drive ids — the LLM
    proposes a path; deterministic code maps path → stored id). No hierarchy → note
    filing collapses to 'always the default Doc'."""
    if not doc_paths:
        return (
            "\n\nFILING (notes): the user has no notes hierarchy yet — always leave "
            "target_doc_path null (the note goes to the default Doc)."
        )
    listed = "\n".join(f"- {p}" for p in doc_paths)
    return (
        "\n\nFILING (notes): the user keeps per-topic notes Docs. When destination is "
        '"note", set target_doc_path to the ONE best-matching path below — by an '
        "explicit prefix (e.g. 'john growth — …' → conversations/john/growth) OR by "
        "content inference (e.g. 'discussed comp with john' → conversations/john/"
        "growth). If a prefix is present, strip ONLY that prefix from note_text and "
        "keep the rest verbatim. If nothing clearly fits, leave target_doc_path null "
        "(the note goes to the default Doc). Never invent a path not listed here.\n"
        f"{listed}"
    )


async def classify(
    text: str, doc_paths: list[str] | None = None
) -> RouterClassification:
    """Classify one captured entry. Returns `unknown` on any failure (never raises).

    `doc_paths` is the user's notes-hierarchy leaf paths (goal 9); it is injected
    into the system prompt so the LLM can propose a `target_doc_path`."""
    try:
        client = anthropic.AsyncAnthropic()
        user = f"TODAY (IST): {_today_ist()}\n\nCaptured thought:\n{text.strip()}"
        resp = await client.messages.parse(
            model=config.ROUTER_MODEL,
            max_tokens=config.ROUTER_MAX_TOKENS,
            system=_SYSTEM + _filing_section(doc_paths),
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
