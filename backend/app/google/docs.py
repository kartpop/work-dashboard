"""Thin Google Docs / Drive client for the notes writer (goal 7).

The app's ENTIRE Docs/Drive surface — insert a note, read a doc's parents (the
folder-ancestry gate), and the one sanctioned file-create (the bootstrap). Each
function is one Google call, no orchestration (that lives in `app.writes.service`);
same sync `_fn` / `async def` + `asyncio.to_thread` split as the other clients.

**Scope is `drive.file` only** (ADR: docs/goals/architecture/drive-access-scoping.md).
Google enforces that the token can touch only files the app created, so the sole
create path (`create_doc_in_folder`) hard-codes `parents=[folder_id]` — every doc the
app can ever reach lives under that folder. This module NEVER deletes a file, never
overwrites a doc's contents, and never does a `files.update` content rewrite — the
insert is the only mutation of an existing doc, and it is insert-only.
"""

from __future__ import annotations

import asyncio

from googleapiclient.discovery import build

from app.google.auth import load_credentials

_DOC_MIME = "application/vnd.google-apps.document"


def _docs_service():
    return build("docs", "v1", credentials=load_credentials(), cache_discovery=False)


def _drive_service():
    return build("drive", "v3", credentials=load_credentials(), cache_discovery=False)


# ── Read helper: the folder-ancestry gate's one Drive call ────────────────────


def _get_parents(file_id: str) -> list[str]:
    service = _drive_service()
    meta = service.files().get(fileId=file_id, fields="parents").execute()
    return meta.get("parents", []) or []


async def get_parents(file_id: str) -> list[str]:
    """Return a file's direct parent folder ids (for the ancestry gate)."""
    return await asyncio.to_thread(_get_parents, file_id)


# ── Insert-only note write (Docs batchUpdate) ─────────────────────────────────


def _insert_note(doc_id: str, heading_text: str, body_text: str) -> None:
    """Insert a Heading-3 timestamp + verbatim body at the TOP of the doc body.

    Newest note always lands first. Index 1 is the start of the body; a single
    batchUpdate applies its requests sequentially, so the style ranges see the
    just-inserted text. Insert-only — nothing existing is deleted or overwritten.

    A trailing empty paragraph is styled as a light-gray delimiter with spacing
    above/below (goal 7a) — the Docs API has no horizontal-rule request, so a
    `borderBottom` on an empty paragraph is the closest insert-only equivalent —
    so consecutive notes read as separated entries, not a run-on wall. The
    delimiter also keeps the previously top-most content in its own paragraph.
    """
    service = _docs_service()

    # Block: "<heading>\n<body>\n\n" — heading paragraph, body paragraph, and a
    # trailing EMPTY paragraph that carries the delimiter styling below.
    block = f"{heading_text}\n{body_text}\n\n"
    heading_end = 1 + len(heading_text) + 1  # end index of the heading paragraph
    body_end = heading_end + len(body_text) + 1  # end index of the body paragraph
    delim_end = body_end + 1  # end index of the empty delimiter paragraph

    requests: list[dict] = [
        {"insertText": {"location": {"index": 1}, "text": block}},
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": heading_end},
                "paragraphStyle": {"namedStyleType": "HEADING_3"},
                "fields": "namedStyleType",
            }
        },
    ]
    if body_text:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": heading_end, "endIndex": body_end},
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType",
                }
            }
        )
    # The trailing empty paragraph → a light-gray horizontal delimiter with
    # breathing room, separating this note from the one below. Insert-only: this
    # styles the just-inserted empty paragraph, never any pre-existing content.
    requests.append(
        {
            "updateParagraphStyle": {
                "range": {"startIndex": body_end, "endIndex": delim_end},
                "paragraphStyle": {
                    "namedStyleType": "NORMAL_TEXT",
                    "spaceAbove": {"magnitude": 8, "unit": "PT"},
                    "spaceBelow": {"magnitude": 8, "unit": "PT"},
                    "borderBottom": {
                        "color": {
                            "color": {
                                "rgbColor": {"red": 0.8, "green": 0.8, "blue": 0.8}
                            }
                        },
                        "width": {"magnitude": 1, "unit": "PT"},
                        "padding": {"magnitude": 0, "unit": "PT"},
                        "dashStyle": "SOLID",
                    },
                },
                "fields": "namedStyleType,spaceAbove,spaceBelow,borderBottom",
            }
        }
    )

    service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()


async def insert_note(doc_id: str, heading_text: str, body_text: str) -> None:
    """Insert a timestamped note at the top of the configured Doc (insert-only)."""
    await asyncio.to_thread(_insert_note, doc_id, heading_text, body_text)


# ── The ONE sanctioned file-create (bootstrap only) ───────────────────────────


def _create_doc_in_folder(title: str, folder_id: str) -> str:
    """Create an empty Google Doc INSIDE `folder_id` and return its id.

    The parent is hard-coded to the caller-supplied folder — there is no code path
    that creates a file anywhere else, so the app's entire reachable file set lives
    under the notes folder. Called only by the bootstrap command.
    """
    service = _drive_service()
    created = (
        service.files()
        .create(
            body={"name": title, "mimeType": _DOC_MIME, "parents": [folder_id]},
            fields="id",
        )
        .execute()
    )
    return created["id"]


async def create_doc_in_folder(title: str, folder_id: str) -> str:
    """Create the notes Doc inside the designated folder (bootstrap; returns its id)."""
    return await asyncio.to_thread(_create_doc_in_folder, title, folder_id)
