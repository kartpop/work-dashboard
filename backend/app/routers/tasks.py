from fastapi import APIRouter

from app.errors import ApiError
from app.google import tasks as tasks_client

router = APIRouter()


@router.get("/tasks")
async def list_tasks():
    try:
        task_lists = await tasks_client.get_task_lists()
    except Exception as exc:
        raise ApiError(502, "google_tasks_unavailable", "Could not fetch Google Tasks.") from exc
    return {"task_lists": task_lists}
