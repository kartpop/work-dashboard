from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env before importing any app module that reads env at import time
# (e.g. app.router.config) or at call time (the classifier's ANTHROPIC_API_KEY).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from app.db import create_tables  # noqa: E402
from app.google.auth import assert_scopes_within_allowlist  # noqa: E402
from app.router import scheduler as router_scheduler  # noqa: E402
from app.routers import calendar, scratch, tasks  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail-closed on a token that carries scopes beyond the allowlist (e.g. a broad
    # Drive/Docs grant left over from debugging) — see drive-access-scoping ADR.
    assert_scopes_within_allowlist()
    create_tables()
    router_scheduler.start()
    try:
        yield
    finally:
        await router_scheduler.stop()


app = FastAPI(title="Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "PATCH", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    detail = exc.detail
    if not (isinstance(detail, dict) and "code" in detail and "message" in detail):
        detail = {"code": "http_error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


app.include_router(tasks.router)
app.include_router(calendar.router)
app.include_router(scratch.router)
