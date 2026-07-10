"""Thin Google Docs / Drive client for the notes writer (goal 7).

The app's ENTIRE Docs/Drive surface — insert a note, read a doc's parents (the
folder-ancestry gate), and the one sanctioned file-create (the bootstrap). Each
function is one Google call, no orchestration (that lives in `app.writes.service`);
same sync `_fn` / `async def` + `asyncio.to_thread` split as the other clients.

**Scope is `drive.file` only** (ADR: docs/goals/architecture/drive-access-scoping.md).
Google enforces that the token can touch only files the app created, so the sole
create path (`create_doc_in_folder`) hard-codes `parents=[folder_id]` — every doc the
app can ever reach lives under that folder. This module NEVER deletes a file and never
overwrites a doc's contents — the insert is the only mutation of a doc's *body*, and it
is insert-only. The one `files.update` here (`rename_file`, goal 9) is **metadata-only**
(`{"name": ...}` — never content, parents, or trashed) and is called only from the
settings/rename path (never the router — AST-asserted).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

_DOC_MIME = "application/vnd.google-apps.document"
_FOLDER_MIME = "application/vnd.google-apps.folder"

# When the LLM gives no one-liner, the H3 headline still exists (a placeholder) so
# the heading levels stay uniform — H3 = one-liner, H4 = timestamp, H5 = keywords —
# across every note. A future "extract all H4s" search then reliably yields every
# timestamp without the level shifting per-entry (goal 9).
_NO_SUMMARY_PLACEHOLDER = "—"


def _docs_service(creds: "Credentials"):
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _drive_service(creds: "Credentials"):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── Read helper: the folder-ancestry gate's one Drive call ────────────────────


def _get_parents(creds: "Credentials", file_id: str) -> list[str]:
    service = _drive_service(creds)
    meta = service.files().get(fileId=file_id, fields="parents").execute()
    return meta.get("parents", []) or []


async def get_parents(creds: "Credentials", file_id: str) -> list[str]:
    """Return a file's direct parent folder ids (for the ancestry gate)."""
    return await asyncio.to_thread(_get_parents, creds, file_id)


# ── Accessibility probe: is a stored file still reachable by THIS client? ──────


def _file_accessible(creds: "Credentials", file_id: str) -> bool:
    """True if this OAuth client can still see `file_id` (a plain `files.get` read).

    Under `drive.file`, per-file access is keyed to the OAuth **client id** that
    created the file — so a file created by a *different* client id (or a file the
    user deleted) returns **404** to this client even though the id is well-formed.
    That 404 is the definitive "no longer ours" signal → `False`. Any other error
    (403/5xx/transient) is NOT a not-found signal, so we re-raise and let the caller
    fail closed rather than discard a still-good id. Never a mutation — a read.
    """
    service = _drive_service(creds)
    try:
        service.files().get(fileId=file_id, fields="id").execute()
        return True
    except HttpError as exc:
        if getattr(exc, "resp", None) is not None and exc.resp.status == 404:
            return False
        raise


async def file_accessible(creds: "Credentials", file_id: str) -> bool:
    """Return whether the current client can still reach a stored file (see above)."""
    return await asyncio.to_thread(_file_accessible, creds, file_id)


# ── Insert-only note write (Docs batchUpdate) ─────────────────────────────────


def _keyword_line(keywords: list[str] | None) -> str:
    """Render keywords as one comma-separated line, or "" when there are none."""
    if not keywords:
        return ""
    return ", ".join(k.strip() for k in keywords if k and k.strip())


def _insert_note(
    creds: "Credentials",
    doc_id: str,
    heading_text: str,
    body_text: str,
    summary_text: str | None = None,
    keywords: list[str] | None = None,
) -> None:
    """Insert an H3 one-liner → H4 timestamp → H5 keywords → body → delimiter at the TOP.

    Newest note always lands first. Index 1 is the start of the block; a single
    batchUpdate applies its requests sequentially, so the style ranges see the
    just-inserted text. Insert-only — nothing existing is deleted or overwritten.

    Entry shape (goal 9): the LLM one-liner is **always the H3** headline, the timestamp
    **always the H4** beneath it, then optional **H5** keywords (comma-separated), the
    verbatim body, and the delimiter. The heading levels are **stable per note** — a
    missing summary uses a placeholder H3 (never promotes the timestamp) so the timestamp
    stays H4 for **every** entry; empty/missing keywords skip only the (leaf-level) H5.
    That uniformity is deliberate: a future "extract all H4s" search must reliably yield
    every timestamp, which only holds if the level never shifts per-entry. Nothing blocks
    the write.

    A trailing empty paragraph is styled as a light-gray delimiter with spacing
    above/below (goal 7a) — the Docs API has no horizontal-rule request, so a
    `borderBottom` on an empty paragraph is the closest insert-only equivalent —
    so consecutive notes read as separated entries, not a run-on wall.
    """
    service = _docs_service(creds)

    summary_text = (summary_text or "").strip() or _NO_SUMMARY_PLACEHOLDER
    keyword_text = _keyword_line(keywords)

    # The ordered paragraphs that make up this entry: (text, named-style). The
    # one-liner is ALWAYS the H3 headline and the timestamp ALWAYS the H4 beneath it —
    # a blank summary uses a placeholder rather than shifting the timestamp up, so the
    # heading levels stay uniform for later heading-extraction search. The body is
    # always present (even if empty); only the H5 keyword line is conditional.
    lines: list[tuple[str, str]] = [
        (summary_text, "HEADING_3"),
        (heading_text, "HEADING_4"),
    ]
    if keyword_text:
        lines.append((keyword_text, "HEADING_5"))
    lines.append((body_text, "NORMAL_TEXT"))

    # Block: every line + "\n", then a trailing EMPTY paragraph for the delimiter.
    block = "".join(f"{text}\n" for text, _ in lines) + "\n"
    requests: list[dict] = [{"insertText": {"location": {"index": 1}, "text": block}}]

    idx = 1  # running start index (body starts at doc index 1)
    for text, style in lines:
        end = idx + len(text) + 1
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType",
                }
            }
        )
        idx = end

    # The trailing empty paragraph → a light-gray horizontal delimiter with
    # breathing room, separating this note from the one below. Insert-only: this
    # styles the just-inserted empty paragraph, never any pre-existing content.
    delim_end = idx + 1
    requests.append(
        {
            "updateParagraphStyle": {
                "range": {"startIndex": idx, "endIndex": delim_end},
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


async def insert_note(
    creds: "Credentials",
    doc_id: str,
    heading_text: str,
    body_text: str,
    summary_text: str | None = None,
    keywords: list[str] | None = None,
) -> None:
    """Insert a timestamped note at the top of the configured Doc (insert-only).

    Optional `summary_text` → the H3 one-liner headline (a placeholder when absent, so
    the timestamp stays H4); optional `keywords` → an H5 line (goal 9). Both are the
    only LLM-authored lines; the body stays verbatim.
    """
    await asyncio.to_thread(
        _insert_note, creds, doc_id, heading_text, body_text, summary_text, keywords
    )


# ── The sanctioned file-creates (bootstrap only) ──────────────────────────────


def _create_folder(
    creds: "Credentials", name: str, parent_id: str | None = None
) -> str:
    """Create a folder and return its id.

    Goal 8: each user's notes folder is app-created (`drive.file` can't write into a
    user-chosen folder). No `parent_id` → Drive root (the root "Dashboard Notes"
    folder). Goal 9: hierarchy folders pass `parent_id` = their parent folder's id
    so the whole tree stays under the root notes folder. Still `files.create` — the
    app's entire reachable set stays app-created.
    """
    service = _drive_service(creds)
    body: dict = {"name": name, "mimeType": _FOLDER_MIME}
    if parent_id:
        body["parents"] = [parent_id]
    created = service.files().create(body=body, fields="id").execute()
    return created["id"]


async def create_folder(
    creds: "Credentials", name: str, parent_id: str | None = None
) -> str:
    """Create a folder (root notes folder, or a hierarchy folder under `parent_id`)."""
    return await asyncio.to_thread(_create_folder, creds, name, parent_id)


def _create_doc_in_folder(creds: "Credentials", title: str, folder_id: str) -> str:
    """Create an empty Google Doc INSIDE `folder_id` and return its id.

    The parent is hard-coded to the caller-supplied folder — there is no code path
    that creates a file anywhere else, so the app's entire reachable file set lives
    under the notes folder. Called only by the bootstrap path.
    """
    service = _drive_service(creds)
    created = (
        service.files()
        .create(
            body={"name": title, "mimeType": _DOC_MIME, "parents": [folder_id]},
            fields="id",
        )
        .execute()
    )
    return created["id"]


async def create_doc_in_folder(creds: "Credentials", title: str, folder_id: str) -> str:
    """Create the notes Doc inside the designated folder (bootstrap; returns its id)."""
    return await asyncio.to_thread(_create_doc_in_folder, creds, title, folder_id)


# ── The one sanctioned metadata mutation: rename (goal 9) ─────────────────────


def _rename_file(creds: "Credentials", file_id: str, name: str) -> None:
    """Rename a file/folder — a **metadata-only** `files.update` (goal 9).

    The request body is **exactly `{"name": name}`** — never content, never
    `parents` (no add/remove), never `trashed`. This is the ONLY `files.update` in
    the module and is a **settings-path-only** caller (the router never reaches it —
    AST-asserted), so the Drive name and the routing name never drift. Not a
    content overwrite; the insert-only note write is untouched.
    """
    service = _drive_service(creds)
    service.files().update(fileId=file_id, body={"name": name}, fields="id").execute()


async def rename_file(creds: "Credentials", file_id: str, name: str) -> None:
    """Rename a Drive file/folder (metadata-only; settings/rename path only)."""
    await asyncio.to_thread(_rename_file, creds, file_id, name)
