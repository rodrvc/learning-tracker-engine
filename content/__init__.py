"""Study material and generated questions.

This package is where uploaded study material and the questions generated
from it live. It follows the same discipline as ``core/`` (frozen models that
validate themselves, ``Protocol`` storage interfaces, backends checked
against a shared test suite) without the engine ever knowing this package
exists: nothing in ``core/`` imports from here.

Scope of this delivery (ACU-245): only the models, the ``Protocol`` types and
the in-memory reference backend. A ``postgres`` backend belongs here next,
following the seam of ``store/postgres.py`` - it did not fit this change's
line budget alongside a well-documented memory backend and test suite.

Use :func:`new_memory_stores` to get a working in-memory backend: it returns
a matched ``MaterialStore``/``QuestionStore`` pair sharing one state, which is
what lets the question store enforce that every ``material_id`` it is given
actually exists (see ``content/_common.py``).
"""

from __future__ import annotations

from .memory import InMemoryMaterialStore, InMemoryQuestionStore, new_memory_stores

__all__ = ["InMemoryMaterialStore", "InMemoryQuestionStore", "new_memory_stores"]
