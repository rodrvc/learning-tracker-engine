"""Tests of migrations/runner.py that need no database (ACU-256).

``apply_migrations`` composes the schema name as a ``psycopg.sql.Identifier``
in every statement it builds, which quoting protects. But it also does a plain
string ``.replace("__SCHEMA__", schema)`` on each migration file's body, a path
identifier quoting cannot reach. These tests verify that path is closed before
a connection is ever attempted, so no database is required to run them.
"""

from __future__ import annotations

import pytest

# migrations/runner.py imports psycopg unconditionally, so importing it at all
# requires the 'postgres' extra — skip this module cleanly when it is absent,
# same as tests/test_store.py does for its Postgres-backed tests.
pytest.importorskip("psycopg")

from migrations.runner import apply_migrations  # noqa: E402


@pytest.mark.parametrize(
    "schema",
    [
        "learning; DROP SCHEMA public CASCADE; --",
        "Learning",
        "1learning",
        "learning-test",
        "learning test",
        "",
    ],
)
def test_apply_migrations_rejects_invalid_schema_name(schema: str) -> None:
    with pytest.raises(ValueError):
        apply_migrations("postgresql://unused/unused", schema=schema)


@pytest.mark.parametrize("schema", ["learning", "learning_test", "_private", "a1"])
def test_valid_schema_names_pass_validation(schema: str) -> None:
    # A valid name must not raise before the connection attempt, which fails
    # instead against the bogus DSN — proof that validation itself let it pass.
    with pytest.raises(Exception) as excinfo:
        apply_migrations("postgresql://unused/unused", schema=schema)
    assert not isinstance(excinfo.value, ValueError)
