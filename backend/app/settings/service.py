"""Per-user settings service (goal 8) — replaces the NOTES_* / EXTRA_CALENDAR_IDS
env vars with a `user_settings` row per user.

Two pieces of per-user config:
- **Calendars:** the extra calendar ids merged into the day strip (primary always on).
- **Notes target:** the app-created notes folder + Doc ids in *this* user's Drive,
  bootstrapped on first need (`ensure_notes_target`). IDs are config-only (DB now),
  never LLM output; under `drive.file` the app can only touch files it created, so
  the folder + Doc must be app-created — never a user-pasted id. `ensure_notes_target`
  also **self-heals** (goal-8a): a stored id that this OAuth client can no longer
  reach (404 — client id changed across a deploy, or the user deleted the file) is
  dropped and re-bootstrapped, so a client-id change can't 404 every note forever.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.auth.models import UserSettings
from app.errors import ApiError
from app.google import docs as docs_client
from app.settings import notes_index

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

_NOTES_FOLDER_NAME = "Dashboard Notes"
_NOTES_DOC_NAME = "Dashboard — Notes"

# User ids whose stored notes ids have been probed-accessible in THIS process, so we
# skip the Drive probe on every subsequent note. Deliberately in-process (not the DB):
# a restart — i.e. a deploy, exactly when the OAuth client id might have changed —
# re-probes each user once. See `_verify_or_clear` and goal-8a.
_verified_targets: set[int] = set()

# Goal 9: the 8a self-heal probe extended to hierarchy Docs, keyed per
# (user_id, drive_id) so each hierarchy Doc is probed once per process. A definite
# 404 re-creates the Doc at the same path; the default-Doc/root-folder self-heal
# above is unchanged.
_verified_files: set[tuple[int, str]] = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _verify_or_clear(
    session: Session, creds: "Credentials", row: UserSettings
) -> None:
    """Drop stored notes ids that this OAuth client can no longer reach, so they
    re-bootstrap on the same call instead of being reused forever.

    Why (goal-8a): under `drive.file`, per-file access is keyed to the OAuth **client
    id** that created the file. If the client id changes across a deploy, the stored
    `notes_folder_id`/`notes_doc_id` become unreachable (404) — and the idempotency
    guard below (`if not row.notes_*`) would otherwise reuse those dead ids forever,
    404-ing every note write with no recovery. A user-deleted folder/Doc is the same
    signal. Only a definite 404 clears; a transient/other error propagates (fail
    closed — never nuke a good id). Cached per process so the healthy path pays the
    probe once per user per deploy, then nothing."""
    if not row.notes_folder_id and not row.notes_doc_id:
        return  # nothing stored yet → bootstrap path handles it, no probe needed
    if row.user_id in _verified_targets:
        return

    cleared = False
    if row.notes_folder_id and not await docs_client.file_accessible(
        creds, row.notes_folder_id
    ):
        # Folder gone → the Doc that lived inside it is unreachable too; drop both.
        row.notes_folder_id = None
        row.notes_doc_id = None
        cleared = True
    elif row.notes_doc_id and not await docs_client.file_accessible(
        creds, row.notes_doc_id
    ):
        # Folder still ours but the Doc isn't — recreate just the Doc in that folder.
        row.notes_doc_id = None
        cleared = True

    if cleared:
        row.updated_at = _now()
        session.add(row)
        session.commit()
        session.refresh(row)
        return  # do NOT mark verified — the recreated id gets probed next process

    _verified_targets.add(row.user_id)


def get_or_create(session: Session, user_id: int) -> UserSettings:
    row = session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def enabled_calendar_ids(settings: UserSettings) -> list[str]:
    try:
        ids = json.loads(settings.enabled_calendar_ids or "[]")
    except json.JSONDecodeError:
        return []
    return [str(c) for c in ids if isinstance(c, str) and c.strip()]


def get_enabled_calendar_ids(session: Session, user_id: int) -> list[str]:
    return enabled_calendar_ids(get_or_create(session, user_id))


def set_enabled_calendars(
    session: Session, user_id: int, calendar_ids: list[str]
) -> UserSettings:
    """Persist the user's toggled-on extra calendars (dedupe, drop blanks)."""
    seen: list[str] = []
    for cid in calendar_ids:
        c = (cid or "").strip()
        if c and c not in seen:
            seen.append(c)
    row = get_or_create(session, user_id)
    row.enabled_calendar_ids = json.dumps(seen)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def ensure_notes_target(
    session: Session, creds: "Credentials", user_id: int
) -> tuple[str, str]:
    """Return (doc_id, folder_id), app-creating the folder + Doc on first need.

    Idempotent: once the ids are stored they are reused. A Drive failure raises
    `ApiError` so the caller (router) leaves the entry re-routable — nothing is
    half-persisted that would block a retry (folder id is saved before the Doc is
    attempted, so a retry reuses the folder)."""
    row = get_or_create(session, user_id)

    try:
        # Self-heal stale ids (changed OAuth client id / user-deleted file) before the
        # reuse guards below, so a dead id re-bootstraps instead of 404-ing forever.
        await _verify_or_clear(session, creds, row)
        if not row.notes_folder_id:
            row.notes_folder_id = await docs_client.create_folder(
                creds, _NOTES_FOLDER_NAME
            )
            row.updated_at = _now()
            session.add(row)
            session.commit()
            session.refresh(row)
        if not row.notes_doc_id:
            row.notes_doc_id = await docs_client.create_doc_in_folder(
                creds, _NOTES_DOC_NAME, row.notes_folder_id
            )
            row.updated_at = _now()
            session.add(row)
            session.commit()
            session.refresh(row)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 — Drive create failed
        raise ApiError(
            502, "notes_bootstrap_failed", "Could not create your notes folder/Doc."
        ) from exc

    return row.notes_doc_id, row.notes_folder_id


# ── Notes hierarchy: the user-defined folder/Doc tree (goal 9) ────────────────


def get_notes_index(session: Session, user_id: int) -> list[dict]:
    """Return the stored notes forest (nodes with materialized drive_ids)."""
    return notes_index.parse(get_or_create(session, user_id).notes_index)


def _persist_index(session: Session, row: UserSettings, forest: list[dict]) -> None:
    """Persist the (possibly partially-materialized) forest immediately, so a Drive
    failure mid-apply never loses an already-created id (mirrors `ensure_notes_target`
    committing the folder id before the Doc)."""
    row.notes_index = notes_index.serialize(forest)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)


async def _materialize(
    session: Session,
    creds: "Credentials",
    row: UserSettings,
    forest: list[dict],
    stored_by_id: dict[str, dict],
    root_folder_id: str,
) -> None:
    """Create/rename Drive files to match `forest`, parent-before-child.

    Diff is **by `node_id`** against the stored tree: a node whose id already carries
    a materialized `drive_id` of the same kind is reused (rename if its name changed);
    a new id (or a doc→folder kind change — orphan + create) gets a fresh Drive
    file/folder under its parent. Each created/renamed drive_id is persisted as it
    succeeds, so a partial failure is resumable and a re-run is idempotent by id.
    Deletes need no Drive op (orphan-only) — an absent node simply isn't walked here.
    """

    async def process(nodes: list[dict], parent_drive_id: str) -> None:
        for node in nodes:
            prior = stored_by_id.get(node["node_id"])
            reusable = (
                prior is not None
                and prior.get("drive_id")
                and prior.get("kind") == node["kind"]
            )
            if reusable:
                node["drive_id"] = prior["drive_id"]
                if (prior.get("name") or "").strip() != node["name"]:
                    await docs_client.rename_file(creds, node["drive_id"], node["name"])
                    _persist_index(session, row, forest)
            else:
                if node["kind"] == notes_index.KIND_FOLDER:
                    node["drive_id"] = await docs_client.create_folder(
                        creds, node["name"], parent_id=parent_drive_id
                    )
                else:
                    node["drive_id"] = await docs_client.create_doc_in_folder(
                        creds, node["name"], parent_drive_id
                    )
                _persist_index(session, row, forest)
            if node["kind"] == notes_index.KIND_FOLDER:
                await process(node.get("children") or [], node["drive_id"])

    await process(forest, root_folder_id)


async def set_notes_index(
    session: Session, creds: "Credentials", user_id: int, incoming: list[dict]
) -> list[dict]:
    """Validate + eagerly materialize the edited tree, persist it, and return it.

    The root notes folder is ensured first (the tree is rooted under it). Validation
    (422 on violation) runs before any Drive op. On a Drive error partway through, the
    ids created so far are already persisted; the error is returned and a retry of the
    same PUT is idempotent by `node_id`.
    """
    forest = notes_index.sanitize_incoming(incoming)
    notes_index.validate(forest)

    row = get_or_create(session, user_id)
    _doc_id, folder_id = await ensure_notes_target(session, creds, user_id)
    stored_by_id = notes_index.index_by_node_id(notes_index.parse(row.notes_index))

    try:
        await _materialize(session, creds, row, forest, stored_by_id, folder_id)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 — a Drive create/rename failed
        raise ApiError(
            502, "notes_index_apply_failed", "Could not apply your notes hierarchy."
        ) from exc

    _persist_index(session, row, forest)
    return forest


async def _file_ok(
    session: Session, creds: "Credentials", user_id: int, drive_id: str
) -> bool:
    """Per-(user, file) reachability probe (goal-9 self-heal), cached per process.

    A definite 404 (client-id change / user-deleted file) → False; any other error
    fails closed by propagating. Mirrors `_verify_or_clear` but keyed per file so
    each hierarchy Doc is probed once."""
    if (user_id, drive_id) in _verified_files:
        return True
    ok = await docs_client.file_accessible(creds, drive_id)
    if ok:
        _verified_files.add((user_id, drive_id))
    return ok


async def resolve_note_target(
    session: Session, creds: "Credentials", user_id: int, path: str | None
) -> tuple[str, str, str | None]:
    """Resolve a routed note path → (doc_id, folder_id, canonical_path).

    `path` null / no leaf match → the default Doc (canonical_path None). A matched
    leaf whose Doc 404s is **self-healed**: the Doc (and any missing ancestor
    folders) is re-created **at the same path**, the index updated, and the fresh id
    returned. `folder_id` is always the root notes folder (the ancestry gate walks
    the Doc's parents up to it). A non-404 error fails closed (propagates), leaving
    the entry re-routable."""
    doc_id, folder_id = await ensure_notes_target(session, creds, user_id)
    if not path:
        return doc_id, folder_id, None

    row = get_or_create(session, user_id)
    forest = notes_index.parse(row.notes_index)
    chain = notes_index.locate_chain(forest, path)
    if chain is None:
        return doc_id, folder_id, None  # unknown path → default Doc

    canonical = notes_index.canonical_path(chain)
    leaf = chain[-1]
    leaf_drive_id = leaf.get("drive_id")
    if leaf_drive_id and await _file_ok(session, creds, user_id, leaf_drive_id):
        return leaf_drive_id, folder_id, canonical

    # Self-heal: re-create missing ancestor folders + the Doc at the same path,
    # persisting each new id, then update the index.
    parent_id = folder_id
    for node in chain[:-1]:
        node_drive = node.get("drive_id")
        if node_drive and await _file_ok(session, creds, user_id, node_drive):
            parent_id = node_drive
        else:
            node["drive_id"] = await docs_client.create_folder(
                creds, node["name"], parent_id=parent_id
            )
            parent_id = node["drive_id"]
            _persist_index(session, row, forest)
    leaf["drive_id"] = await docs_client.create_doc_in_folder(
        creds, leaf["name"], parent_id
    )
    _persist_index(session, row, forest)
    _verified_files.add((user_id, leaf["drive_id"]))
    return leaf["drive_id"], folder_id, canonical
