"""In-process scheduler for the auto-router (goal 5).

A single asyncio task started from the FastAPI lifespan periodically routes any
`UNROUTED` scratch entries — no Celery / broker (single-user local app). The
manual `route-now` endpoint calls the same `route_unrouted` directly, so dev/eval
never waits on the timer. Disable with `ROUTER_SCHEDULER_ENABLED=0`.
"""

from __future__ import annotations

import asyncio
import logging
import os

from sqlmodel import Session

from app.db import engine
from app.router import service as router_svc

_log = logging.getLogger("router.scheduler")

_ENABLED = os.environ.get("ROUTER_SCHEDULER_ENABLED", "1") not in ("0", "false", "")
_INTERVAL = float(os.environ.get("ROUTER_SCHEDULER_INTERVAL", "300"))

_task: asyncio.Task | None = None


async def _loop() -> None:
    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            with Session(engine) as session:
                tally = await router_svc.route_unrouted(session)
            if any(tally.values()):
                _log.info("router scheduler tally: %s", tally)
        except asyncio.CancelledError:
            raise
        except Exception:  # never let a transient failure kill the loop
            _log.exception("router scheduler tick failed")


def start() -> None:
    global _task
    if not _ENABLED or _task is not None:
        return
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
