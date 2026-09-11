"""The data model of the content package.

Both structures are ``dataclass(frozen=True)`` and validate themselves in
``__post_init__``, exactly like :class:`core.models.Attempt`: a malformed
object cannot exist, let alone be persisted. In particular, a
:class:`Question` whose ``correct_key`` is not one of its ``options`` is
impossible to construct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidMaterialError, InvalidQuestionError

def _require_aware(value: datetime, name: str, error: type[Exception]) -> None:
    """Demands an aware ``datetime``, exactly like ``core.models._require_aware``."""
    if not isinstance(value, datetime):
        raise error(f"{name} debe ser datetime, no {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise error(f"{name} debe llevar zona horaria (aware)")

def _require_nonempty_str(value: object, name: str, error: type[Exception]) -> None:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{name} no puede estar vacío")

@dataclass(frozen=True)
class Material:
    """A piece of uploaded study material.

    **Immutable and append-only**, like :class:`core.models.Attempt`: no API
    modifies or deletes it (see :class:`content.storage.MaterialStore`).

    Attributes:
        material_id: unique, immutable identifier.
        topic_id: topic this material belongs to.
        title: human readable title.
        source: where it came from, e.g. a filename or URL.
        body: the material itself, as markdown text.
        created_at: when it was uploaded. Aware; supplied by the caller,
            never read from the system clock (SPEC I2's discipline).
    """

    material_id: str
    topic_id: str
    title: str
    source: str
    body: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("material_id", "topic_id", "title", "source", "body"):
            _require_nonempty_str(getattr(self, name), name, InvalidMaterialError)
        _require_aware(self.created_at, "created_at", InvalidMaterialError)

@dataclass(frozen=True)
class Question:
    """A question generated from a :class:`Material`.

    **Immutable**: an approved question is not edited in place, it is
    replaced (see :meth:`content.storage.QuestionStore.replace_for_material`).

    Attributes:
        question_id: unique, immutable identifier.
        topic_id: topic this question belongs to.
        objective_id: objective this question assesses.
        stem: the question text.
        options: the answer choices, an ordered tuple of ``(key, text)``
            pairs. Order is significant and preserved verbatim; at least two
            options are required and their keys must be unique.
        correct_key: the key, among ``options``, of the correct answer.
        explanation: why the correct answer is correct.
        material_id: the material this question was generated from.
        created_at: when it was generated. Aware.
    """

    question_id: str
    topic_id: str
    objective_id: str
    stem: str
    options: tuple[tuple[str, str], ...]
    correct_key: str
    explanation: str
    material_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("question_id", "topic_id", "objective_id", "stem", "explanation", "material_id"):
            _require_nonempty_str(getattr(self, name), name, InvalidQuestionError)
        _require_aware(self.created_at, "created_at", InvalidQuestionError)

        if not isinstance(self.options, tuple) or len(self.options) < 2:
            raise InvalidQuestionError("options debe tener al menos dos alternativas")
        keys: list[str] = []
        for pair in self.options:
            valid = (
                isinstance(pair, tuple)
                and len(pair) == 2
                and all(isinstance(part, str) and part.strip() for part in pair)
            )
            if not valid:
                raise InvalidQuestionError(f"cada opción debe ser (key, text) no vacío: {pair!r}")
            keys.append(pair[0])
        if len(set(keys)) != len(keys):
            raise InvalidQuestionError(f"claves de opciones repetidas: {keys!r}")
        _require_nonempty_str(self.correct_key, "correct_key", InvalidQuestionError)
        if self.correct_key not in keys:
            raise InvalidQuestionError(
                f"correct_key {self.correct_key!r} no está entre las opciones {keys!r}"
            )
