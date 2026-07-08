# syntax=docker/dockerfile:1
#
# Single-container image (goal 8): build the Vite frontend, then serve it + the
# FastAPI API from one Python process. Fronted by Caddy (see docker-compose.yml).

# ── Stage 1: build the Vite frontend ──────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin in prod — the API is served by this same container, so no base URL.
ENV VITE_API_BASE_URL=""
RUN npm run build

# ── Stage 2: backend + static serving ─────────────────────────────────────────
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# sqlite3 for the nightly `.backup` cron; curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend
COPY backend/ ./
# Prod deps only (no pytest / ruff / playwright).
RUN uv sync --no-dev

# The built SPA, served by app.main via StaticFiles.
COPY --from=frontend /frontend/dist /srv/frontend/dist

ENV FRONTEND_DIST=/srv/frontend/dist \
    DATABASE_URL=sqlite:////data/overlay.db \
    COOKIE_SECURE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8010
CMD ["/srv/backend/docker-entrypoint.sh"]
