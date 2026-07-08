"""In-process scheduler for the auto-router (goal 5).

A single asyncio task started from the FastAPI lifespan periodically routes any
`UNROUTED` scratch entries — no Celery / broker (single-user local app). The
manual `route-now` endpoint calls the same `route_unrouted` directly, so dev/eval
never waits on the timer. Disable with `ROUTER_SCHEDULER_ENABLED=0`.

Goal 7c: capture routes inline (`POST /scratch`), so this loop is demoted to a
**retry backstop** — it only picks up entries that inline routing left UNROUTED
(crash/downtime recovery, transient Google/Docs failures). Hence the ~15-min default
interval; nothing user-facing waits on the timer anymore.
"""

from __future__ import annotations

import asyncio
import logging
import os

from sqlmodel import Session, select

from app.auth.models import User
from app.db import engine
from app.google import auth as google_auth
from app.router import service as router_svc

_log = logging.getLogger("router.scheduler")

_ENABLED = os.environ.get("ROUTER_SCHEDULER_ENABLED", "1") not in ("0", "false", "")
_INTERVAL = float(os.environ.get("ROUTER_SCHEDULER_INTERVAL", "900"))

_task: asyncio.Task | None = None


async def _route_all_users() -> None:
    """Per-user backstop (goal 8): route each user's UNROUTED entries with THAT
    user's credentials. A user whose token can't load is skipped (logged), never
    stalling the rest."""
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        for user in users:
            if not user.refresh_token_encrypted:
                continue
            try:
                creds = google_auth.load_credentials(session, user)
            except Exception as exc:  # noqa: BLE001 — per-user, best-effort
                _log.warning("scheduler: skipping user %s (creds): %s", user.id, exc)
                continue
            try:
                tally = await router_svc.route_unrouted(session, user, creds)
            except Exception:
                _log.exception("scheduler: routing failed for user %s", user.id)
                continue
            if any(tally.values()):
                _log.info("router scheduler tally (user %s): %s", user.id, tally)


async def _loop() -> None:
    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            await _route_all_users()
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
