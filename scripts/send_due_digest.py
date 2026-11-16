"""Send each user the daily digest of what is due (issue #68).

Meant to be run by a cron once a day. See ``docs/due-digest.md`` for the
Railway cron setup.

Usage, from the repo root::

    python -m scripts.send_due_digest                 # print to stdout
    python -m scripts.send_due_digest --sender file --out digests.log
    python -m scripts.send_due_digest --sender smtp   # real email, SMTP vars required
    python -m scripts.send_due_digest --as-of 2026-11-15T11:00:00+00:00

Data is per user (issue #58), so the digest is too: for every user that owns
data, the job reads *that user's* topics only and sends *that user* a message
about their own items; two users are never mixed in one message. The address
of each user comes from ``LEARNING_TRACKER_DIGEST_RECIPIENTS``, a JSON object
mapping a user id to an email address::

    {"user_2abc": "ana@example.com", "user_2def": "profe@example.com"}

This mapping is a stop-gap until the email comes from Clerk. A user without a
mapped address is skipped, and the skip is logged.

A user with nothing due gets nothing. Exit code: 0 on success (sent or
silent), 2 on configuration errors, 1 if any send failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Callable, Iterable, Mapping, Sequence

from core.errors import StorageError
from core.storage import AttemptStore, ProfileStore
from notify.digest import build_digest, render_subject, render_text
from notify.senders import (
    ConsoleSender,
    FileSender,
    Message,
    Sender,
    SmtpConfigError,
    SmtpSender,
    SmtpSettings,
)

RECIPIENTS_VAR = "LEARNING_TRACKER_DIGEST_RECIPIENTS"
#: Public URL of the web app, for the practice links in the message.
BASE_URL_VAR = "LEARNING_TRACKER_PUBLIC_URL"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
ALL_TOPICS = "*"


class ConfigError(RuntimeError):
    pass


def parse_recipients(raw: str | None) -> dict[str, str]:
    """Parses the user id -> email mapping."""
    if not raw:
        raise ConfigError(f"set {RECIPIENTS_VAR} (see docs/due-digest.md)")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{RECIPIENTS_VAR} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ConfigError(f"{RECIPIENTS_VAR} must be a non-empty JSON object")
    parsed: dict[str, str] = {}
    for user_id, email in data.items():
        if not user_id.strip():
            raise ConfigError(f"{RECIPIENTS_VAR}: empty user id")
        if not isinstance(email, str) or "@" not in email:
            raise ConfigError(f"{RECIPIENTS_VAR}: {email!r} (for {user_id}) is not an email address")
        parsed[user_id] = email
    return parsed


#: Opens one user's stores. Every store it returns is scoped to that user, so
#: nothing the digest reads can belong to anyone else.
StoresFor = Callable[[str], tuple[ProfileStore, AttemptStore]]


def run(
    stores_for: StoresFor,
    user_ids: Iterable[str],
    sender: Sender,
    recipients: Mapping[str, str],
    as_of: datetime,
    base_url: str,
    log=sys.stderr,
) -> int:
    """Builds and sends one digest per user. Returns the exit code."""
    failures = 0
    for user_id in user_ids:
        email = recipients.get(user_id)
        if email is None:
            print(f"{user_id}: no email mapped, skipped", file=log)
            continue
        profiles, attempts = stores_for(user_id)
        digest = build_digest(profiles, attempts, as_of, base_url)
        if digest.is_empty:
            print(f"{user_id}: nothing due, nothing sent", file=log)
            continue
        message = Message(to=email, subject=render_subject(digest), body=render_text(digest))
        try:
            sender.send(message)
        except Exception as exc:  # one bad address must not silence everyone else
            failures += 1
            print(f"{user_id}: send failed: {exc}", file=log)
        else:
            print(f"{user_id}: sent ({digest.total_due} due)", file=log)
    return 1 if failures else 0


def build_sender(kind: str, out: str | None, env: Mapping[str, str]) -> Sender:
    if kind == "console":
        return ConsoleSender()
    if kind == "file":
        if not out:
            raise ConfigError("--sender file needs --out PATH")
        return FileSender(out)
    if kind == "smtp":
        try:
            return SmtpSender(SmtpSettings.from_env(env))
        except SmtpConfigError as exc:
            raise ConfigError(str(exc)) from exc
    raise ConfigError(f"unknown sender {kind!r}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m scripts.send_due_digest", description=__doc__.split("\n")[0])
    parser.add_argument("--sender", choices=("console", "file", "smtp"), default="console")
    parser.add_argument("--out", help="file to append to, with --sender file")
    parser.add_argument(
        "--as-of",
        help="ISO date-time with timezone to compute the digest at; default: now (UTC)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    args = _parse_args(argv)
    try:
        recipients = parse_recipients(env.get(RECIPIENTS_VAR))
        sender = build_sender(args.sender, args.out, env)
        as_of = _resolve_as_of(args.as_of)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Imported here so the parsing above (and its tests) needs no database driver.
    from store.postgres import PostgresAttemptStore, PostgresProfileStore
    from web.config import DATABASE_URL_VAR, SCHEMA_VAR

    dsn = env.get(DATABASE_URL_VAR)
    if not dsn:
        print(f"error: set {DATABASE_URL_VAR} first (see .env.example)", file=sys.stderr)
        return 2
    schema = env.get(SCHEMA_VAR) or "learning"
    try:
        base_profiles = PostgresProfileStore.from_dsn(dsn, schema=schema)
        base_attempts = PostgresAttemptStore.from_dsn(dsn, schema=schema)
        return run(
            lambda user_id: (base_profiles.for_user(user_id), base_attempts.for_user(user_id)),
            base_profiles.list_user_ids(),
            sender,
            recipients,
            as_of,
            env.get(BASE_URL_VAR) or DEFAULT_BASE_URL,
        )
    except StorageError as exc:
        print(f"error: could not read the engine: {exc}", file=sys.stderr)
        return 1


def _resolve_as_of(raw: str | None) -> datetime:
    """The one place this feature reads the system clock (SPEC I2)."""
    if raw is None:
        from store import SystemClock

        return SystemClock().now()
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigError(f"--as-of is not an ISO date-time: {raw!r}") from exc
    if moment.tzinfo is None:
        raise ConfigError("--as-of needs a timezone, e.g. 2026-11-15T11:00:00+00:00")
    return moment


if __name__ == "__main__":
    raise SystemExit(main())
