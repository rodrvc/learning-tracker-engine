"""Study material and generated questions.

This package is where uploaded study material and the questions generated
from it live. It follows the same discipline as ``core/`` (frozen models that
validate themselves, ``Protocol`` storage interfaces, backends checked
against a shared test suite) without the engine ever knowing this package
exists: nothing in ``core/`` imports from here.

Concrete implementations, against the ``Protocol`` types of
``content.storage``:

* :func:`new_memory_stores` returns a matched ``MaterialStore``/
  ``QuestionStore`` pair sharing one state, which is what lets the question
  store enforce that every ``material_id`` it is given actually exists (see
  ``content/_common.py``). This is the supported way to build the in-memory
  backend; ``InMemoryMaterialStore`` / ``InMemoryQuestionStore`` are exported
  for typing, not for standalone construction.
* ``content.postgres.PostgresMaterialStore`` / ``PostgresQuestionStore``,
  imported on demand below, exactly like ``store/__init__.py`` does for the
  engine's Postgres backend: environments without the ``postgres`` extra can
  still use the memory backend. The two Postgres stores already share one
  connection provider and schema, so they are naturally a matched pair too.
"""

from __future__ import annotations

from .memory import InMemoryMaterialStore, InMemoryQuestionStore, new_memory_stores

_POSTGRES_NAMES = ("PostgresMaterialStore", "PostgresQuestionStore")


def __getattr__(name: str):
    if name in _POSTGRES_NAMES:
        try:
            from . import postgres
        except ImportError as exc:  # pragma: no cover - needs psycopg absent
            raise ImportError(
                f"{name} requires the psycopg driver: install the "
                "'postgres' extra (pip install -e '.[postgres]')"
            ) from exc
        return getattr(postgres, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "InMemoryMaterialStore",
    "InMemoryQuestionStore",
    "new_memory_stores",
    "PostgresMaterialStore",
    "PostgresQuestionStore",
]
