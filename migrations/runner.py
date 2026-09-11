"""Minimal migration runner. Deliberately NOT a framework.

Applies the numbered ``*_*.sql`` files of this directory, in ascending order,
each inside its own transaction. Applied versions are recorded in
``<schema>.schema_migrations``, so re-running is a no-op: only files whose
version is not yet in that table are executed.

Every file may use the ``__SCHEMA__`` placeholder instead of a hardcoded
schema name, so the same migrations can build a throwaway schema for tests
(SPEC ACU-247) and the real ``learning`` schema in production.

Usage: ``python -m migrations.runner <dsn> [schema]``
"""

from __future__ import annotations

import pathlib
import re
import sys

import psycopg
from psycopg import sql

MIGRATIONS_DIR = pathlib.Path(__file__).parent
DEFAULT_SCHEMA = "learning"
_FILENAME_RE = re.compile(r"^(\d+)_.*\.sql$")


def apply_migrations(
    dsn: str, schema: str = DEFAULT_SCHEMA, directory: pathlib.Path = MIGRATIONS_DIR
) -> int:
    """Applies every pending migration against ``schema``. Returns how many ran."""
    applied = 0
    # The schema name is composed into the statement as an identifier rather
    # than interpolated as text. These statements take no parameters, which
    # puts them on the simple protocol, where a name carrying a semicolon
    # would be accepted as a second statement. It also stops Postgres from
    # silently lowercasing a name that has capitals in it.
    name = sql.Identifier(schema)
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(name))
        conn.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {}.schema_migrations ("
                "version integer PRIMARY KEY, "
                "applied_at timestamptz NOT NULL DEFAULT now())"
            ).format(name)
        )
        conn.commit()
        done = {
            row[0]
            for row in conn.execute(
                sql.SQL("SELECT version FROM {}.schema_migrations").format(name)
            )
        }
        for path in sorted(directory.glob("*.sql")):
            match = _FILENAME_RE.match(path.name)
            if not match:
                continue
            version = int(match.group(1))
            if version in done:
                continue
            statements = path.read_text(encoding="utf-8").replace("__SCHEMA__", schema)
            conn.execute(statements)
            conn.execute(
                sql.SQL(
                    "INSERT INTO {}.schema_migrations (version) VALUES (%s)"
                ).format(name),
                (version,),
            )
            conn.commit()
            applied += 1
    return applied


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m migrations.runner <dsn> [schema]")
        return 1
    dsn = argv[0]
    schema = argv[1] if len(argv) > 1 else DEFAULT_SCHEMA
    applied = apply_migrations(dsn, schema=schema)
    print(f"{applied} migration(s) applied to schema {schema!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
