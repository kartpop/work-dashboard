from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.errors import ApiError
from app.google import tasks as tasks_client
from app.overlay import service as overlay_svc

router = APIRouter()


@router.get("/tasks")
async def list_tasks(
    view: Annotated[Literal["grouped", "flat"], Query()] = "grouped",
    show_completed: Annotated[bool, Query()] = False,
    session: Session = Depends(get_session),
):
    try:
        raw_lists = await tasks_client.get_task_lists()
    except Exception as exc:
        raise ApiError(502, "google_tasks_unavailable", "Could not fetch Google Tasks.") from exc

    task_lists = overlay_svc.get_merged_task_lists(
        session, raw_lists, view=view, show_completed=show_completed
    )
    return {"task_lists": task_lists}


class OverlayUpdate(BaseModel):
    rank: Optional[float] = None
    priority: Optional[int] = None


@router.patch("/tasks/{tasklist_id}/{task_id}/overlay")
async def update_overlay(
    tasklist_id: str,
    task_id: str,
    body: OverlayUpdate,
    session: Session = Depends(get_session),
):
    if body.rank is None and body.priority is None:
        raise ApiError(400, "no_fields", "Provide at least one of rank or priority.")
    row = overlay_svc.upsert_overlay(
        session,
        tasklist_id=tasklist_id,
        task_id=task_id,
        rank=body.rank,
        priority=body.priority,
    )
    return {"tasklist_id": row.tasklist_id, "task_id": row.task_id, "rank": row.rank, "priority": row.priority}
