#!/bin/sh
set -e
alembic upgrade head
python -m scripts.seed || true
exec "$@"
