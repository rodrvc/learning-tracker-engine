"""In-memory backend, the reference implementation of the content
``Protocol`` types, exactly as ``store/memory.py`` is for the engine. It
persists nothing across processes; it is the mirror the Postgres backend
gets checked against.

``InMemoryMaterialStore`` and ``InMemoryQuestionStore`` are two Protocols
over ONE backing store, not two unrelated dictionaries: a
``QuestionStore`` has to see the same materials a ``MaterialStore`` holds to
enforce ownership (SPEC-style, see ``content/_common.py``), so the two
classes share one :class:`_ContentState` instance. :func:`new_memory_stores`
is the supported way to obtain a matched pair; constructing either class on
its own state, unpaired with the other, produces a ``QuestionStore`` that can
never see any material and would reject every question as an orphan.
"""

from __future__ import annotations

from typing import Iterable

from ._common import reject_duplicate_ids, validate_ownership_and_topic
from .errors import (
    DuplicateMaterialError,
    InvalidQuestionError,
    UnknownMaterialError,
    UnknownQuestionError,
)
from .models import Material, Question


def _sort_materials(materials: Iterable[Material]) -> list[Material]:
    return sorted(materials, key=lambda m: (m.created_at, m.material_id))


def _sort_questions(questions: Iterable[Question]) -> list[Question]:
    return sorted(questions, key=lambda q: (q.created_at, q.question_id))


class _ContentState:
    """The shared state backing one matched ``MaterialStore``/``QuestionStore``
    pair. Not part of the public interface - see :func:`new_memory_stores`."""

    def __init__(self) -> None:
        self.materials: dict[str, Material] = {}
        self.questions: dict[str, Question] = {}


def new_memory_stores() -> tuple["InMemoryMaterialStore", "InMemoryQuestionStore"]:
    """Builds a matched ``(MaterialStore, QuestionStore)`` pair sharing one
    backing store. This is the supported way to construct the in-memory
    backend: the two objects returned share the same materials, so the
    question store can enforce that every ``material_id`` it is given
    actually exists.
    """
    state = _ContentState()
    return InMemoryMaterialStore(state), InMemoryQuestionStore(state)


class InMemoryMaterialStore:
    """In-memory ``MaterialStore``. It only appends and reads.

    Note what is **not** here: no ``update``, no ``remove``. The absence is
    the guarantee. Construct through :func:`new_memory_stores`, not directly.
    """

    def __init__(self, state: _ContentState) -> None:
        self._state = state

    def add(self, material: Material) -> Material:
        """Persists a material. See ``content.storage.MaterialStore.add``."""
        if material.material_id in self._state.materials:
            raise DuplicateMaterialError(material.material_id)
        self._state.materials[material.material_id] = material
        return material

    def get(self, material_id: str) -> Material:
        """Returns the material or raises ``UnknownMaterialError``."""
        try:
            return self._state.materials[material_id]
        except KeyError:
            raise UnknownMaterialError(material_id) from None

    def list_for_topic(self, topic_id: str) -> list[Material]:
        """Materials of a topic, in the canonical order."""
        return _sort_materials(
            m for m in self._state.materials.values() if m.topic_id == topic_id
        )

    def exists(self, material_id: str) -> bool:
        """Whether a material with that id already exists."""
        return material_id in self._state.materials


class InMemoryQuestionStore:
    """In-memory ``QuestionStore``. Construct through :func:`new_memory_stores`,
    not directly."""

    def __init__(self, state: _ContentState) -> None:
        self._state = state

    def add_many(self, questions: Iterable[Question]) -> int:
        """Persists a batch of questions, atomically. See the Protocol docstring."""
        incoming = list(questions)
        reject_duplicate_ids(incoming, self._state.questions)
        validate_ownership_and_topic(incoming, self._state.materials)
        for question in incoming:
            self._state.questions[question.question_id] = question
        return len(incoming)

    def get(self, question_id: str) -> Question:
        """Returns the question or raises ``UnknownQuestionError``."""
        try:
            return self._state.questions[question_id]
        except KeyError:
            raise UnknownQuestionError(question_id) from None

    def list_for_objective(self, objective_id: str) -> list[Question]:
        """Questions assessing an objective, in the canonical order."""
        return _sort_questions(
            q for q in self._state.questions.values() if q.objective_id == objective_id
        )

    def list_for_topic(self, topic_id: str) -> list[Question]:
        """Questions of a topic, in the canonical order."""
        return _sort_questions(
            q for q in self._state.questions.values() if q.topic_id == topic_id
        )

    def count(self, topic_id: str | None = None) -> int:
        """Number of questions, optionally scoped to a topic."""
        if topic_id is None:
            return len(self._state.questions)
        return sum(1 for q in self._state.questions.values() if q.topic_id == topic_id)

    def exists(self, question_id: str) -> bool:
        """Whether a question with that id already exists."""
        return question_id in self._state.questions

    def replace_for_material(self, material_id: str, questions: Iterable[Question]) -> int:
        """Atomically replaces the questions of ``material_id``.

        Validated against a snapshot excluding the material's own current
        questions, before anything is mutated: a failure never touches
        ``self._state.questions``, which is what leaves the old set intact.
        """
        if material_id not in self._state.materials:
            raise UnknownMaterialError(material_id)
        incoming = list(questions)
        for question in incoming:
            if question.material_id != material_id:
                raise InvalidQuestionError(
                    f"question {question.question_id!r} no pertenece a "
                    f"material {material_id!r}"
                )
        existing_elsewhere = {
            qid: q for qid, q in self._state.questions.items() if q.material_id != material_id
        }
        reject_duplicate_ids(incoming, existing_elsewhere)
        validate_ownership_and_topic(incoming, self._state.materials)

        for question_id, question in list(self._state.questions.items()):
            if question.material_id == material_id:
                del self._state.questions[question_id]
        for question in incoming:
            self._state.questions[question.question_id] = question
        return len(incoming)
