"""Read-only access to the account's Google Tasks lists and tasks.

This is the only module that talks to the Google Tasks API directly (see
CLAUDE.md hard constraint: read paths call the Google API client directly,
never via MCP/LLM).
"""

from __future__ import annotations

import asyncio

from googleapiclient.discovery import build

from app.google._paging import list_all
from app.google.auth import load_credentials


def _fetch_task_lists() -> list[dict]:
    service = build("tasks", "v1", credentials=load_credentials(), cache_discovery=False)

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
                "tasks": [
                    {
                        "id": task["id"],
                        "title": task.get("title", ""),
                        "status": task.get("status", "needsAction"),
                        "due": task.get("due"),
                        "notes": task.get("notes"),
                    }
                    for task in tasks
                ],
            }
        )
    return task_lists


async def get_task_lists() -> list[dict]:
    """Return every task list in the account, each with its tasks."""
    return await asyncio.to_thread(_fetch_task_lists)
