"""Pure unit tests for the notes-index tree logic (goal 9).

No Google, no DB — `app.settings.notes_index` is a pure module: parse, validate,
render leaf paths, and resolve a path → node. The Drive materialization that drives
it lives in `test_settings.py`.
"""

from __future__ import annotations

import pytest

from app.errors import ApiError
from app.settings import notes_index as ni


def _doc(nid, name):
    return {"node_id": nid, "name": name, "kind": "doc", "children": []}


def _folder(nid, name, children):
    return {"node_id": nid, "name": name, "kind": "folder", "children": children}


def _example():
    # conversations/{john/{growth, progression}, jane}, ideas
    return [
        _folder(
            "c",
            "conversations",
            [
                _folder(
                    "j",
                    "john",
                    [_doc("g", "growth"), _doc("p", "progression")],
                ),
                _doc("ja", "jane"),
            ],
        ),
        _doc("i", "ideas"),
    ]


def test_leaf_paths_are_docs_only_depth_first():
    assert ni.leaf_paths(_example()) == [
        "conversations/john/growth",
        "conversations/john/progression",
        "conversations/jane",
        "ideas",
    ]


def test_resolve_path_case_insensitive_leaf_match():
    node = ni.resolve_path(_example(), "Conversations/John/Growth")
    assert node is not None and node["node_id"] == "g"


def test_resolve_path_folder_or_unknown_is_none():
    assert ni.resolve_path(_example(), "conversations/john") is None  # a folder
    assert ni.resolve_path(_example(), "conversations/nope") is None  # unknown
    assert ni.resolve_path(_example(), None) is None


def test_canonical_path_uses_stored_casing():
    chain = ni.locate_chain(_example(), "CONVERSATIONS/john/GROWTH")
    assert ni.canonical_path(chain) == "conversations/john/growth"


def test_validate_accepts_the_example_tree():
    ni.validate(_example())  # no raise


def test_validate_rejects_duplicate_siblings():
    tree = [_doc("a", "notes"), _doc("b", "Notes")]  # case-insensitive dup
    with pytest.raises(ApiError):
        ni.validate(tree)


def test_validate_rejects_doc_with_children():
    tree = [{"node_id": "x", "name": "d", "kind": "doc", "children": [_doc("y", "z")]}]
    with pytest.raises(ApiError):
        ni.validate(tree)


def test_validate_rejects_overlong_and_control_chars():
    with pytest.raises(ApiError):
        ni.validate([_doc("a", "x" * 61)])
    with pytest.raises(ApiError):
        ni.validate([_doc("a", "bad\nname")])


def test_validate_rejects_over_depth():
    # 6 nested folders + a doc = depth 7 > 5.
    node = _doc("leaf", "d")
    for i in range(6):
        node = _folder(f"f{i}", f"f{i}", [node])
    with pytest.raises(ApiError):
        ni.validate([node])


def test_validate_rejects_too_many_docs():
    tree = [_doc(str(i), f"d{i}") for i in range(ni.MAX_LEAF_DOCS + 1)]
    with pytest.raises(ApiError):
        ni.validate(tree)


def test_validate_rejects_duplicate_node_ids():
    with pytest.raises(ApiError):
        ni.validate([_doc("dup", "a"), _doc("dup", "b")])


def test_sanitize_drops_client_drive_ids():
    incoming = [
        {
            "node_id": "a",
            "name": "  x  ",
            "kind": "doc",
            "drive_id": "SPOOFED",
            "children": [],
        }
    ]
    out = ni.sanitize_incoming(incoming)
    assert out == [{"node_id": "a", "name": "x", "kind": "doc", "children": []}]
    assert "drive_id" not in out[0]
