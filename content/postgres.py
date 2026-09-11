"""PostgreSQL backend for study material and generated questions.

Same seam as ``store/postgres.py``: an injected ``ConnectionProvider`` (a
zero-argument callable returning a context manager over an open
``psycopg.Connection``), reused as-is from there rather than redefined, since
it is a pure type/helper with nothing engine-specific about it. Every
operation acquires a connection for exactly the one operation it performs and
lets ``_open_connection`` turn acquisition failures into ``StorageError`` -
see ``store/postgres.py`` for the full rationale, including why acquisition
is driven by hand instead of a plain ``with connect():``: a real pool can
fail on checkout (entering the context manager), not just on the call that
describes it, and both steps have to surface as ``StorageError``.

``Question.options`` is stored as a ``jsonb`` array of ``[key, text]`` pairs
(see ``migrations/0002_content.sql``): JSON preserves array order, so the
tuple round-trips exactly as given.

Ownership and topical consistency (``content/storage.py``'s ``QuestionStore``
docstring) are enforced structurally here, by the two foreign keys the
migration declares, rather than by calling ``content._common`` the way the
memory backend does: a violation of ``questions_material_id_fkey`` (no such
material) is mapped to :class:`~content.errors.UnknownMaterialError`, and a
violation of ``questions_material_topic_fkey`` (material exists, topic
differs) is mapped to :class:`~content.errors.InvalidQuestionError` -
distinguished by constraint name, so the two backends agree on WHICH
exception a caller sees, not merely that one is raised. The batch
duplicate-id check IS reused from ``content._common`` : this backend
pre-checks the incoming ids against the store, inside the same transaction
as the writes that follow, so it can raise with the exact colliding id
instead of leaking a driver message; the ``PRIMARY KEY`` stays as the
backstop for a race between that check and the insert.

The datetime trap
------------------

Like ``store/postgres.py``, this backend returns every ``created_at``
normalized to UTC, while the memory backend returns whatever offset it was
given. Aware ``datetime`` equality compares instants, so ``==`` cannot
observe the difference; only ``.utcoffset()`` can.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

import psycopg
from psycopg import errors as pg_errors

from store.postgres import ConnectionProvider, DEFAULT_SCHEMA, _open_connection

from ._common import reject_duplicate_ids
from .errors import (
    DuplicateMaterialError,
    DuplicateQuestionError,
    InvalidQuestionError,
    StorageError,
    UnknownMaterialError,
    UnknownQuestionError,
)
from .models import Material, Question

#: Name of the composite foreign key that enforces topical consistency (see
#: migrations/0002_content.sql). A violation of THIS constraint means the
#: material exists but under a different topic; any other foreign key
#: violation on ``questions`` means the material does not exist at all.
_TOPIC_FK_CONSTRAINT = "questions_material_topic_fkey"


def _to_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc)


def _row_to_material(row: tuple) -> Material:
    material_id, topic_id, title, source, body, created_at = row
    return Material(
        material_id=material_id,
        topic_id=topic_id,
        title=title,
        source=source,
        body=body,
        created_at=_to_utc(created_at),
    )


def _row_to_question(row: tuple) -> Question:
    (
        question_id,
        topic_id,
        objective_id,
        stem,
        options,
        correct_key,
        explanation,
        material_id,
        created_at,
    ) = row
    return Question(
        question_id=question_id,
        topic_id=topic_id,
        objective_id=objective_id,
        stem=stem,
        options=tuple((key, text) for key, text in options),
        correct_key=correct_key,
        explanation=explanation,
        material_id=material_id,
        created_at=_to_utc(created_at),
    )


class PostgresMaterialStore:
    """``MaterialStore`` over PostgreSQL. It only appends and reads.

    Args:
        connect: zero-argument callable returning a context manager that
            yields an open ``psycopg.Connection`` (see
            :data:`store.postgres.ConnectionProvider`). Use :meth:`from_dsn`
            when a plain DSN is all that is needed.
        schema: schema the tables live in. Defaults to ``"learning"``.
    """

    def __init__(self, connect: ConnectionProvider, schema: str = DEFAULT_SCHEMA) -> None:
        self._connect_fn = connect
        self._schema = schema

    @classmethod
    def from_dsn(cls, dsn: str, schema: str = DEFAULT_SCHEMA) -> "PostgresMaterialStore":
        """Convenience constructor: opens a plain ``psycopg.connect(dsn)`` per operation."""
        return cls(lambda: psycopg.connect(dsn), schema=schema)

    def _connect(self):
        return _open_connection(self._connect_fn)

    def add(self, material: Material) -> Material:
        """Persists a material. See ``content.storage.MaterialStore.add``."""
        try:
            with self._connect() as conn:
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.materials
                        (material_id, topic_id, title, source, body, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        material.material_id,
                        material.topic_id,
                        material.title,
                        material.source,
                        material.body,
                        material.created_at,
                    ),
                )
        except pg_errors.UniqueViolation as exc:
            raise DuplicateMaterialError(material.material_id) from exc
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo guardar el material: {exc}") from exc
        return material

    def get(self, material_id: str) -> Material:
        """Returns the material or raises ``UnknownMaterialError``."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"""SELECT material_id, topic_id, title, source, body, created_at
                        FROM {self._schema}.materials WHERE material_id = %s""",
                    (material_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo leer el material: {exc}") from exc
        if row is None:
            raise UnknownMaterialError(material_id)
        return _row_to_material(row)

    def list_for_topic(self, topic_id: str) -> list[Material]:
        """Materials of a topic, in the canonical order."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT material_id, topic_id, title, source, body, created_at
                    FROM {self._schema}.materials
                    WHERE topic_id = %s
                    ORDER BY created_at, material_id
                    """,
                    (topic_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo listar los materiales: {exc}") from exc
        return [_row_to_material(row) for row in rows]

    def exists(self, material_id: str) -> bool:
        """Whether a material with that id already exists."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT 1 FROM {self._schema}.materials WHERE material_id = %s",
                    (material_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo verificar el material: {exc}") from exc
        return row is not None


class PostgresQuestionStore:
    """``QuestionStore`` over PostgreSQL.

    Args:
        connect: zero-argument callable returning a context manager that
            yields an open ``psycopg.Connection`` (see
            :data:`store.postgres.ConnectionProvider`). Use :meth:`from_dsn`
            when a plain DSN is all that is needed.
        schema: schema the tables live in. Defaults to ``"learning"``.
    """

    def __init__(self, connect: ConnectionProvider, schema: str = DEFAULT_SCHEMA) -> None:
        self._connect_fn = connect
        self._schema = schema

    @classmethod
    def from_dsn(cls, dsn: str, schema: str = DEFAULT_SCHEMA) -> "PostgresQuestionStore":
        """Convenience constructor: opens a plain ``psycopg.connect(dsn)`` per operation."""
        return cls(lambda: psycopg.connect(dsn), schema=schema)

    def _connect(self):
        return _open_connection(self._connect_fn)

    def _insert(self, conn: psycopg.Connection, question: Question) -> None:
        try:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.questions
                    (question_id, topic_id, objective_id, stem, options,
                     correct_key, explanation, material_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    question.question_id,
                    question.topic_id,
                    question.objective_id,
                    question.stem,
                    json.dumps([list(pair) for pair in question.options]),
                    question.correct_key,
                    question.explanation,
                    question.material_id,
                    question.created_at,
                ),
            )
        except pg_errors.ForeignKeyViolation as exc:
            if exc.diag.constraint_name == _TOPIC_FK_CONSTRAINT:
                raise InvalidQuestionError(
                    f"question {question.question_id!r} topic_id {question.topic_id!r} "
                    f"no coincide con el topic_id del material {question.material_id!r}"
                ) from exc
            raise UnknownMaterialError(question.material_id) from exc

    def _check_no_duplicates(
        self, conn: psycopg.Connection, incoming: list[Question], exclude_material_id: str | None = None
    ) -> None:
        """Pre-checks the batch against already-stored ids, inside the same
        transaction as the writes that follow, so a duplicate is reported
        with its exact id rather than through the ``PRIMARY KEY``, which
        stays only as the backstop for a race with this check.

        ``exclude_material_id``, when given, excludes that material's own
        current questions - they are about to be replaced, not collided
        with (mirrors the memory backend's ``existing_elsewhere``).
        """
        ids = [q.question_id for q in incoming]
        where = "WHERE question_id = ANY(%s)"
        params: tuple = (ids,)
        if exclude_material_id is not None:
            where += " AND material_id != %s"
            params += (exclude_material_id,)
        rows = conn.execute(
            f"SELECT question_id FROM {self._schema}.questions {where}", params
        ).fetchall()
        existing = {row[0] for row in rows}
        reject_duplicate_ids(incoming, existing)

    def add_many(self, questions: Iterable[Question]) -> int:
        """Persists a batch of questions, atomically. See the Protocol docstring."""
        incoming = list(questions)
        try:
            with self._connect() as conn:
                self._check_no_duplicates(conn, incoming)
                for question in incoming:
                    self._insert(conn, question)
        except pg_errors.UniqueViolation as exc:
            raise DuplicateQuestionError(
                "duplicate question_id detected by the database"
            ) from exc
        except psycopg.Error as exc:
            raise StorageError(f"no se pudieron guardar las preguntas: {exc}") from exc
        return len(incoming)

    def get(self, question_id: str) -> Question:
        """Returns the question or raises ``UnknownQuestionError``."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT question_id, topic_id, objective_id, stem, options,
                           correct_key, explanation, material_id, created_at
                    FROM {self._schema}.questions WHERE question_id = %s
                    """,
                    (question_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo leer la pregunta: {exc}") from exc
        if row is None:
            raise UnknownQuestionError(question_id)
        return _row_to_question(row)

    def _select(self, where: str, params: tuple) -> list[Question]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT question_id, topic_id, objective_id, stem, options,
                           correct_key, explanation, material_id, created_at
                    FROM {self._schema}.questions
                    {where}
                    ORDER BY created_at, question_id
                    """,
                    params,
                ).fetchall()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo leer las preguntas: {exc}") from exc
        return [_row_to_question(row) for row in rows]

    def list_for_objective(self, objective_id: str) -> list[Question]:
        """Questions assessing an objective, in the canonical order."""
        return self._select("WHERE objective_id = %s", (objective_id,))

    def list_for_topic(self, topic_id: str) -> list[Question]:
        """Questions of a topic, in the canonical order."""
        return self._select("WHERE topic_id = %s", (topic_id,))

    def count(self, topic_id: str | None = None) -> int:
        """Number of questions, optionally scoped to a topic."""
        where = "WHERE topic_id = %s" if topic_id is not None else ""
        params = (topic_id,) if topic_id is not None else ()
        try:
            with self._connect() as conn:
                (total,) = conn.execute(
                    f"SELECT count(*) FROM {self._schema}.questions {where}", params
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo contar las preguntas: {exc}") from exc
        return total

    def exists(self, question_id: str) -> bool:
        """Whether a question with that id already exists."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT 1 FROM {self._schema}.questions WHERE question_id = %s",
                    (question_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo verificar la pregunta: {exc}") from exc
        return row is not None

    def _check_material_exists(self, conn: psycopg.Connection, material_id: str) -> None:
        row = conn.execute(
            f"SELECT 1 FROM {self._schema}.materials WHERE material_id = %s",
            (material_id,),
        ).fetchone()
        if row is None:
            raise UnknownMaterialError(material_id)

    def replace_for_material(self, material_id: str, questions: Iterable[Question]) -> int:
        """Atomically replaces the questions of ``material_id``.

        Delete and inserts share one connection and therefore one
        transaction: ``_open_connection`` commits on a clean exit and rolls
        back on any exception, so a failure partway through the inserts
        undoes the delete as well, leaving the old set exactly as it was
        (the same atomicity guarantee ``append`` has in ``store/postgres.py``).
        """
        incoming = list(questions)
        for question in incoming:
            if question.material_id != material_id:
                raise InvalidQuestionError(
                    f"question {question.question_id!r} no pertenece a "
                    f"material {material_id!r}"
                )
        try:
            with self._connect() as conn:
                self._check_material_exists(conn, material_id)
                self._check_no_duplicates(conn, incoming, exclude_material_id=material_id)
                conn.execute(
                    f"DELETE FROM {self._schema}.questions WHERE material_id = %s",
                    (material_id,),
                )
                for question in incoming:
                    self._insert(conn, question)
        except pg_errors.UniqueViolation as exc:
            raise DuplicateQuestionError(
                "duplicate question_id detected by the database"
            ) from exc
        except psycopg.Error as exc:
            raise StorageError(f"no se pudo reemplazar las preguntas: {exc}") from exc
        return len(incoming)


__all__ = ["PostgresMaterialStore", "PostgresQuestionStore"]
