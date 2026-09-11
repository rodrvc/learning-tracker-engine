"""The persistence interfaces of the content package.

Same spirit as ``core/storage.py``: these two ``Protocol`` types are the only
thing a caller needs to know about. The concrete backend of this delivery
lives in ``content/memory.py``; a ``postgres`` backend belongs here next,
against these same two Protocols.

Canonical read order (imposed on read, never on write, exactly like the
engine's ``AttemptStore``): every read below returns results sorted by
ascending ``created_at``, ties broken by id (``material_id`` or
``question_id``). Every backend must honour this order so that two backends
never disagree about it.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from .models import Material, Question

@runtime_checkable
class MaterialStore(Protocol):
    """Persistence of study material. It only appends and reads.

    Material is **append-only**, like ``Attempt``: there is no ``update`` and
    no ``delete`` method here. The absence is the guarantee: once uploaded, a
    material cannot be silently altered out from under the questions
    generated from it.

    ``add`` is atomic (:class:`~content.errors.StorageError` on failure) and
    rejects an existing ``material_id`` with
    :class:`~content.errors.DuplicateMaterialError`.
    """

    def add(self, material: Material) -> Material:
        """Persists a material and returns it as stored."""
        ...

    def get(self, material_id: str) -> Material:
        """Returns the material, or raises ``UnknownMaterialError``."""
        ...

    def list_for_topic(self, topic_id: str) -> list[Material]:
        """Materials of a topic, in the canonical order."""
        ...

    def exists(self, material_id: str) -> bool:
        """Whether a material with that id already exists."""
        ...

@runtime_checkable
class QuestionStore(Protocol):
    """Persistence of generated questions.

    Questions differ from attempts and from material in one deliberate way:
    regenerating from a material replaces that material's question set, via
    :meth:`replace_for_material`. Nothing else here mutates or deletes.

    ``add_many`` is atomic across the whole batch: either every question is
    written or none is, and a duplicate ``question_id`` (against the store or
    within the batch) raises :class:`~content.errors.DuplicateQuestionError`
    before anything is written. ``replace_for_material`` is atomic the same
    way: either the whole new set replaces the old one, or the old set is
    left completely untouched.
    """

    def add_many(self, questions: Iterable[Question]) -> int:
        """Persists a batch of questions. Returns how many were written."""
        ...

    def get(self, question_id: str) -> Question:
        """Returns the question, or raises ``UnknownQuestionError``."""
        ...

    def list_for_objective(self, objective_id: str) -> list[Question]:
        """Questions assessing an objective, in the canonical order."""
        ...

    def list_for_topic(self, topic_id: str) -> list[Question]:
        """Questions of a topic, in the canonical order."""
        ...

    def count(self, topic_id: str | None = None) -> int:
        """Number of questions, optionally scoped to a topic."""
        ...

    def exists(self, question_id: str) -> bool:
        """Whether a question with that id already exists."""
        ...

    def replace_for_material(self, material_id: str, questions: Iterable[Question]) -> int:
        """Atomically replaces every question generated from ``material_id``.

        The old questions of ``material_id`` disappear and ``questions``
        takes their place, or, if anything about the operation fails
        (a question not belonging to ``material_id``, an id already used
        under a different material, a storage failure), the old set is
        exactly as it was before the call. Returns how many were written.
        """
        ...
