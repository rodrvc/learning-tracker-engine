#!/usr/bin/env bash
# Puts the demo back to its known state: deletes the demo organizations' data
# (only the fixed demo user ids and the two demo organizations) and seeds it
# again with every date relative to now. Run it right before a demo, with the
# database up (scripts/dev-up.sh). See docs/demo.md.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${LEARNING_TRACKER_DATABASE_URL:?Set LEARNING_TRACKER_DATABASE_URL first: cp .env.example .env (and edit it), or export it yourself.}"

if [ -x .venv/bin/python ]; then
  python=.venv/bin/python
else
  python=python
fi

exec "$python" -m scripts.seed_demo --reset
