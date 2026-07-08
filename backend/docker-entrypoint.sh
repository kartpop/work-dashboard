#!/bin/sh
# Migrate then serve (goal 8). SQLite lives on the mounted /data volume; WAL mode is
# set by app.db on connect. Alembic is the source of truth for schema in prod.
set -e

mkdir -p /data /data/backups

echo "==> alembic upgrade head"
uv run alembic upgrade head

echo "==> starting uvicorn on :8010"
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
