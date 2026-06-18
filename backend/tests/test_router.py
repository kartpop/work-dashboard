"""Tests for the goal-5 auto-router: route/dispose logic, the create-only guardrail,
route-once idempotency, the review queue, and the pure eval scorer.

Both the classifier (the runtime LLM) and Google are fully mocked — no API key, no
network. The guardrail tests are the gate-critical ones: they prove routing can NEVER
reach a destructive Google writer (statically via AST, and dynamically by recording
every call across every routing path).

Service functions are async; sync tests drive them with `run(...)` (asyncio.run) so we
need no async-pytest plugin.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.errors import ApiError
from app.main import app
from app.router import service as router_svc
from app.router.models import (
    IN_REVIEW,
    KEPT_NOTE,
    PENDING,
    RESOLVED,
    ROUTED_TASK,
    UNROUTED,
    ReviewItem,
    ScratchEntry,
)
from app.router.schema import RouterClassification, RouterFields


def run(coro):
    return asyncio.run(coro)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


class Google:
    """Records every Google write so we can assert what routing did (and didn't) touch."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.tasks: dict[tuple[str, str], dict] = {}
        self._next_id = 0

    async def get_task_lists(self):
        self.calls.append(("get_task_lists",))
        return [
            {"id": "L1", "title": "My Tasks", "tasks": []},
            {"id": "L2", "title": "Followups", "tasks": []},
        ]

    async def get_task(self, list_id, task_id):
        self.calls.append(("get_task", list_id, task_id))
        return self.tasks.get((list_id, task_id))

    async def insert_task(self, list_id, body):
        self.calls.append(("insert_task", list_id, body))
        self._next_id += 1
        tid = f"new-{self._next_id}"
        task = {
            "id": tid,
            "title": body.get("title", ""),
            "status": body.get("status", "needsAction"),
            "due": body.get("due"),
            "notes": body.get("notes"),
            "parent": None,
        }
        self.tasks[(list_id, tid)] = task
        return task

    async def update_due_date(self, list_id, task_id, due):
        self.calls.append(("update_due_date", list_id, task_id, due))

    async def delete_task(self, list_id, task_id):  # must NEVER be called by routing
        self.calls.append(("delete_task", list_id, task_id))

    async def update_task_content(self, list_id, task_id, **fields):  # never by routing
        self.calls.append(("update_task_content", list_id, task_id, fields))
        return self.tasks.get((list_id, task_id), {"id": task_id})

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def google(monkeypatch):
    rec = Google()
    monkeypatch.setattr("app.google.tasks.get_task_lists", rec.get_task_lists)
    monkeypatch.setattr("app.google.tasks.get_task", rec.get_task)
    monkeypatch.setattr("app.google.tasks.insert_task", rec.insert_task)
    monkeypatch.setattr("app.google.tasks.update_due_date", rec.update_due_date)
    monkeypatch.setattr("app.google.tasks.delete_task", rec.delete_task)
    monkeypatch.setattr("app.google.tasks.update_task_content", rec.update_task_content)
    return rec


@pytest.fixture
def fake_classify(monkeypatch):
    """Patch the runtime LLM with a canned classification (set via `_set`)."""

    holder = {"result": RouterClassification(destination="unknown", confidence=0.0)}

    async def _classify(text: str):
        return holder["result"]

    monkeypatch.setattr("app.router.service.classify", _classify)
    return holder


def _set(holder, destination, confidence, **fields):
    holder["result"] = RouterClassification(
        destination=destination, confidence=confidence, fields=RouterFields(**fields)
    )


def _entry(session, text="something"):
    e = ScratchEntry(text=text)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


# ── Dispose: each destination ─────────────────────────────────────────────────


def test_high_conf_task_creates_one_task(session, google, fake_classify):
    _set(fake_classify, "task", 0.95, title="call plumber", due_date="2026-06-20")
    state = run(router_svc.route_entry(session, _entry(session, "call plumber friday")))
    assert state == ROUTED_TASK
    assert google.names().count("insert_task") == 1
    assert "update_due_date" in google.names()  # due via reschedule (metadata)
    assert "delete_task" not in google.names()
    assert "update_task_content" not in google.names()


def test_high_conf_note_kept_local_no_writes(session, google, fake_classify):
    _set(fake_classify, "note", 0.9, note_text="vsauce entropy video")
    state = run(router_svc.route_entry(session, _entry(session, "remember vsauce")))
    assert state == KEPT_NOTE
    assert google.calls == []  # no Google write of any kind


def test_event_goes_to_review_no_writes(session, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="lunch", event_datetime="thu 1pm")
    state = run(router_svc.route_entry(session, _entry(session, "lunch with Tejas")))
    assert state == IN_REVIEW
    assert google.calls == []
    rows = session.exec(select(ReviewItem)).all()
    assert len(rows) == 1 and rows[0].status == PENDING


def test_unknown_goes_to_review(session, google, fake_classify):
    _set(fake_classify, "unknown", 0.1)
    assert run(router_svc.route_entry(session, _entry(session, "huh"))) == IN_REVIEW
    assert google.calls == []


def test_low_confidence_task_goes_to_review_not_written(session, google, fake_classify):
    _set(fake_classify, "task", 0.4, title="maybe ping someone")
    assert run(router_svc.route_entry(session, _entry(session, "ping?"))) == IN_REVIEW
    assert "insert_task" not in google.names()


# ── Route-once idempotency ────────────────────────────────────────────────────


def test_route_once_does_not_recreate(session, google, fake_classify):
    _set(fake_classify, "task", 0.95, title="buy milk")
    entry = _entry(session, "buy milk")
    run(router_svc.route_entry(session, entry))
    state2 = run(router_svc.route_entry(session, entry))  # already routed → no-op
    assert state2 == ROUTED_TASK
    assert google.names().count("insert_task") == 1


def test_route_unrouted_tally_then_noop(session, google, fake_classify):
    _set(fake_classify, "note", 0.95, note_text="x")
    for _ in range(3):
        _entry(session, "a note")
    tally = run(router_svc.route_unrouted(session))
    assert tally["kept_note"] == 3
    assert run(router_svc.route_unrouted(session)) == {
        "routed_task": 0,
        "kept_note": 0,
        "in_review": 0,
        "failed": 0,
    }


# ── THE GUARDRAIL ─────────────────────────────────────────────────────────────


def test_router_never_calls_delete_or_status(session, google, fake_classify):
    """Drive every routing destination; assert delete_task and the status/complete
    write are NEVER called — the create-only blast-radius contract, dynamically."""
    scenarios = [
        ("task", 0.95, {"title": "t", "due_date": "2026-06-20"}),
        ("task", 0.3, {"title": "t"}),
        ("note", 0.95, {"note_text": "n"}),
        ("note", 0.2, {"note_text": "n"}),
        ("event", 0.95, {"title": "e"}),
        ("unknown", 0.05, {}),
    ]
    for dest, conf, fields in scenarios:
        _set(fake_classify, dest, conf, **fields)
        run(router_svc.route_entry(session, _entry(session, f"{dest} case")))

    forbidden = {"delete_task", "update_task_content"}
    assert forbidden.isdisjoint(google.names()), google.names()
    assert google.names().count("insert_task") == 1  # the one high-conf task


def test_router_write_dependency_set_is_create_only():
    """Statically: every `writes_svc.<fn>(...)` call reachable in the router service
    is in {create_task, reschedule}. No destructive writer is even referenced."""
    tree = ast.parse(inspect.getsource(router_svc))
    called = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "writes_svc"
        ):
            called.add(node.func.attr)
    assert called == {"create_task", "reschedule"}, called


# ── Write-failure leaves the entry re-routable ────────────────────────────────


def test_write_failure_leaves_entry_unrouted(
    session, monkeypatch, google, fake_classify
):
    _set(fake_classify, "task", 0.95, title="boom")

    async def _boom(list_id, body):
        raise RuntimeError("google down")

    monkeypatch.setattr("app.google.tasks.insert_task", _boom)
    entry = _entry(session, "boom")
    with pytest.raises(ApiError):
        run(router_svc.route_entry(session, entry))
    session.expire_all()
    assert session.get(ScratchEntry, entry.id).routing_state == UNROUTED


# ── Review queue dispositions ─────────────────────────────────────────────────


def test_confirm_task_review_fires_one_create(session, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="lunch")  # lands in review
    run(router_svc.route_entry(session, _entry(session, "lunch maybe")))
    item = session.exec(select(ReviewItem)).first()
    res = run(
        router_svc.confirm_review(
            session,
            item.id,
            destination="task",
            fields=RouterFields(title="lunch with Tejas", due_date="2026-06-20"),
        )
    )
    assert res["entry_state"] == ROUTED_TASK
    assert google.names().count("insert_task") == 1


def test_dismiss_writes_nothing(session, google, fake_classify):
    _set(fake_classify, "unknown", 0.1)
    entry = _entry(session, "huh")
    run(router_svc.route_entry(session, entry))
    item = session.exec(select(ReviewItem)).first()
    res = run(router_svc.dismiss_review(session, item.id))
    assert res["status"] == "dismissed"
    assert google.calls == []
    session.expire_all()
    assert session.get(ScratchEntry, entry.id).routing_state == RESOLVED


def test_confirm_event_acknowledges_no_write(session, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="standup")
    run(router_svc.route_entry(session, _entry(session, "standup 10am")))
    item = session.exec(select(ReviewItem)).first()
    res = run(router_svc.confirm_review(session, item.id))  # confirm as-is (event)
    assert res["entry_state"] == RESOLVED
    assert "insert_task" not in google.names()


# ── Endpoints ─────────────────────────────────────────────────────────────────


def test_capture_appends_unrouted(client):
    r = client.post("/scratch", json={"text": "  a thought  "})
    assert r.status_code == 201
    body = r.json()
    assert body["text"] == "a thought" and body["routing_state"] == UNROUTED
    assert client.get("/scratch").json()["entries"][0]["id"] == body["id"]


def test_capture_empty_400(client):
    assert client.post("/scratch", json={"text": "   "}).status_code == 400


def test_route_now_endpoint(client, google, fake_classify):
    _set(fake_classify, "note", 0.95, note_text="x")
    client.post("/scratch", json={"text": "a note"})
    r = client.post("/scratch/route-now")
    assert r.status_code == 200 and r.json()["tally"]["kept_note"] == 1


def test_review_confirm_endpoint(client, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="lunch")
    client.post("/scratch", json={"text": "lunch with Sam thursday"})
    client.post("/scratch/route-now")
    items = client.get("/review").json()["items"]
    assert len(items) == 1
    r = client.post(
        f"/review/{items[0]['id']}/confirm",
        json={"destination": "task", "fields": {"title": "lunch with Sam"}},
    )
    assert r.status_code == 200 and r.json()["entry_state"] == ROUTED_TASK
    assert google.names().count("insert_task") == 1
    assert client.get("/review").json()["items"] == []  # left the queue


# ── Pure eval scorer (no API) ─────────────────────────────────────────────────


def test_eval_score_perfect_passes():
    from app.router.evals.runner import load_cases, score

    results = []
    for c in load_cases():
        amb = bool(c.get("ambiguous"))
        results.append(
            {
                "text": c["text"],
                "expected": c["destination"],
                "ambiguous": amb,
                "predicted": c["destination"] if not amb else "unknown",
                "confidence": 0.4 if amb else 0.95,
                "fields": {
                    "title": c["text"],
                    "due_date": "2026-06-20" if c.get("expects_due") else None,
                    "list_hint": "followups" if c.get("list_hint_contains") else None,
                },
                "case": c,
            }
        )
    card = score(results)
    assert card["clear_accuracy"] == 1.0
    assert card["task_false_positives"] == 0
    assert card["passed"] is True


def test_eval_score_catches_task_false_positive():
    from app.router.evals.runner import score

    results = [
        {
            "text": "remember x",
            "expected": "note",
            "ambiguous": False,
            "predicted": "task",  # a wrong auto-write
            "confidence": 0.95,
            "fields": {},
            "case": {"text": "remember x", "destination": "note"},
        }
    ]
    card = score(results)
    assert card["task_false_positives"] == 1
    assert card["passed"] is False
