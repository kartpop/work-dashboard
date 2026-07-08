"""Tests for the goal-5 auto-router: route/dispose logic, the create-only guardrail,
route-once idempotency, the review queue, and the pure eval scorer.

Both the classifier (the runtime LLM) and Google are fully mocked — no API key, no
network. The guardrail tests are the gate-critical ones: they prove routing can NEVER
reach a destructive Google writer (statically via AST, and dynamically by recording
every call across every routing path).

Goal 8: `route_entry`/`confirm_review` take the full `User` + live `creds`; every
Google client fn takes `creds` first; scratch/review rows are user-scoped; and a note's
Doc is the user's own — auto-bootstrapped via `settings_svc.ensure_notes_target`
(create_folder → create_doc_in_folder), not an env var. Service functions are async;
sync tests drive them with `run(...)` (asyncio.run) so we need no async-pytest plugin.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

import pytest
from sqlmodel import select

from tests.conftest import DummyCreds

from app.errors import ApiError
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


class Google:
    """Records every Google write so we can assert what routing did (and didn't) touch.

    Every wrapper takes `creds` first (goal 8); it is dropped from the recorded tuple."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.tasks: dict[tuple[str, str], dict] = {}
        self._next_id = 0

    async def get_task_lists(self, creds):
        self.calls.append(("get_task_lists",))
        return [
            {"id": "L1", "title": "My Tasks", "tasks": []},
            {"id": "L2", "title": "Followups", "tasks": []},
        ]

    async def get_task(self, creds, list_id, task_id):
        self.calls.append(("get_task", list_id, task_id))
        return self.tasks.get((list_id, task_id))

    async def insert_task(self, creds, list_id, body):
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

    async def update_due_date(self, creds, list_id, task_id, due):
        self.calls.append(("update_due_date", list_id, task_id, due))

    async def delete_task(self, creds, list_id, task_id):  # must NEVER be routed
        self.calls.append(("delete_task", list_id, task_id))

    async def update_task_content(self, creds, list_id, task_id, **fields):  # never
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


@pytest.fixture
def notes(monkeypatch):
    """Mock the goal-8 Docs/Drive surface + the notes-target bootstrap.

    A note's Doc is the user's own, auto-created on first need: the router calls
    `settings_svc.ensure_notes_target`, which — with unset UserSettings ids — calls
    `create_folder` then `create_doc_in_folder`, then `append_note` runs its ancestry
    gate (`get_parents`) + `insert_note`. We record inserts and make ancestry pass
    (parents of the created doc include the created folder)."""
    from app.writes import service as writes_svc

    writes_svc._ancestry_ok.clear()
    rec = {"insert": [], "folder_id": "FOLDER-boot", "doc_id": "DOC-boot"}

    async def _create_folder(creds, name):
        return rec["folder_id"]

    async def _create_doc_in_folder(creds, title, folder_id):
        return rec["doc_id"]

    async def _get_parents(creds, file_id):
        # The bootstrapped doc lives directly in the bootstrapped folder.
        if file_id == rec["doc_id"]:
            return [rec["folder_id"]]
        return []

    async def _insert_note(creds, doc_id, heading, body, summary=None):
        rec["insert"].append((doc_id, heading, body, summary))

    monkeypatch.setattr("app.google.docs.create_folder", _create_folder)
    monkeypatch.setattr("app.google.docs.create_doc_in_folder", _create_doc_in_folder)
    monkeypatch.setattr("app.google.docs.get_parents", _get_parents)
    monkeypatch.setattr("app.google.docs.insert_note", _insert_note)
    return rec


def _set(holder, destination, confidence, **fields):
    holder["result"] = RouterClassification(
        destination=destination, confidence=confidence, fields=RouterFields(**fields)
    )


def _entry(session, user, text="something"):
    e = ScratchEntry(user_id=user.id, text=text)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


# ── Dispose: each destination ─────────────────────────────────────────────────


def test_high_conf_task_creates_one_task(session, user_a, google, fake_classify):
    _set(fake_classify, "task", 0.95, title="call plumber", due_date="2026-06-20")
    state = run(
        router_svc.route_entry(
            session,
            user_a,
            DummyCreds(),
            _entry(session, user_a, "call plumber friday"),
        )
    )
    assert state == ROUTED_TASK
    assert google.names().count("insert_task") == 1
    assert "update_due_date" in google.names()  # due via reschedule (metadata)
    assert "delete_task" not in google.names()
    assert "update_task_content" not in google.names()


def test_high_conf_note_bootstraps_doc_and_writes_verbatim(
    session, user_a, google, fake_classify, notes
):
    """Goal 8: with no notes Doc yet, the router bootstraps the user's own folder+Doc
    (`ensure_notes_target`), then writes exactly one verbatim Docs insert under an H3
    timestamp — no task write. Replaces the old NOTES_DOC_ID-unset kept-local test."""
    _set(fake_classify, "note", 0.95, note_text="cleaned — but body must be verbatim")
    body = "- strategy idea\n  - sub point\n- another line"
    state = run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, body)
        )
    )
    assert state == KEPT_NOTE
    assert len(notes["insert"]) == 1
    doc_id, heading, written, _summary = notes["insert"][0]
    assert doc_id == notes["doc_id"]  # the app-bootstrapped Doc
    assert written == body  # verbatim — bullets/indentation preserved
    assert heading.endswith("IST")
    assert "insert_task" not in google.names()


def test_note_ancestry_gate_rejects_doc_outside_folder(
    session, user_a, google, fake_classify, notes, monkeypatch
):
    """A doc whose parents don't reach the notes folder is rejected fail-closed — no
    insert, entry left re-routable."""

    async def _bad_parents(creds, file_id):
        return ["SOME_OTHER_FOLDER"]

    monkeypatch.setattr("app.google.docs.get_parents", _bad_parents)
    _set(fake_classify, "note", 0.95, note_text="x")
    entry = _entry(session, user_a, "note outside the folder")
    with pytest.raises(ApiError):
        run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    assert notes["insert"] == []
    session.expire_all()
    assert session.get(ScratchEntry, entry.id).routing_state == UNROUTED


def test_note_docs_failure_leaves_entry_unrouted(
    session, user_a, google, fake_classify, notes, monkeypatch
):
    """A Docs write failure surfaces (never swallowed) and leaves the entry
    re-routable — route-once marks routed only on a successful append."""

    async def _boom(creds, doc_id, heading, body, summary=None):
        raise RuntimeError("docs down")

    monkeypatch.setattr("app.google.docs.insert_note", _boom)
    _set(fake_classify, "note", 0.95, note_text="x")
    entry = _entry(session, user_a, "boom note")
    with pytest.raises(ApiError):
        run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    session.expire_all()
    assert session.get(ScratchEntry, entry.id).routing_state == UNROUTED


def test_event_goes_to_review_no_writes(session, user_a, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="lunch", event_datetime="thu 1pm")
    state = run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "lunch with Tejas")
        )
    )
    assert state == IN_REVIEW
    assert google.calls == []
    rows = session.exec(select(ReviewItem)).all()
    assert len(rows) == 1 and rows[0].status == PENDING


def test_unknown_goes_to_review(session, user_a, google, fake_classify):
    _set(fake_classify, "unknown", 0.1)
    assert (
        run(
            router_svc.route_entry(
                session, user_a, DummyCreds(), _entry(session, user_a, "huh")
            )
        )
        == IN_REVIEW
    )
    assert google.calls == []


def test_low_confidence_task_goes_to_review_not_written(
    session, user_a, google, fake_classify
):
    _set(fake_classify, "task", 0.4, title="maybe ping someone")
    assert (
        run(
            router_svc.route_entry(
                session, user_a, DummyCreds(), _entry(session, user_a, "ping?")
            )
        )
        == IN_REVIEW
    )
    assert "insert_task" not in google.names()


# ── Route-once idempotency ────────────────────────────────────────────────────


def test_route_once_does_not_recreate(session, user_a, google, fake_classify):
    _set(fake_classify, "task", 0.95, title="buy milk")
    entry = _entry(session, user_a, "buy milk")
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    state2 = run(router_svc.route_entry(session, user_a, DummyCreds(), entry))  # no-op
    assert state2 == ROUTED_TASK
    assert google.names().count("insert_task") == 1


def test_route_unrouted_tally_then_noop(session, user_a, google, fake_classify, notes):
    _set(fake_classify, "note", 0.95, note_text="x")
    for _ in range(3):
        _entry(session, user_a, "a note")
    tally = run(router_svc.route_unrouted(session, user_a, DummyCreds()))
    assert tally["kept_note"] == 3
    assert run(router_svc.route_unrouted(session, user_a, DummyCreds())) == {
        "routed_task": 0,
        "kept_note": 0,
        "in_review": 0,
        "failed": 0,
    }


# ── THE GUARDRAIL ─────────────────────────────────────────────────────────────


def test_router_never_calls_delete_or_status(
    session, user_a, google, fake_classify, notes
):
    """Drive every routing destination; assert delete_task and the status/complete
    write are NEVER called — the insert-only blast-radius contract, dynamically."""
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
        run(
            router_svc.route_entry(
                session, user_a, DummyCreds(), _entry(session, user_a, f"{dest} case")
            )
        )

    forbidden = {"delete_task", "update_task_content"}
    assert forbidden.isdisjoint(google.names()), google.names()
    assert google.names().count("insert_task") == 1  # the one high-conf task


def test_router_write_dependency_set_is_insert_only():
    """Statically: every `writes_svc.<fn>(...)` call reachable in the router service
    is in {create_task, reschedule, append_note} (goal 7). No destructive writer —
    no delete_task, status write, update_content, or Docs overwrite — is referenced."""
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
    assert called == {"create_task", "reschedule", "append_note"}, called


def test_docs_module_write_surface_is_insert_only():
    """Statically: the Docs/Drive client never deletes a file or does a
    content-overwriting `files().update` — the only mutations are the insert-only
    `documents().batchUpdate` and the sanctioned `files().create` (bootstrap).
    Drive-access-scoping ADR, layer 5."""
    from app.google import docs as docs_mod

    tree = ast.parse(inspect.getsource(docs_mod))
    called_methods = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "delete" not in called_methods, called_methods
    assert "update" not in called_methods, called_methods  # no files().update overwrite
    assert "batchUpdate" in called_methods  # the insert-only note write
    assert "create" in called_methods  # the sanctioned file-create (bootstrap)


# ── Write-failure leaves the entry re-routable ────────────────────────────────


def test_write_failure_leaves_entry_unrouted(
    session, user_a, monkeypatch, google, fake_classify
):
    _set(fake_classify, "task", 0.95, title="boom")

    async def _boom(creds, list_id, body):
        raise RuntimeError("google down")

    monkeypatch.setattr("app.google.tasks.insert_task", _boom)
    entry = _entry(session, user_a, "boom")
    with pytest.raises(ApiError):
        run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    session.expire_all()
    assert session.get(ScratchEntry, entry.id).routing_state == UNROUTED


# ── Review queue dispositions ─────────────────────────────────────────────────


def test_confirm_task_review_fires_one_create(session, user_a, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="lunch")  # lands in review
    run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "lunch maybe")
        )
    )
    item = session.exec(select(ReviewItem)).first()
    res = run(
        router_svc.confirm_review(
            session,
            user_a,
            DummyCreds(),
            item.id,
            destination="task",
            fields=RouterFields(title="lunch with Tejas", due_date="2026-06-20"),
        )
    )
    assert res["entry_state"] == ROUTED_TASK
    assert google.names().count("insert_task") == 1


def test_dismiss_writes_nothing(session, user_a, google, fake_classify):
    _set(fake_classify, "unknown", 0.1)
    entry = _entry(session, user_a, "huh")
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    item = session.exec(select(ReviewItem)).first()
    res = run(router_svc.dismiss_review(session, user_a, item.id))
    assert res["status"] == "dismissed"
    assert google.calls == []
    session.expire_all()
    assert session.get(ScratchEntry, entry.id).routing_state == RESOLVED


def test_confirm_event_acknowledges_no_write(session, user_a, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="standup")
    run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "standup 10am")
        )
    )
    item = session.exec(select(ReviewItem)).first()
    res = run(router_svc.confirm_review(session, user_a, DummyCreds(), item.id))
    assert res["entry_state"] == RESOLVED
    assert "insert_task" not in google.names()


# ── Endpoints ─────────────────────────────────────────────────────────────────


def test_capture_persists_and_lists(client, google, fake_classify):
    """Capture persists + is listed. It also routes inline (goal 7c) — an event
    proposal lands in review, but the raw entry is stored append-only regardless."""
    _set(fake_classify, "event", 0.95, title="lunch")
    r = client.post("/scratch", json={"text": "  a thought  "})
    assert r.status_code == 201
    body = r.json()
    assert body["text"] == "a thought"
    assert client.get("/scratch").json()["entries"][0]["id"] == body["id"]


def test_capture_routes_inline(client, google, fake_classify):
    """Goal 7c: the POST response carries the routed state — a high-confidence task
    is created in Google without waiting for any scheduler tick."""
    _set(fake_classify, "task", 0.95, title="buy milk")
    r = client.post("/scratch", json={"text": "buy milk"})
    assert r.status_code == 201
    assert r.json()["routing_state"] == ROUTED_TASK
    assert google.names().count("insert_task") == 1


def test_capture_inline_failure_leaves_unrouted(
    client, google, fake_classify, monkeypatch
):
    """A Google failure during inline routing still returns 2xx (capture never
    lost) and leaves the entry UNROUTED for the scheduler backstop to retry."""

    async def _boom(creds, list_id, body):
        raise RuntimeError("google down")

    monkeypatch.setattr("app.google.tasks.insert_task", _boom)
    _set(fake_classify, "task", 0.95, title="boom")
    r = client.post("/scratch", json={"text": "boom"})
    assert r.status_code == 201
    assert r.json()["routing_state"] == UNROUTED


def test_capture_empty_400(client):
    assert client.post("/scratch", json={"text": "   "}).status_code == 400


def test_route_now_endpoint_is_backstop_noop(client, google, fake_classify, notes):
    """Capture routes inline now, so route-now (the backstop) finds nothing to do."""
    _set(fake_classify, "note", 0.95, note_text="x")
    client.post("/scratch", json={"text": "a note"})  # routes inline → kept_note
    r = client.post("/scratch/route-now")
    assert r.status_code == 200
    assert r.json()["tally"] == {
        "routed_task": 0,
        "kept_note": 0,
        "in_review": 0,
        "failed": 0,
    }


def test_review_confirm_endpoint(client, google, fake_classify):
    _set(fake_classify, "event", 0.95, title="lunch")
    client.post("/scratch", json={"text": "lunch with Sam thursday"})  # → review inline
    items = client.get("/review").json()["items"]
    assert len(items) == 1
    r = client.post(
        f"/review/{items[0]['id']}/confirm",
        json={"destination": "task", "fields": {"title": "lunch with Sam"}},
    )
    assert r.status_code == 200 and r.json()["entry_state"] == ROUTED_TASK
    assert google.names().count("insert_task") == 1
    assert client.get("/review").json()["items"] == []  # left the queue


# ── Two-user isolation (goal 8 headline AC) ─────────────────────────────────────


def test_scratch_list_is_per_user(auth, user_a, user_b, session, google, fake_classify):
    """B's GET /scratch returns only B's entries — A's captures are invisible."""
    _set(fake_classify, "unknown", 0.1)  # everything lands in review, no writes
    client_a = auth.as_user(user_a)
    client_a.post("/scratch", json={"text": "a-secret"})
    client_b = auth.as_user(user_b)
    client_b.post("/scratch", json={"text": "b-thought"})

    texts_b = [e["text"] for e in client_b.get("/scratch").json()["entries"]]
    assert texts_b == ["b-thought"]
    texts_a = [
        e["text"] for e in auth.as_user(user_a).get("/scratch").json()["entries"]
    ]
    assert texts_a == ["a-secret"]


def test_cannot_confirm_or_dismiss_other_users_review(
    auth, user_a, user_b, session, google, fake_classify
):
    """B cannot confirm or dismiss A's review item — 404 (no cross-tenant read by id)."""
    _set(fake_classify, "event", 0.95, title="lunch")  # → review inline for A
    client_a = auth.as_user(user_a)
    client_a.post("/scratch", json={"text": "a's lunch"})
    item_id = client_a.get("/review").json()["items"][0]["id"]

    client_b = auth.as_user(user_b)
    assert (
        client_b.post(
            f"/review/{item_id}/confirm", json={"destination": "task"}
        ).status_code
        == 404
    )
    assert client_b.post(f"/review/{item_id}/dismiss").status_code == 404
    # A's item is still pending + no Google write leaked.
    assert len(auth.as_user(user_a).get("/review").json()["items"]) == 1
    assert "insert_task" not in google.names()


def test_review_queries_are_user_scoped(session, user_a, user_b, google, fake_classify):
    """Service-level: a review item created for A is invisible to B (404 on lookup)."""
    _set(fake_classify, "unknown", 0.1)
    run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "a thought")
        )
    )
    item = session.exec(select(ReviewItem)).first()
    # B cannot dismiss A's item.
    with pytest.raises(ApiError):
        run(router_svc.dismiss_review(session, user_b, item.id))
    # A can.
    res = run(router_svc.dismiss_review(session, user_a, item.id))
    assert res["status"] == "dismissed"


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


# ── Notes writer: heading + insert-at-top (goal 7, no API) ─────────────────────


def test_format_note_heading_locked_format():
    from datetime import datetime

    from app.writes.service import format_note_heading

    assert (
        format_note_heading(datetime(2026, 7, 6, 20, 41)) == "6-July-2026, 8:41 PM IST"
    )
    assert (
        format_note_heading(datetime(2026, 1, 9, 0, 5))
        == "9-January-2026, 12:05 AM IST"
    )
    assert (
        format_note_heading(datetime(2026, 12, 25, 12, 0))
        == "25-December-2026, 12:00 PM IST"
    )


def test_insert_note_puts_h3_timestamp_at_top(monkeypatch):
    """The batchUpdate inserts at index 1 (top of body), heading first with an H3
    paragraph style — newest note lands above everything else. `insert_note` now
    takes `creds` first (pass a dummy)."""
    from app.google import docs as docs_mod

    captured = {}

    class FakeDocs:
        def documents(self):
            return self

        def batchUpdate(self, documentId, body):
            captured["documentId"] = documentId
            captured["requests"] = body["requests"]
            return self

        def execute(self):
            return {}

    monkeypatch.setattr(docs_mod, "_docs_service", lambda _creds: FakeDocs())
    run(
        docs_mod.insert_note(
            DummyCreds(), "DOC", "6-July-2026, 8:41 PM IST", "- a\n- b"
        )
    )

    reqs = captured["requests"]
    assert captured["documentId"] == "DOC"
    assert reqs[0]["insertText"]["location"]["index"] == 1
    assert reqs[0]["insertText"]["text"].startswith("6-July-2026, 8:41 PM IST\n")
    # verbatim body, then a trailing empty paragraph (the delimiter, goal 7a)
    assert reqs[0]["insertText"]["text"].endswith("- a\n- b\n\n")
    assert reqs[1]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == (
        "HEADING_3"
    )
    assert reqs[1]["updateParagraphStyle"]["range"]["startIndex"] == 1
    # The last request styles the empty delimiter paragraph with a light-gray
    # borderBottom + spacing — insert-only, no HR request exists.
    delim = reqs[-1]["updateParagraphStyle"]
    assert "borderBottom" in delim["paragraphStyle"]
    assert "borderBottom" in delim["fields"]


def _capture_batchupdate(monkeypatch):
    """Patch the Docs service to capture the batchUpdate requests; returns the box."""
    from app.google import docs as docs_mod

    captured: dict = {}

    class FakeDocs:
        def documents(self):
            return self

        def batchUpdate(self, documentId, body):
            captured["documentId"] = documentId
            captured["requests"] = body["requests"]
            return self

        def execute(self):
            return {}

    monkeypatch.setattr(docs_mod, "_docs_service", lambda _creds: FakeDocs())
    return captured


def test_insert_note_with_summary_bold_one_liner(monkeypatch):
    """Goal 7c entry shape: H3 timestamp → bold one-liner → verbatim body →
    delimiter. The one-liner is a bold (updateTextStyle) NORMAL_TEXT paragraph."""
    from app.google import docs as docs_mod

    captured = _capture_batchupdate(monkeypatch)
    run(
        docs_mod.insert_note(
            DummyCreds(), "DOC", "6-July-2026, 8:41 PM IST", "- a\n- b", "milk + eggs"
        )
    )
    reqs = captured["requests"]
    text = reqs[0]["insertText"]["text"]
    # timestamp, then the one-liner on its own line, then the verbatim body.
    assert text.startswith("6-July-2026, 8:41 PM IST\nmilk + eggs\n")
    assert text.endswith("- a\n- b\n\n")
    # exactly one bold text-style request — the one-liner.
    bold = [
        r
        for r in reqs
        if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"].get("bold")
    ]
    assert len(bold) == 1
    # the bold range starts right after the heading paragraph.
    heading_end = 1 + len("6-July-2026, 8:41 PM IST") + 1
    assert bold[0]["updateTextStyle"]["range"]["startIndex"] == heading_end
    # delimiter still present.
    assert "borderBottom" in reqs[-1]["updateParagraphStyle"]["paragraphStyle"]


def test_insert_note_empty_summary_degrades_to_g7_shape(monkeypatch):
    """A missing/blank summary → no bold line, the goal-7 heading→body→delimiter
    shape, never blocking the write."""
    from app.google import docs as docs_mod

    captured = _capture_batchupdate(monkeypatch)
    run(
        docs_mod.insert_note(
            DummyCreds(), "DOC", "6-July-2026, 8:41 PM IST", "- a", "   "
        )
    )
    reqs = captured["requests"]
    assert reqs[0]["insertText"]["text"] == "6-July-2026, 8:41 PM IST\n- a\n\n"
    assert not any("updateTextStyle" in r for r in reqs)


def test_auto_route_note_passes_summary_through(
    session, user_a, google, fake_classify, notes
):
    """A high-confidence note carries the classifier's summary into the Doc write."""
    _set(fake_classify, "note", 0.95, note_text="x", summary="entropy video")
    state = run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "raw verbatim text")
        )
    )
    assert state == KEPT_NOTE
    doc_id, heading, body, summary = notes["insert"][0]
    assert body == "raw verbatim text"  # raw stays verbatim
    assert summary == "entropy video"  # the LLM one-liner rides alongside


def test_confirm_as_note_review_writes_to_doc(
    session, user_a, google, fake_classify, notes
):
    """Confirm-as-note in review fires exactly one Docs append (the panel copy now
    promises this)."""
    _set(fake_classify, "unknown", 0.1)  # lands in review
    run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "- a stray thought")
        )
    )
    item = session.exec(select(ReviewItem)).first()
    res = run(
        router_svc.confirm_review(
            session, user_a, DummyCreds(), item.id, destination="note"
        )
    )
    assert res["entry_state"] == KEPT_NOTE
    assert len(notes["insert"]) == 1
    assert notes["insert"][0][2] == "- a stray thought"  # verbatim entry text


def test_confirm_as_note_uses_edited_body_and_one_liner(
    session, user_a, google, fake_classify, notes
):
    """Goal 7c: review edits win — a user-edited note body + one-liner are what
    land in the Doc, not the raw captured text."""
    _set(fake_classify, "unknown", 0.1)  # lands in review
    run(
        router_svc.route_entry(
            session, user_a, DummyCreds(), _entry(session, user_a, "raw capture text")
        )
    )
    item = session.exec(select(ReviewItem)).first()
    res = run(
        router_svc.confirm_review(
            session,
            user_a,
            DummyCreds(),
            item.id,
            destination="note",
            fields=RouterFields(note_text="cleaned body", summary="a headline"),
        )
    )
    assert res["entry_state"] == KEPT_NOTE
    _doc, _heading, body, summary = notes["insert"][0]
    assert body == "cleaned body"  # the edit, not the raw capture
    assert summary == "a headline"


def test_review_note_endpoint_overrides(client, google, fake_classify, notes):
    """The /confirm endpoint threads note_text + summary overrides through to the
    Doc write (task | note only in the UI; the endpoint honors both)."""
    _set(fake_classify, "event", 0.95, title="lunch")  # → review inline
    client.post("/scratch", json={"text": "some thought"})
    item = client.get("/review").json()["items"][0]
    r = client.post(
        f"/review/{item['id']}/confirm",
        json={
            "destination": "note",
            "fields": {"note_text": "edited note", "summary": "one-liner"},
        },
    )
    assert r.status_code == 200 and r.json()["entry_state"] == KEPT_NOTE
    assert notes["insert"][0][2] == "edited note"
    assert notes["insert"][0][3] == "one-liner"
