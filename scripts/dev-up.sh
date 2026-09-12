#!/usr/bin/env bash
# One command: brings up Postgres, applies migrations and starts the API.
#
# Usage, from anywhere in the repo:
#
#     scripts/dev-up.sh
#
# Assumes dependencies are already installed (`pip install -e ".[web]"` - see
# README.md) and Docker is running. Activating the virtualenv is not required:
# a `.venv` beside this repo is found on its own. Everything
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

# Checked here rather than left to fail two steps later. Forgetting to activate
# the virtualenv is the most likely way a first run goes wrong, and without this
# it surfaces as `python: command not found` from the migration step, which
# blames the wrong thing: the remedy is one line up, not in the migrations.
# `.venv/bin/python` is used when it exists, so the common case needs nothing.
if [ -x .venv/bin/python ]; then
  python=.venv/bin/python
elif command -v python >/dev/null 2>&1; then
  python=python
else
  echo "No usable python: none on PATH, and no working .venv in the repo." >&2
  echo "Create one and install the dependencies first:" >&2
  echo "  python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[web]'" >&2
  exit 1
fi

echo "==> starting postgres (docker compose)"
docker compose up -d --wait postgres

echo "==> applying migrations to schema '${schema}'"
"$python" -m migrations.runner "$LEARNING_TRACKER_DATABASE_URL" "$schema"

echo "==> starting the API on ${LEARNING_TRACKER_WEB_HOST:-127.0.0.1}:${LEARNING_TRACKER_WEB_PORT:-8000}"
exec "$python" -m web.app
