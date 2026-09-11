"""In-memory backend, the reference implementation of the content
``Protocol`` types, exactly as ``store/memory.py`` is for the engine. It
persists nothing across processes; it is the mirror a future Postgres
backend gets checked against.
"""

from __future__ import annotations

from typing import Iterable

from .errors import (
    DuplicateMaterialError,
    DuplicateQuestionError,
    InvalidQuestionError,
    UnknownMaterialError,
    UnknownQuestionError,
)
from .models import Material, Question

def _sort_materials(materials: Iterable[Material]) -> list[Material]:
    return sorted(materials, key=lambda m: (m.created_at, m.material_id))

def _sort_questions(questions: Iterable[Question]) -> list[Question]:
    return sorted(questions, key=lambda q: (q.created_at, q.question_id))

class InMemoryMaterialStore:
    """In-memory ``MaterialStore``. It only appends and reads.

    Note what is **not** here: no ``update``, no ``remove``. The absence is
    the guarantee.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, Material] = {}

    def add(self, material: Material) -> Material:
        """Persists a material. See ``content.storage.MaterialStore.add``."""
        if material.material_id in self._by_id:
            raise DuplicateMaterialError(material.material_id)
        self._by_id[material.material_id] = material
        return material

    def get(self, material_id: str) -> Material:
        """Returns the material or raises ``UnknownMaterialError``."""
        try:
            return self._by_id[material_id]
        except KeyError:
            raise UnknownMaterialError(material_id) from None

    def list_for_topic(self, topic_id: str) -> list[Material]:
        """Materials of a topic, in the canonical order."""
        return _sort_materials(m for m in self._by_id.values() if m.topic_id == topic_id)

    def exists(self, material_id: str) -> bool:
        """Whether a material with that id already exists."""
        return material_id in self._by_id

class InMemoryQuestionStore:
    """In-memory ``QuestionStore``."""

    def __init__(self) -> None:
        self._by_id: dict[str, Question] = {}

    def add_many(self, questions: Iterable[Question]) -> int:
        """Persists a batch of questions, atomically. See the Protocol docstring."""
        incoming = list(questions)
        _validate_batch(incoming, self._by_id)
        for question in incoming:
            self._by_id[question.question_id] = question
        return len(incoming)

    def get(self, question_id: str) -> Question:
        """Returns the question or raises ``UnknownQuestionError``."""
        try:
            return self._by_id[question_id]
        except KeyError:
            raise UnknownQuestionError(question_id) from None

    def list_for_objective(self, objective_id: str) -> list[Question]:
        """Questions assessing an objective, in the canonical order."""
        return _sort_questions(
            q for q in self._by_id.values() if q.objective_id == objective_id
        )

    def list_for_topic(self, topic_id: str) -> list[Question]:
        """Questions of a topic, in the canonical order."""
        return _sort_questions(q for q in self._by_id.values() if q.topic_id == topic_id)

    def count(self, topic_id: str | None = None) -> int:
        """Number of questions, optionally scoped to a topic."""
        if topic_id is None:
            return len(self._by_id)
        return sum(1 for q in self._by_id.values() if q.topic_id == topic_id)

    def exists(self, question_id: str) -> bool:
        """Whether a question with that id already exists."""
        return question_id in self._by_id

    def replace_for_material(
        self, material_id: str, questions: Iterable[Question]
    ) -> int:
        """Atomically replaces the questions of ``material_id``.

        Validated against a snapshot excluding the material's own current
        questions, before anything is mutated: a failure never touches
        ``self._by_id``, which is what leaves the old set intact.
        """
        incoming = list(questions)
        for question in incoming:
            if question.material_id != material_id:
                raise InvalidQuestionError(
                    f"question {question.question_id!r} no pertenece a "
                    f"material {material_id!r}"
                )
        existing_elsewhere = {
            qid: q for qid, q in self._by_id.items() if q.material_id != material_id
        }
        _validate_batch(incoming, existing_elsewhere)

        for question_id, question in list(self._by_id.items()):
            if question.material_id == material_id:
                del self._by_id[question_id]
        for question in incoming:
            self._by_id[question.question_id] = question
        return len(incoming)

def _validate_batch(incoming: list[Question], existing: dict[str, Question]) -> None:
    """Rejects a batch with an internal or external duplicate id, before any
    write happens, so a rejected batch leaves no trace."""
    seen: set[str] = set()
    for question in incoming:
        if question.question_id in existing or question.question_id in seen:
            raise DuplicateQuestionError(question.question_id)
        seen.add(question.question_id)
