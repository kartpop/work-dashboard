"""Endpoint tests for the goal-4 write paths (reschedule + move).

Google is fully mocked: the async `app.google.tasks.*` wrappers are replaced with
recording stubs so we can assert call counts, arguments, and ordering (insert
before delete) without touching the real API or needing write scope.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.google.tasks import _UNSET, _reshape_task
from app.main import app
from app.overlay.models import TaskGroup, TaskOverlay

# A fixed RFC3339 due that maps to the IST bucket "2026-06-15".
DUE_0615 = "2026-06-15T00:00:00.000Z"


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine):
    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


class Recorder:
    """Holds async stubs for the Google client and records every call in order."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.tasks: dict[tuple[str, str], dict] = {}
        self.insert_result: dict = {"id": "new-task"}
        self.insert_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.update_error: Exception | None = None
        self.content_error: Exception | None = None

    async def get_task(self, tasklist_id, task_id):
        self.calls.append(("get_task", tasklist_id, task_id))
        return self.tasks.get((tasklist_id, task_id))

    async def update_due_date(self, tasklist_id, task_id, due):
        self.calls.append(("update_due_date", tasklist_id, task_id, due))
        if self.update_error:
            raise self.update_error

    async def insert_task(self, tasklist_id, body):
        self.calls.append(("insert_task", tasklist_id, body))
        if self.insert_error:
            raise self.insert_error
        # Mirror the real wrapper: echo the body, then reshape to the stable shape
        # (adds due / notes / parent keys) so create returns a full task.
        return _reshape_task({**self.insert_result, **body})

    async def delete_task(self, tasklist_id, task_id):
        self.calls.append(("delete_task", tasklist_id, task_id))
        if self.delete_error:
            raise self.delete_error

    async def update_task_content(
        self, tasklist_id, task_id, title=_UNSET, notes=_UNSET, status=_UNSET
    ):
        body = {}
        if title is not _UNSET:
            body["title"] = title
        if notes is not _UNSET:
            body["notes"] = notes
        if status is not _UNSET:
            body["status"] = status
        self.calls.append(("update_task_content", tasklist_id, task_id, body))
        if self.content_error:
            raise self.content_error
        base = self.tasks.get((tasklist_id, task_id), {"id": task_id})
        return {**base, **body}

    async def update_tasklist(self, tasklist_id, title):
        self.calls.append(("update_tasklist", tasklist_id, title))
        return {"id": tasklist_id, "title": title}

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def google(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("app.google.tasks.get_task", rec.get_task)
    monkeypatch.setattr("app.google.tasks.update_due_date", rec.update_due_date)
    monkeypatch.setattr("app.google.tasks.insert_task", rec.insert_task)
    monkeypatch.setattr("app.google.tasks.delete_task", rec.delete_task)
    monkeypatch.setattr("app.google.tasks.update_task_content", rec.update_task_content)
    monkeypatch.setattr("app.google.tasks.update_tasklist", rec.update_tasklist)
    return rec


def _seed_task(google, list_id="L1", task_id="T1", **fields):
    google.tasks[(list_id, task_id)] = {
        "id": task_id,
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
        **fields,
    }


# ── reschedule ────────────────────────────────────────────────────────────────


def test_reschedule_to_different_bucket(client, google, session):
    # Current task has no due (NO_DATE bucket); target is 2026-06-15.
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
    }
    resp = client.post(
        "/tasks/L1/T1/reschedule",
        json={"due_date": "2026-06-15", "rank": 100.0, "group_id": None},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "tasklist_id": "L1",
        "task_id": "T1",
        "due": DUE_0615,
        "rank": 100.0,
        "group_id": None,
    }
    # update_due_date called exactly once with the RFC3339 form.
    updates = [c for c in google.calls if c[0] == "update_due_date"]
    assert updates == [("update_due_date", "L1", "T1", DUE_0615)]
    # Overlay row reflects rank + group.
    row = session.get(TaskOverlay, ("L1", "T1"))
    assert row is not None and row.rank == 100.0 and row.group_id is None


def test_reschedule_idempotent_same_bucket(client, google, session):
    # Task already due on 2026-06-15; target bucket equals current → no Google write.
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": DUE_0615,
        "notes": None,
    }
    resp = client.post(
        "/tasks/L1/T1/reschedule",
        json={"due_date": "2026-06-15", "rank": 50.0, "group_id": None},
    )
    assert resp.status_code == 200
    assert "update_due_date" not in google.names()
    # Overlay still upserted.
    row = session.get(TaskOverlay, ("L1", "T1"))
    assert row is not None and row.rank == 50.0


def test_reschedule_to_no_date_clears_due(client, google, session):
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": DUE_0615,
        "notes": None,
    }
    resp = client.post(
        "/tasks/L1/T1/reschedule",
        json={"due_date": None, "rank": 10.0, "group_id": None},
    )
    assert resp.status_code == 200
    assert resp.json()["due"] is None
    updates = [c for c in google.calls if c[0] == "update_due_date"]
    assert updates == [("update_due_date", "L1", "T1", None)]


def test_reschedule_group_wrong_bucket_422(client, google, session):
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
    }
    # Group lives in a DIFFERENT bucket than the destination.
    grp = TaskGroup(tasklist_id="L1", bucket_key="2026-06-20", name="g", rank=1.0)
    session.add(grp)
    session.commit()
    session.refresh(grp)

    resp = client.post(
        "/tasks/L1/T1/reschedule",
        json={"due_date": "2026-06-15", "rank": 5.0, "group_id": grp.id},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "group_wrong_bucket"
    # No Google write, no overlay row created.
    assert "update_due_date" not in google.names()
    assert session.get(TaskOverlay, ("L1", "T1")) is None


def test_reschedule_group_correct_bucket_200(client, google, session):
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
    }
    grp = TaskGroup(tasklist_id="L1", bucket_key="2026-06-15", name="g", rank=1.0)
    session.add(grp)
    session.commit()
    session.refresh(grp)

    resp = client.post(
        "/tasks/L1/T1/reschedule",
        json={"due_date": "2026-06-15", "rank": 5.0, "group_id": grp.id},
    )
    assert resp.status_code == 200
    assert resp.json()["group_id"] == grp.id
    row = session.get(TaskOverlay, ("L1", "T1"))
    assert row is not None and row.group_id == grp.id


def test_reschedule_task_not_found_404(client, google):
    resp = client.post(
        "/tasks/L1/missing/reschedule",
        json={"due_date": "2026-06-15", "rank": 1.0, "group_id": None},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "task_not_found"


# ── move ──────────────────────────────────────────────────────────────────────


def test_move_happy_path(client, google, session):
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": DUE_0615,
        "notes": "n",
    }
    google.insert_result = {
        "id": "NEW1",
        "title": "x",
        "status": "needsAction",
        "due": DUE_0615,
        "notes": "n",
    }
    # Seed a source overlay row to verify migration.
    session.add(TaskOverlay(tasklist_id="L1", task_id="T1", rank=9.0, group_id=None))
    session.commit()

    resp = client.post("/tasks/L1/T1/move", json={"target_list_id": "L2", "rank": 7.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "target_list_id": "L2",
        "new_task_id": "NEW1",
        "rank": 7.0,
        "group_id": None,
    }
    # insert_task strictly before delete_task.
    names = google.names()
    assert names.index("insert_task") < names.index("delete_task")
    # Overlay migrated: old gone, new present with rank and group None.
    session.expire_all()
    assert session.get(TaskOverlay, ("L1", "T1")) is None
    new_row = session.get(TaskOverlay, ("L2", "NEW1"))
    assert new_row is not None and new_row.rank == 7.0 and new_row.group_id is None


def test_move_same_list_400(client, google, session):
    resp = client.post("/tasks/L1/T1/move", json={"target_list_id": "L1"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "same_list"
    # Nothing called.
    assert google.calls == []


def test_move_insert_fails_502_no_delete(client, google, session):
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
    }
    google.insert_error = RuntimeError("boom")
    session.add(TaskOverlay(tasklist_id="L1", task_id="T1", rank=9.0, group_id=None))
    session.commit()

    resp = client.post("/tasks/L1/T1/move", json={"target_list_id": "L2", "rank": 7.0})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "google_insert_failed"
    # delete never called; source overlay intact.
    assert "delete_task" not in google.names()
    session.expire_all()
    assert session.get(TaskOverlay, ("L1", "T1")) is not None


def test_move_delete_fails_after_insert_502_no_migration(client, google, session):
    google.tasks[("L1", "T1")] = {
        "id": "T1",
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
    }
    google.insert_result = {
        "id": "NEW1",
        "title": "x",
        "status": "needsAction",
        "due": None,
        "notes": None,
    }
    google.delete_error = RuntimeError("boom")
    session.add(TaskOverlay(tasklist_id="L1", task_id="T1", rank=9.0, group_id=None))
    session.commit()

    resp = client.post("/tasks/L1/T1/move", json={"target_list_id": "L2", "rank": 7.0})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "move_delete_failed"
    # Insert happened, delete attempted, but overlay NOT migrated (source preserved).
    names = google.names()
    assert "insert_task" in names and "delete_task" in names
    session.expire_all()
    assert session.get(TaskOverlay, ("L1", "T1")) is not None
    assert session.get(TaskOverlay, ("L2", "NEW1")) is None


# ── create ─────────────────────────────────────────────────────────────────────


def test_create_task(client, google, session):
    google.insert_result = {"id": "NEW1"}
    resp = client.post("/tasks/L1", json={"title": "new task", "rank": 500.0})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "NEW1"
    assert data["title"] == "new task"
    assert data["status"] == "needsAction"
    assert data["due"] is None
    assert data["rank"] == 500.0 and data["group_id"] is None
    # Exactly one insert, with no due (lands in NO_DATE).
    inserts = [c for c in google.calls if c[0] == "insert_task"]
    assert len(inserts) == 1 and "due" not in inserts[0][2]
    # Overlay row seeded with the client rank.
    row = session.get(TaskOverlay, ("L1", "NEW1"))
    assert row is not None and row.rank == 500.0


def test_create_task_empty_title_400(client, google, session):
    resp = client.post("/tasks/L1", json={"title": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_title"
    assert "insert_task" not in google.names()


# ── content edit (title / notes) ────────────────────────────────────────────────


def test_edit_title_sends_only_title(client, google, session):
    _seed_task(google)
    resp = client.patch("/tasks/L1/T1", json={"title": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "renamed"
    # The patch body carried ONLY title — notes/status omitted, not nulled.
    edits = [c for c in google.calls if c[0] == "update_task_content"]
    assert edits == [("update_task_content", "L1", "T1", {"title": "renamed"})]


def test_edit_notes_only(client, google, session):
    _seed_task(google)
    resp = client.patch("/tasks/L1/T1", json={"notes": "some notes"})
    assert resp.status_code == 200
    edits = [c for c in google.calls if c[0] == "update_task_content"]
    assert edits == [("update_task_content", "L1", "T1", {"notes": "some notes"})]


def test_edit_empty_title_400(client, google, session):
    _seed_task(google)
    resp = client.patch("/tasks/L1/T1", json={"title": ""})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_title"
    assert "update_task_content" not in google.names()


def test_edit_no_fields_400(client, google, session):
    _seed_task(google)
    resp = client.patch("/tasks/L1/T1", json={})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_fields"


def test_edit_missing_task_404(client, google, session):
    resp = client.patch("/tasks/L1/missing", json={"title": "x"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "task_not_found"


# ── complete / uncomplete (status rides the content patch) ──────────────────────


def test_complete_task(client, google, session):
    _seed_task(google)
    resp = client.patch("/tasks/L1/T1", json={"status": "completed"})
    assert resp.status_code == 200
    edits = [c for c in google.calls if c[0] == "update_task_content"]
    assert edits == [("update_task_content", "L1", "T1", {"status": "completed"})]


def test_uncomplete_task(client, google, session):
    _seed_task(google, status="completed")
    resp = client.patch("/tasks/L1/T1", json={"status": "needsAction"})
    assert resp.status_code == 200
    edits = [c for c in google.calls if c[0] == "update_task_content"]
    assert edits == [("update_task_content", "L1", "T1", {"status": "needsAction"})]


# ── delete (user path: immediate Google delete + overlay row removal) ───────────


def test_delete_task_removes_overlay(client, google, session):
    _seed_task(google)
    session.add(TaskOverlay(tasklist_id="L1", task_id="T1", rank=3.0, group_id=None))
    session.commit()
    resp = client.delete("/tasks/L1/T1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    assert google.names().count("delete_task") == 1
    session.expire_all()
    assert session.get(TaskOverlay, ("L1", "T1")) is None


def test_delete_missing_task_404(client, google, session):
    # No task seeded → existence check fails before any Google delete.
    resp = client.delete("/tasks/L1/missing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "task_not_found"
    assert "delete_task" not in google.names()


def test_delete_task_google_failure_502(client, google, session):
    _seed_task(google)
    session.add(TaskOverlay(tasklist_id="L1", task_id="T1", rank=3.0, group_id=None))
    session.commit()
    google.delete_error = RuntimeError("boom")
    resp = client.delete("/tasks/L1/T1")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "google_delete_failed"
    # Overlay row preserved when the Google delete fails.
    session.expire_all()
    assert session.get(TaskOverlay, ("L1", "T1")) is not None


# ── list rename (tasklists resource) ────────────────────────────────────────────


def test_rename_list(client, google, session):
    resp = client.patch("/lists/L1", json={"title": "Renamed List"})
    assert resp.status_code == 200
    assert resp.json() == {"id": "L1", "title": "Renamed List"}
    assert google.calls == [("update_tasklist", "L1", "Renamed List")]


def test_rename_list_empty_400(client, google, session):
    resp = client.patch("/lists/L1", json={"title": "  "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_title"
    assert "update_tasklist" not in google.names()


# ── _get_task maps Google's "bad id" responses to None ──────────────────────────
# Google returns 404 for some unknown task ids and 400 for others; both must map
# to None so callers raise a clean enveloped 404 (regression: a 400 leaked a 500).


@pytest.mark.parametrize("status", [400, 404])
def test_get_task_maps_bad_id_to_none(monkeypatch, status):
    from googleapiclient.errors import HttpError

    import app.google.tasks as t

    class _Resp:
        def __init__(self, s):
            self.status = s
            self.reason = "err"

    class _Exec:
        def execute(self):
            raise HttpError(_Resp(status), b'{"error": "bad id"}')

    class _Tasks:
        def get(self, **_kw):
            return _Exec()

    class _Svc:
        def tasks(self):
            return _Tasks()

    monkeypatch.setattr(t, "_tasks_service", lambda: _Svc())
    assert t._get_task("L1", "bad") is None
