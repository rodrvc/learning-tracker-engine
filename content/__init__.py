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
"""

from __future__ import annotations

from .memory import InMemoryMaterialStore, InMemoryQuestionStore

__all__ = ["InMemoryMaterialStore", "InMemoryQuestionStore"]
