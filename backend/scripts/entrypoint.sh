#!/bin/sh
set -e

# Api service runs migrations; Celery workers set RUN_MIGRATIONS=false to avoid a race.
if [ "${RUN_MIGRATIONS:-true}" != "false" ]; then
  alembic upgrade head
fi

# Opt-in only — demo accounts must not appear in production by default.
if [ "${RUN_SEED:-false}" = "true" ]; then
  python -m scripts.seed || true
fi

exec "$@"
