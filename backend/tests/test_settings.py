"""Per-user settings service — the goal-8a self-heal of stale notes ids.

`ensure_notes_target` bootstraps the notes folder+Doc on first need (covered by
`test_router.py`). These tests pin the goal-8a addition: a stored id this OAuth
client can no longer reach (404 — the client id changed across a deploy, or the
user deleted the file) is dropped and re-bootstrapped, so a client-id change can't
404 every note write forever. Only a definite 404 clears; a transient/other error
must NOT discard a still-good id.
"""

from __future__ import annotations

import asyncio

import pytest
from googleapiclient.errors import HttpError

from app.auth.models import UserSettings
from app.settings import service as settings_svc
from tests.conftest import DummyCreds


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_verified_cache():
    """The in-process verified-ids cache leaks across tests otherwise."""
    settings_svc._verified_targets.clear()
    yield
    settings_svc._verified_targets.clear()


def _http_error(status: int) -> HttpError:
    class _Resp:
        def __init__(self, s):
            self.status = s
            self.reason = "err"

    return HttpError(_Resp(status), b"{}")


def _settings(session, user, **fields) -> UserSettings:
    row = UserSettings(user_id=user.id, **fields)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _mock_creates(monkeypatch, folder="FOLDER-new", doc="DOC-new"):
    async def _create_folder(creds, name):
        return folder

    async def _create_doc_in_folder(creds, title, folder_id):
        return doc

    monkeypatch.setattr("app.google.docs.create_folder", _create_folder)
    monkeypatch.setattr("app.google.docs.create_doc_in_folder", _create_doc_in_folder)


def _mock_accessible(monkeypatch, verdict):
    """`verdict(file_id)` → True (reachable), False (404), or an HttpError to raise."""

    async def _file_accessible(creds, file_id):
        v = verdict(file_id)
        if isinstance(v, HttpError):
            raise v
        return v

    monkeypatch.setattr("app.google.docs.file_accessible", _file_accessible)


def test_reachable_ids_are_reused_without_recreate(session, user_a, monkeypatch):
    """Healthy path: both stored ids probe-accessible → reused, nothing created."""
    _settings(session, user_a, notes_folder_id="FOLDER-old", notes_doc_id="DOC-old")
    _mock_accessible(monkeypatch, lambda fid: True)

    async def _boom(*a, **k):  # a create here would be a bug
        raise AssertionError("must not create when ids are still reachable")

    monkeypatch.setattr("app.google.docs.create_folder", _boom)
    monkeypatch.setattr("app.google.docs.create_doc_in_folder", _boom)

    doc_id, folder_id = run(
        settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id)
    )
    assert (doc_id, folder_id) == ("DOC-old", "FOLDER-old")


def test_gone_folder_reboots_both_ids(session, user_a, monkeypatch):
    """Client id changed → folder 404s → both ids re-bootstrapped in the same call."""
    _settings(session, user_a, notes_folder_id="FOLDER-old", notes_doc_id="DOC-old")
    _mock_accessible(monkeypatch, lambda fid: False)  # nothing is ours anymore
    _mock_creates(monkeypatch, folder="FOLDER-new", doc="DOC-new")

    doc_id, folder_id = run(
        settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id)
    )
    assert (doc_id, folder_id) == ("DOC-new", "FOLDER-new")
    row = session.get(UserSettings, user_a.id)
    assert row.notes_folder_id == "FOLDER-new"
    assert row.notes_doc_id == "DOC-new"


def test_gone_doc_keeps_folder_recreates_doc(session, user_a, monkeypatch):
    """Only the Doc was deleted → keep the still-ours folder, recreate the Doc in it."""
    _settings(session, user_a, notes_folder_id="FOLDER-old", notes_doc_id="DOC-old")
    _mock_accessible(monkeypatch, lambda fid: fid != "DOC-old")  # folder ok, doc gone

    captured = {}

    async def _create_doc_in_folder(creds, title, folder_id):
        captured["folder_id"] = folder_id
        return "DOC-new"

    async def _create_folder(creds, name):
        raise AssertionError("folder is still reachable — must not recreate it")

    monkeypatch.setattr("app.google.docs.create_folder", _create_folder)
    monkeypatch.setattr("app.google.docs.create_doc_in_folder", _create_doc_in_folder)

    doc_id, folder_id = run(
        settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id)
    )
    assert (doc_id, folder_id) == ("DOC-new", "FOLDER-old")
    assert captured["folder_id"] == "FOLDER-old"  # recreated INSIDE the kept folder


def test_transient_error_never_discards_a_good_id(session, user_a, monkeypatch):
    """A non-404 probe error (e.g. 500) must NOT clear ids — it raises, ids intact."""
    _settings(session, user_a, notes_folder_id="FOLDER-old", notes_doc_id="DOC-old")
    _mock_accessible(monkeypatch, lambda fid: _http_error(500))

    from app.errors import ApiError

    with pytest.raises(ApiError):
        run(settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id))

    row = session.get(UserSettings, user_a.id)
    assert row.notes_folder_id == "FOLDER-old"  # untouched
    assert row.notes_doc_id == "DOC-old"


def test_probe_is_cached_per_process(session, user_a, monkeypatch):
    """After one accessible probe the id is trusted for the process — no re-probe."""
    _settings(session, user_a, notes_folder_id="FOLDER-old", notes_doc_id="DOC-old")
    calls = {"n": 0}

    async def _file_accessible(creds, file_id):
        calls["n"] += 1
        return True

    monkeypatch.setattr("app.google.docs.file_accessible", _file_accessible)

    run(settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id))
    first = calls["n"]
    run(settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id))
    assert calls["n"] == first  # second call probed nothing
