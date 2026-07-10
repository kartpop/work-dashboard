"""Goal 9: notes-hierarchy materialization, routing, and self-heal.

A `FakeDrive` stands in for the whole Docs/Drive client (`app.google.docs.*`) with
an in-memory file store, so we can assert exactly which folders/Docs were created,
renamed, or (never) deleted — and drive the router's path→id disposal + the 404
self-heal — with no network.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlmodel import select

from app.errors import ApiError
from app.router import service as router_svc
from app.router.models import KEPT_NOTE, ReviewItem, ScratchEntry
from app.router.schema import RouterClassification, RouterFields
from app.settings import service as settings_svc
from tests.conftest import DummyCreds


def run(coro):
    return asyncio.run(coro)


# ── FakeDrive: an in-memory Docs/Drive client ─────────────────────────────────


class FakeDrive:
    def __init__(self):
        self.files: dict[str, dict] = {}
        self.n = 0
        self.calls: list[tuple] = []
        self.insert: list[tuple] = []
        self.accessible = lambda fid: True
        self.fail_create_name: str | None = None

    def _new(self, kind: str, name: str, parent: str | None) -> str:
        self.n += 1
        fid = f"{kind}-{self.n}"
        self.files[fid] = {
            "name": name,
            "parents": [parent] if parent else [],
            "kind": kind,
        }
        return fid

    async def create_folder(self, creds, name, parent_id=None):
        self.calls.append(("create_folder", name, parent_id))
        if self.fail_create_name == name:
            raise RuntimeError("drive down")
        return self._new("folder", name, parent_id)

    async def create_doc_in_folder(self, creds, title, folder_id):
        self.calls.append(("create_doc", title, folder_id))
        if self.fail_create_name == title:
            raise RuntimeError("drive down")
        return self._new("doc", title, folder_id)

    async def rename_file(self, creds, file_id, name):
        self.calls.append(("rename", file_id, name))
        self.files[file_id]["name"] = name

    async def file_accessible(self, creds, file_id):
        return self.accessible(file_id)

    async def get_parents(self, creds, file_id):
        return list(self.files.get(file_id, {}).get("parents", []))

    async def insert_note(
        self, creds, doc_id, heading, body, summary=None, keywords=None
    ):
        self.insert.append((doc_id, heading, body, summary, keywords))

    def creates_of(self, kind: str) -> list[tuple]:
        """Hierarchy creates only — excludes the bootstrap root folder + default Doc."""
        pref = "create_folder" if kind == "folder" else "create_doc"
        boot = {"Dashboard Notes", "Dashboard — Notes"}
        return [c for c in self.calls if c[0] == pref and c[1] not in boot]


@pytest.fixture
def drive(monkeypatch):
    from app.writes import service as writes_svc

    settings_svc._verified_targets.clear()
    settings_svc._verified_files.clear()
    writes_svc._ancestry_ok.clear()
    fake = FakeDrive()
    for name in (
        "create_folder",
        "create_doc_in_folder",
        "rename_file",
        "file_accessible",
        "get_parents",
        "insert_note",
    ):
        monkeypatch.setattr(f"app.google.docs.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def fake_classify(monkeypatch):
    holder = {"result": RouterClassification(destination="unknown", confidence=0.0)}

    async def _classify(text, doc_paths=None):
        holder["doc_paths"] = doc_paths
        return holder["result"]

    monkeypatch.setattr("app.router.service.classify", _classify)
    return holder


def _doc(nid, name):
    return {"node_id": nid, "name": name, "kind": "doc", "children": []}


def _folder(nid, name, children):
    return {"node_id": nid, "name": name, "kind": "folder", "children": children}


def _entry(session, user, text):
    e = ScratchEntry(user_id=user.id, text=text)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


# ── Materialization via the endpoint ──────────────────────────────────────────


def _example_nodes():
    return [
        _folder(
            "c",
            "conversations",
            [
                _folder("j", "john", [_doc("g", "growth"), _doc("p", "progression")]),
                _doc("ja", "jane"),
            ],
        ),
        _doc("i", "ideas"),
    ]


def test_put_builds_nested_tree_and_second_put_is_noop(client, drive):
    r = client.put("/settings/notes-index", json={"nodes": _example_nodes()})
    assert r.status_code == 200
    # Every node materialized with a drive id + link.
    body = r.json()["nodes"]
    conv = body[0]
    assert conv["kind"] == "folder" and conv["drive_id"]
    assert conv["drive_url"].startswith("https://drive.google.com/drive/folders/")
    growth = conv["children"][0]["children"][0]
    assert growth["name"] == "growth" and growth["kind"] == "doc"
    assert growth["drive_url"].startswith("https://docs.google.com/document/")

    # 3 folders (conversations, john) + wait: conversations, john = 2 folders;
    # docs: growth, progression, jane, ideas = 4.
    assert len(drive.creates_of("folder")) == 2
    assert len(drive.creates_of("doc")) == 4

    # A second identical PUT creates nothing new (idempotent by node_id).
    before = len(drive.calls)
    r2 = client.put("/settings/notes-index", json={"nodes": _example_nodes()})
    assert r2.status_code == 200
    assert drive.calls[before:] == []


def test_get_returns_persisted_tree(client, drive):
    client.put("/settings/notes-index", json={"nodes": [_doc("i", "ideas")]})
    got = client.get("/settings/notes-index").json()["nodes"]
    assert [n["name"] for n in got] == ["ideas"]
    assert got[0]["drive_id"]


def test_rename_updates_drive_name_only(client, drive):
    client.put("/settings/notes-index", json={"nodes": [_doc("i", "ideas")]})
    doc_id = client.get("/settings/notes-index").json()["nodes"][0]["drive_id"]

    # Same node_id, new name → a metadata rename, no new create.
    r = client.put("/settings/notes-index", json={"nodes": [_doc("i", "brain-dump")]})
    assert r.status_code == 200
    assert ("rename", doc_id, "brain-dump") in drive.calls
    assert drive.creates_of("doc") == [
        ("create_doc", "ideas", drive.files[doc_id]["parents"][0])
    ]
    assert drive.files[doc_id]["name"] == "brain-dump"


def test_delete_is_orphan_only(client, drive):
    client.put(
        "/settings/notes-index", json={"nodes": [_doc("a", "keep"), _doc("b", "drop")]}
    )
    drop_id = client.get("/settings/notes-index").json()["nodes"][1]["drive_id"]

    r = client.put("/settings/notes-index", json={"nodes": [_doc("a", "keep")]})
    assert r.status_code == 200
    names = [n["name"] for n in r.json()["nodes"]]
    assert names == ["keep"]
    # The Drive file is NEVER deleted/trashed — it just left the index.
    assert not any(c[0] == "delete" for c in drive.calls)
    assert drop_id in drive.files  # still in Drive, untouched


def test_doc_to_folder_conversion_orphans_and_creates(client, drive):
    client.put("/settings/notes-index", json={"nodes": [_doc("n", "topic")]})
    old_doc_id = client.get("/settings/notes-index").json()["nodes"][0]["drive_id"]

    # Same node_id, kind flips doc→folder with a child → orphan old doc, create folder.
    r = client.put(
        "/settings/notes-index",
        json={"nodes": [_folder("n", "topic", [_doc("child", "sub")])]},
    )
    assert r.status_code == 200
    new = r.json()["nodes"][0]
    assert new["kind"] == "folder" and new["drive_id"] != old_doc_id
    assert old_doc_id in drive.files  # old doc orphaned, not deleted
    assert not any(c[0] == "delete" for c in drive.calls)


def test_partial_failure_persists_progress_and_retry_idempotent(client, drive):
    # Fail creating the 2nd top-level doc; the first must persist, retry fills the gap.
    drive.fail_create_name = "second"
    r = client.put(
        "/settings/notes-index",
        json={"nodes": [_doc("a", "first"), _doc("b", "second")]},
    )
    assert r.status_code == 502
    # First doc persisted despite the failure.
    persisted = client.get("/settings/notes-index").json()["nodes"]
    assert persisted[0]["name"] == "first" and persisted[0]["drive_id"]
    first_id = persisted[0]["drive_id"]

    # Retry succeeds and does NOT recreate the first doc (idempotent by node_id).
    drive.fail_create_name = None
    doc_creates_before = len(drive.creates_of("doc"))
    r2 = client.put(
        "/settings/notes-index",
        json={"nodes": [_doc("a", "first"), _doc("b", "second")]},
    )
    assert r2.status_code == 200
    out = r2.json()["nodes"]
    assert out[0]["drive_id"] == first_id  # reused, not recreated
    # Only the missing "second" doc was created on retry.
    assert len(drive.creates_of("doc")) == doc_creates_before + 1


def test_validation_rejects_dup_siblings_422(client, drive):
    r = client.put(
        "/settings/notes-index",
        json={"nodes": [_doc("a", "notes"), _doc("b", "Notes")]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_notes_index"


def test_two_user_isolation(auth, user_a, user_b, drive):
    ca = auth.as_user(user_a)
    ca.put("/settings/notes-index", json={"nodes": [_doc("a", "a-topic")]})
    cb = auth.as_user(user_b)
    cb.put("/settings/notes-index", json={"nodes": [_doc("b", "b-topic")]})

    assert [n["name"] for n in cb.get("/settings/notes-index").json()["nodes"]] == [
        "b-topic"
    ]
    assert [
        n["name"]
        for n in auth.as_user(user_a).get("/settings/notes-index").json()["nodes"]
    ] == ["a-topic"]


# ── Routing to a hierarchy Doc ────────────────────────────────────────────────


def _materialize(session, user, nodes):
    return run(settings_svc.set_notes_index(session, DummyCreds(), user.id, nodes))


def test_note_routes_to_hierarchy_doc_prefix_stripped(
    session, user_a, drive, fake_classify
):
    forest = _materialize(session, user_a, _example_nodes())
    growth_id = forest[0]["children"][0]["children"][0]["drive_id"]

    fake_classify["result"] = RouterClassification(
        destination="note",
        confidence=0.95,
        fields=RouterFields(
            note_text="discussed promotion timeline",
            target_doc_path="conversations/john/growth",
            summary="promo",
        ),
    )
    entry = _entry(session, user_a, "john growth — discussed promotion timeline")
    state = run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    assert state == KEPT_NOTE
    # The classifier saw the hierarchy paths.
    assert "conversations/john/growth" in fake_classify["doc_paths"]
    # Landed in the john/growth Doc, body = stripped note_text.
    doc_id, _heading, body, _summary, _kw = drive.insert[-1]
    assert doc_id == growth_id
    assert body == "discussed promotion timeline"
    session.refresh(entry)
    assert entry.routed_doc_path == "conversations/john/growth"


def test_note_unknown_path_falls_back_to_default(session, user_a, drive, fake_classify):
    _materialize(session, user_a, [_doc("i", "ideas")])
    default_doc_id, _f = run(
        settings_svc.ensure_notes_target(session, DummyCreds(), user_a.id)
    )
    fake_classify["result"] = RouterClassification(
        destination="note",
        confidence=0.95,
        fields=RouterFields(
            note_text="a floating thought that fits nowhere",
            target_doc_path="conversations/ghost",
        ),
    )
    entry = _entry(session, user_a, "a floating thought that fits nowhere")
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    assert drive.insert[-1][0] == default_doc_id
    session.refresh(entry)
    assert entry.routed_doc_path is None


def test_truncation_guard_falls_back_to_raw(session, user_a, drive, fake_classify):
    _materialize(session, user_a, [_doc("i", "ideas")])
    raw = "a long verbatim capture that must not be lost when extraction mangles it"
    fake_classify["result"] = RouterClassification(
        destination="note",
        confidence=0.95,
        fields=RouterFields(note_text="x"),  # far under 50% of raw length
    )
    entry = _entry(session, user_a, raw)
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    assert drive.insert[-1][2] == raw  # raw wins, no silent word loss


# ── Self-heal of a 404'd hierarchy Doc ────────────────────────────────────────


def test_hierarchy_doc_404_recreated_at_same_path(
    session, user_a, drive, fake_classify
):
    forest = _materialize(session, user_a, [_folder("f", "topic", [_doc("d", "sub")])])
    stale_id = forest[0]["children"][0]["drive_id"]

    # The Doc 404s (client-id change / user-deleted); the folder is still ours.
    settings_svc._verified_files.clear()
    drive.accessible = lambda fid: fid != stale_id

    fake_classify["result"] = RouterClassification(
        destination="note",
        confidence=0.95,
        fields=RouterFields(note_text="note body here", target_doc_path="topic/sub"),
    )
    entry = _entry(session, user_a, "note body here")
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))

    # A fresh Doc was created at the same path and written to; index updated.
    new_id = drive.insert[-1][0]
    assert new_id != stale_id
    got = settings_svc.get_notes_index(session, user_a.id)
    assert got[0]["children"][0]["drive_id"] == new_id
    session.refresh(entry)
    assert entry.routed_doc_path == "topic/sub"


# ── Confirm-as-note re-validates the destination path ─────────────────────────


def test_confirm_as_note_stale_path_422(session, user_a, drive, fake_classify):
    _materialize(session, user_a, [_doc("i", "ideas")])
    fake_classify["result"] = RouterClassification(
        destination="unknown", confidence=0.1, fields=RouterFields()
    )
    entry = _entry(session, user_a, "a thought")
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    item = session.exec(select(ReviewItem)).first()

    with pytest.raises(ApiError) as exc:
        run(
            router_svc.confirm_review(
                session,
                user_a,
                DummyCreds(),
                item.id,
                destination="note",
                fields=RouterFields(
                    note_text="body", target_doc_path="conversations/gone"
                ),
            )
        )
    assert exc.value.detail["code"] == "unknown_doc_path"


def test_confirm_as_note_valid_path_writes_to_that_doc(
    session, user_a, drive, fake_classify
):
    forest = _materialize(session, user_a, [_doc("i", "ideas")])
    ideas_id = forest[0]["drive_id"]
    fake_classify["result"] = RouterClassification(
        destination="unknown", confidence=0.1, fields=RouterFields()
    )
    entry = _entry(session, user_a, "a thought")
    run(router_svc.route_entry(session, user_a, DummyCreds(), entry))
    item = session.exec(select(ReviewItem)).first()
    res = run(
        router_svc.confirm_review(
            session,
            user_a,
            DummyCreds(),
            item.id,
            destination="note",
            fields=RouterFields(note_text="filed here", target_doc_path="ideas"),
        )
    )
    assert res["entry_state"] == KEPT_NOTE
    assert drive.insert[-1][0] == ideas_id
    session.refresh(entry)
    assert entry.routed_doc_path == "ideas"
