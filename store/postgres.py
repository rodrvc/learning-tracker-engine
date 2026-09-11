"""PostgreSQL backend. Driver: ``psycopg`` version 3.

Same interface and same rules as the memory and JSON backends: ordering,
cut, duplicate detection and validation are enforced identically (SPEC
sections 6 and 7). Where the memory/JSON backends run the shared logic of
``store._common`` over a Python list, this backend expresses the same rules as
SQL (``ORDER BY at, attempt_id`` for the cut/order guarantee, a ``PRIMARY KEY``
on ``attempt_id`` alone for the duplicate guarantee) because that is what a SQL
engine is for; the pure validation helpers of ``store._common`` that do not
depend on the storage medium (``validate_attempt``, ``validate_objective``,
``validate_profile``) are reused as-is.

Every operation asks the injected ``connect`` callable (``ConnectionProvider``)
for a **context manager** and uses it with ``with ... as conn:`` around exactly
that one operation. The context manager, not this module, decides what
entering and leaving it means: a plain ``psycopg.connect(dsn)`` call returns a
``psycopg.Connection``, which is its own context manager and commits-or-rolls-
back *and closes* on exit; ``pool.connection`` (from ``psycopg_pool``) returns
a context manager that also commits-or-rolls-back on exit, but *returns the
connection to the pool* instead of closing it. This module never calls
``.close()`` itself and never holds a connection between operations, so
whichever shape the provider hands back, each method still gets its own
transaction — which is what makes ``append`` atomic (SPEC I8): either the
whole statement lands, or nothing does and a ``StorageError`` is raised — and
the resource is released, one way or the other, before the method returns.

That is the point of the seam: the web layer that will sit on top of this
backend cannot afford one connection per request against a hosted Postgres, so
it can inject a real pool and get pooling, instead of a factory that opens and
closes a fresh connection under the hood regardless of what the caller passed
in. Constructing a store straight from a DSN — the common case for the CLI and
for tests — stays a one-liner through :meth:`PostgresAttemptStore.from_dsn` /
:meth:`PostgresProfileStore.from_dsn`, which wrap ``psycopg.connect`` as the
provider.

The datetime trap
------------------

``Attempt.at`` must be an aware ``datetime``. The JSON backend stores the
literal offset it was given (an attempt recorded at ``-05:00`` comes back at
``-05:00``). Postgres' ``timestamptz`` does not: it stores an instant and
returns it normalized to the session's timezone. **This backend returns every
instant normalized to UTC.**

This is a deliberate decision, not an oversight: the contract this backend
honours is "the same instant comes back", not "the same offset comes back".
Since aware ``datetime`` equality in Python compares instants regardless of
offset, code written against the shared ``AttemptStore`` contract cannot
observe the difference through ``==``; only code that inspects ``.tzinfo`` or
``.utcoffset()`` directly would.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, ContextManager, Iterable

import psycopg
from psycopg import errors as pg_errors

from core.errors import (
    DuplicateAttemptError,
    StorageError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.models import Attempt, AttemptKind, Objective, Profile

from ._common import validate_attempt, validate_objective, validate_profile

DEFAULT_SCHEMA = "learning"

#: A zero-argument callable that returns a **context manager** yielding an
#: open ``psycopg.Connection``. The stores below call it once per operation,
#: use the result with ``with ... as conn:``, and never hold on to it between
#: calls; what entering and leaving that context manager does internally (a
#: plain ``psycopg.connect`` that closes on exit, a ``pool.connection`` that
#: returns the connection to the pool, a proxy) is the caller's concern, not
#: this module's — see the module docstring.
ConnectionProvider = Callable[[], ContextManager[psycopg.Connection]]


def _open_connection(connect: ConnectionProvider) -> ContextManager[psycopg.Connection]:
    """Calls ``connect`` and turns whatever it raises into ``StorageError``.

    The provider is arbitrary caller code, not necessarily ``psycopg.connect``,
    so this catches broadly rather than only ``psycopg.Error``: a failing
    provider must surface as ``StorageError``, never as a leaked driver (or
    other) exception (SPEC I8 — no silent half success, and no leaking
    concretions either). ``KeyboardInterrupt`` still propagates: it is a
    ``BaseException``, not an ``Exception``.
    """
    try:
        return connect()
    except Exception as exc:
        raise StorageError("no se pudo conectar a postgres") from exc


def _to_utc(moment: datetime | None) -> datetime | None:
    """Normalizes an aware ``datetime`` to UTC. See the module docstring."""
    return None if moment is None else moment.astimezone(timezone.utc)


def _row_to_attempt(row: tuple) -> Attempt:
    attempt_id, objective_id, at, correct, kind, confidence, note, recorded_at = row
    return Attempt(
        attempt_id=attempt_id,
        objective_id=objective_id,
        at=_to_utc(at),
        correct=correct,
        kind=AttemptKind(kind),
        confidence=confidence,
        note=note,
        recorded_at=_to_utc(recorded_at),
    )


def _row_to_objective(row: tuple) -> Objective:
    objective_id, title, domain, weight, tags = row
    return Objective(
        objective_id=objective_id,
        title=title,
        domain=domain,
        weight=weight,
        tags=tuple(tags or ()),
    )


class PostgresAttemptStore:
    """``AttemptStore`` over PostgreSQL. It only appends and reads (SPEC I1).

    Args:
        connect: zero-argument callable returning a context manager that
            yields an open ``psycopg.Connection`` (see
            :data:`ConnectionProvider`). Use :meth:`from_dsn` when a plain
            DSN is all that is needed.
        schema: schema the tables live in. Defaults to ``"learning"``, the
            production schema; tests point it at a throwaway one.
    """

    def __init__(
        self, connect: ConnectionProvider, schema: str = DEFAULT_SCHEMA
    ) -> None:
        self._connect_fn = connect
        self._schema = schema

    @classmethod
    def from_dsn(cls, dsn: str, schema: str = DEFAULT_SCHEMA) -> "PostgresAttemptStore":
        """Convenience constructor: opens a plain ``psycopg.connect(dsn)`` per operation."""
        return cls(lambda: psycopg.connect(dsn), schema=schema)

    def _connect(self) -> ContextManager[psycopg.Connection]:
        return _open_connection(self._connect_fn)

    def append(self, profile_id: str, attempt: Attempt) -> Attempt:
        """Persists an attempt. See :meth:`core.storage.AttemptStore.append`."""
        validate_attempt(profile_id, attempt, ())
        try:
            with self._connect() as conn:
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.attempts
                        (attempt_id, profile_id, objective_id, at, correct,
                         kind, confidence, note, recorded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        attempt.attempt_id,
                        profile_id,
                        attempt.objective_id,
                        attempt.at,
                        attempt.correct,
                        attempt.kind.value,
                        attempt.confidence,
                        attempt.note,
                        attempt.recorded_at,
                    ),
                )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateAttemptError(attempt.attempt_id) from exc
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo guardar el intento: {exc}") from exc
        return attempt

    def _select(self, where: str, params: tuple) -> list[Attempt]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT attempt_id, objective_id, at, correct, kind,
                           confidence, note, recorded_at
                    FROM {self._schema}.attempts
                    {where}
                    ORDER BY at, attempt_id
                    """,
                    params,
                ).fetchall()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo leer los intentos: {exc}") from exc
        return [_row_to_attempt(row) for row in rows]

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Attempts of an objective, sorted by ``at`` and ``attempt_id``."""
        where = "WHERE profile_id = %s AND objective_id = %s"
        params = (profile_id, objective_id)
        if until is not None:
            where += " AND at <= %s"
            params += (until,)
        return self._select(where, params)

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Every attempt of the profile, sorted, with an optional cut."""
        where = "WHERE profile_id = %s"
        params = (profile_id,)
        if until is not None:
            where += " AND at <= %s"
            params += (until,)
        return self._select(where, params)

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Number of attempts of the profile (or of the objective, when given)."""
        where = "WHERE profile_id = %s"
        params: tuple = (profile_id,)
        if objective_id is not None:
            where += " AND objective_id = %s"
            params += (objective_id,)
        try:
            with self._connect() as conn:
                (total,) = conn.execute(
                    f"SELECT count(*) FROM {self._schema}.attempts {where}", params
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo contar los intentos: {exc}") from exc
        return total

    def exists(self, attempt_id: str) -> bool:
        """Whether an attempt with that id already exists, in any profile."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT 1 FROM {self._schema}.attempts WHERE attempt_id = %s",
                    (attempt_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo verificar el intento: {exc}") from exc
        return row is not None


class PostgresProfileStore:
    """``ProfileStore`` over PostgreSQL.

    Args:
        connect: zero-argument callable returning a context manager that
            yields an open ``psycopg.Connection`` (see
            :data:`ConnectionProvider`). Use :meth:`from_dsn` when a plain
            DSN is all that is needed.
        schema: schema the tables live in. Defaults to ``"learning"``.
    """

    def __init__(
        self, connect: ConnectionProvider, schema: str = DEFAULT_SCHEMA
    ) -> None:
        self._connect_fn = connect
        self._schema = schema

    @classmethod
    def from_dsn(cls, dsn: str, schema: str = DEFAULT_SCHEMA) -> "PostgresProfileStore":
        """Convenience constructor: opens a plain ``psycopg.connect(dsn)`` per operation."""
        return cls(lambda: psycopg.connect(dsn), schema=schema)

    def _connect(self) -> ContextManager[psycopg.Connection]:
        return _open_connection(self._connect_fn)

    def get_profile(self, profile_id: str) -> Profile:
        """Returns the profile or raises ``UnknownProfileError``."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT name FROM {self._schema}.profiles WHERE profile_id = %s",
                    (profile_id,),
                ).fetchone()
                if row is None:
                    raise UnknownProfileError(profile_id)
                rows = conn.execute(
                    f"""SELECT objective_id, title, domain, weight, tags
                        FROM {self._schema}.objectives WHERE profile_id = %s""",
                    (profile_id,),
                ).fetchall()
        except UnknownProfileError:
            raise
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo leer el perfil: {exc}") from exc
        objectives = {r[0]: _row_to_objective(r) for r in rows}
        return Profile(profile_id=profile_id, name=row[0], objectives=objectives)

    def save_profile(self, profile: Profile) -> Profile:
        """Replaces the whole profile: an omitted objective disappears (guarantee 7)."""
        validate_profile(profile)
        try:
            with self._connect() as conn:
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.profiles (profile_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (profile_id) DO UPDATE SET name = EXCLUDED.name
                    """,
                    (profile.profile_id, profile.name),
                )
                conn.execute(
                    f"DELETE FROM {self._schema}.objectives WHERE profile_id = %s",
                    (profile.profile_id,),
                )
                for objective in profile.objectives.values():
                    conn.execute(
                        f"""
                        INSERT INTO {self._schema}.objectives
                            (profile_id, objective_id, title, domain, weight, tags)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            profile.profile_id,
                            objective.objective_id,
                            objective.title,
                            objective.domain,
                            objective.weight,
                            list(objective.tags),
                        ),
                    )
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo guardar el perfil: {exc}") from exc
        return profile

    def list_profiles(self) -> list[Profile]:
        """Every profile, sorted by ``profile_id``.

        One connection, two statements: the profiles and every objective of
        every profile, joined in Python. Looping ``get_profile`` per row would
        mean N+1 *connections* (not just round trips) now that a connection is
        no longer assumed to be free, so it is deliberately avoided here.
        """
        try:
            with self._connect() as conn:
                profile_rows = conn.execute(
                    f"SELECT profile_id, name FROM {self._schema}.profiles ORDER BY profile_id"
                ).fetchall()
                objective_rows = conn.execute(
                    f"""SELECT profile_id, objective_id, title, domain, weight, tags
                        FROM {self._schema}.objectives"""
                ).fetchall()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo listar los perfiles: {exc}") from exc
        objectives_by_profile: dict[str, dict[str, Objective]] = {}
        for pid, *objective_row in objective_rows:
            objective = _row_to_objective(objective_row)
            by_id = objectives_by_profile.setdefault(pid, {})
            by_id[objective.objective_id] = objective
        return [
            Profile(
                profile_id=pid, name=name, objectives=objectives_by_profile.get(pid, {})
            )
            for pid, name in profile_rows
        ]

    def get_objective(self, profile_id: str, objective_id: str) -> Objective:
        """One objective of the profile. It fails loudly when missing (SPEC C8)."""
        profile = self.get_profile(profile_id)
        try:
            return profile.objectives[objective_id]
        except KeyError:
            raise UnknownObjectiveError(f"{profile_id}/{objective_id}") from None

    def list_objectives(self, profile_id: str) -> list[Objective]:
        """Objectives of the profile, sorted by ``objective_id``."""
        objectives = self.get_profile(profile_id).objectives
        return [objectives[key] for key in sorted(objectives)]

    def upsert_objectives(
        self, profile_id: str, objectives: Iterable[Objective]
    ) -> int:
        """Adds or replaces objectives of the profile. Returns how many it wrote."""
        incoming = list(objectives)
        for objective in incoming:
            validate_objective(objective)
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT 1 FROM {self._schema}.profiles WHERE profile_id = %s",
                    (profile_id,),
                ).fetchone()
                if row is None:
                    raise UnknownProfileError(profile_id)
                for objective in incoming:
                    conn.execute(
                        f"""
                        INSERT INTO {self._schema}.objectives
                            (profile_id, objective_id, title, domain, weight, tags)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (profile_id, objective_id) DO UPDATE SET
                            title = EXCLUDED.title, domain = EXCLUDED.domain,
                            weight = EXCLUDED.weight, tags = EXCLUDED.tags
                        """,
                        (
                            profile_id,
                            objective.objective_id,
                            objective.title,
                            objective.domain,
                            objective.weight,
                            list(objective.tags),
                        ),
                    )
        except UnknownProfileError:
            raise
        except psycopg.Error as exc:
            raise StorageError(f"no se pudieron guardar los objetivos: {exc}") from exc
        return len(incoming)


__all__ = [
    "PostgresAttemptStore",
    "PostgresProfileStore",
    "ConnectionProvider",
    "DEFAULT_SCHEMA",
]
