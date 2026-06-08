"""Shared pagination helper for Google API list() calls."""

from __future__ import annotations

from typing import Any


def list_all(resource: Any, **list_kwargs: Any) -> list[dict]:
    """Collect every item across all pages of a `resource.list(...)` call."""
    items: list[dict] = []
    page_token: str | None = None
    while True:
        response = resource.list(pageToken=page_token, **list_kwargs).execute()
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return items
