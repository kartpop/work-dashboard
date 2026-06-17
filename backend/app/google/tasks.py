"""Read-only access to the account's Google Tasks lists and tasks.

This is the only module that talks to the Google Tasks API directly (see
CLAUDE.md hard constraint: read paths call the Google API client directly,
never via MCP/LLM).
"""

from __future__ import annotations

import asyncio

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.google._paging import list_all
from app.google.auth import load_credentials


def _tasks_service():
    return build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)


def _reshape_task(task: dict) -> dict:
    """Map a raw Google Tasks resource to our small, stable shape."""
    return {
        "id": task["id"],
        "title": task.get("title", ""),
        "status": task.get("status", "needsAction"),
        "due": task.get("due"),
        "notes": task.get("notes"),
    }


def _fetch_task_lists() -> list[dict]:
    service = _tasks_service()

    task_lists = []
    for task_list in list_all(service.tasklists()):
        tasks = list_all(
            service.tasks(),
            tasklist=task_list["id"],
            showCompleted=True,
            showHidden=True,
        )
        task_lists.append(
            {
                "id": task_list["id"],
                "title": task_list.get("title", ""),
                "tasks": [_reshape_task(task) for task in tasks],
            }
        )
    return task_lists


async def get_task_lists() -> list[dict]:
    """Return every task list in the account, each with its tasks."""
    return await asyncio.to_thread(_fetch_task_lists)


# ── Read helper used by the writes service ────────────────────────────────────


def _get_task(tasklist_id: str, task_id: str) -> dict | None:
    service = _tasks_service()
    try:
        task = service.tasks().get(tasklist=tasklist_id, task=task_id).execute()
    except HttpError as exc:
        if exc.resp.status == 404:
            return None
        raise
    return _reshape_task(task)


async def get_task(tasklist_id: str, task_id: str) -> dict | None:
    """Fetch a single task; return None if it does not exist (404)."""
    return await asyncio.to_thread(_get_task, tasklist_id, task_id)


# ── Thin write wrappers (one Google call each; no orchestration) ──────────────


def _update_due_date(tasklist_id: str, task_id: str, due: str | None) -> None:
    service = _tasks_service()
    if due is not None:
        service.tasks().patch(
            tasklist=tasklist_id, task=task_id, body={"due": due}
        ).execute()
        return
    # GOOGLE QUIRK: the Tasks API ignores a null `due` on patch, so clearing the
    # due date requires a full get-then-update (the one exception to "one API call").
    task = service.tasks().get(tasklist=tasklist_id, task=task_id).execute()
    task.pop("due", None)
    service.tasks().update(tasklist=tasklist_id, task=task_id, body=task).execute()


async def update_due_date(tasklist_id: str, task_id: str, due: str | None) -> None:
    """Set (patch) or clear (get+update) the Google due date for a task."""
    await asyncio.to_thread(_update_due_date, tasklist_id, task_id, due)


def _insert_task(tasklist_id: str, body: dict) -> dict:
    service = _tasks_service()
    task = service.tasks().insert(tasklist=tasklist_id, body=body).execute()
    return _reshape_task(task)


async def insert_task(tasklist_id: str, body: dict) -> dict:
    """Insert a new task into a list and return its reshaped representation."""
    return await asyncio.to_thread(_insert_task, tasklist_id, body)


def _delete_task(tasklist_id: str, task_id: str) -> None:
    service = _tasks_service()
    service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()


async def delete_task(tasklist_id: str, task_id: str) -> None:
    # Only callable from app.writes.service.move (sanctioned-delete exception).
    await asyncio.to_thread(_delete_task, tasklist_id, task_id)
