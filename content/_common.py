"""Contract rules shared across content backends, the way ``store/_common.py``
houses medium-independent rules for the engine's backends.

Two integrity rules live here:

* **Ownership**: every ``Question.material_id`` must name a material that
  already exists. A question anchored to nothing can never be reached by
  ``replace_for_material``, the one operation designed to manage it, and
  keeps feeding the engine evidence that no regeneration will ever correct -
  the same failure shape as a ``correct_key`` absent from ``options``, one
  level up.
* **Topical consistency**: a question's ``topic_id`` must equal its
  material's. ``topic_id`` is derivable through the material; storing it a
  second time without an invariant defending it lets regeneration silently
  move a question to another topic.

The in-memory backend calls :func:`validate_ownership_and_topic` directly,
since it holds a Python mapping to check against. Postgres enforces both
rules structurally (a foreign key and a composite foreign key - see
``migrations/0002_content.sql``), so it does not call this function, but it
must map a violation of those constraints to the exact same exceptions raised
here: the two backends have to agree on WHICH exception a caller sees, not
merely that one is raised.

The batch duplicate-id check is shared for the same reason: both backends
need it, and having it copy-pasted twice is how it drifted on integrity in
the first place. The in-memory backend checks a Python container directly;
Postgres pre-checks the incoming ids against the store inside its own
transaction (see ``content/postgres.py``) and passes the result in here,
keeping its ``PRIMARY KEY`` as the backstop rather than the primary check.
"""

from __future__ import annotations

from typing import Container, Iterable, Mapping

from .errors import DuplicateQuestionError, InvalidQuestionError, UnknownMaterialError
from .models import Material, Question


def validate_ownership_and_topic(
    questions: Iterable[Question], materials: Mapping[str, Material]
) -> None:
    """Rejects a question whose ``material_id`` is unknown, or whose
    ``topic_id`` disagrees with that material's. Checked before any write, so
    a rejected batch leaves no trace.

    Args:
        questions: the incoming batch, not yet persisted.
        materials: a mapping from ``material_id`` to :class:`Material`,
            queried with ``.get`` - a plain ``dict`` works.

    Raises:
        UnknownMaterialError: ``question.material_id`` is not a key of
            ``materials``.
        InvalidQuestionError: the material exists but its ``topic_id``
            differs from the question's.
    """
    for question in questions:
        material = materials.get(question.material_id)
        if material is None:
            raise UnknownMaterialError(question.material_id)
        if question.topic_id != material.topic_id:
            raise InvalidQuestionError(
                f"question {question.question_id!r} topic_id {question.topic_id!r} "
                f"no coincide con el topic_id {material.topic_id!r} del material "
                f"{material.material_id!r}"
            )


def reject_duplicate_ids(incoming: list[Question], existing: Container[str]) -> None:
    """Rejects a batch with an internal or external duplicate ``question_id``,
    before any write happens, so a rejected batch leaves no trace.

    Args:
        incoming: the batch about to be written.
        existing: any container of already-registered ``question_id`` values
            (a ``dict``, a ``set``...) to check the batch against; only
            membership is queried.

    Raises:
        DuplicateQuestionError: with the offending ``question_id``, either
            because it is already in ``existing`` or repeated within
            ``incoming`` itself.
    """
    seen: set[str] = set()
    for question in incoming:
        if question.question_id in existing or question.question_id in seen:
            raise DuplicateQuestionError(question.question_id)
        seen.add(question.question_id)
