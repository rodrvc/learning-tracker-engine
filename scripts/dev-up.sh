#!/usr/bin/env bash
# One command: brings up Postgres, applies migrations and starts the API.
#
# Usage, from anywhere in the repo:
#
#     scripts/dev-up.sh
#
# Assumes dependencies are already installed (`pip install -e ".[web,postgres]"`
# in an active virtualenv - see README.md) and Docker is running. Everything
# here fails loudly and stops: a half-applied migration or a server that
# never started is not something this script papers over with a green exit
# code.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${LEARNING_TRACKER_DATABASE_URL:?Set LEARNING_TRACKER_DATABASE_URL first: cp .env.example .env (and edit it), or export it yourself.}"
schema="${LEARNING_TRACKER_SCHEMA:-learning}"

echo "==> starting postgres (docker compose)"
docker compose up -d --wait postgres

echo "==> applying migrations to schema '${schema}'"
python -m migrations.runner "$LEARNING_TRACKER_DATABASE_URL" "$schema"

echo "==> starting the API on ${LEARNING_TRACKER_WEB_HOST:-127.0.0.1}:${LEARNING_TRACKER_WEB_PORT:-8000}"
exec python -m web.app
