"""Ingest router: let an external source register objectives and report verdicts.

**The gap this closes.** Every other write path into this engine goes through
its own multiple-choice quiz bank: ``POST .../practice/answer``
(``web/routers/practice.py``) requires a ``question_id`` from this engine's
own store and derives ``correct`` itself by comparing keys. A source that
grades something else -- free text, a written exercise, a spoken answer, a
simulated exam -- has no HTTP path in, even though the engine underneath is
subject-agnostic by design (``INTEGRATION.md``, the CLI's
``record --correct|--wrong``) and already accepts a caller-supplied verdict.

**Vocabulary**, the same rule as every other router: the product says
"topic", the engine says "profile" (``core.models.Profile``). Every
request/response model here says "topic"; every call into ``resources``
says "profile" or "objective", matching the engine's own words.

**Two routes, two engine calls already built for this exact shape:**

* ``POST /topics/{id}/objectives`` wraps ``ProfileStore.upsert_objectives``
  (``core/storage.py``), idempotent by design: registering the same
  objective twice is not an error, it updates in place.
* ``POST /topics/{id}/objectives/{objective_id}/attempts`` wraps
  ``LearningTracker.record_attempt`` (``core/tracker.py``) with exactly the
  shape an external verdict needs: a caller-supplied ``at`` and
  ``attempt_id``, and a ``correct`` flag taken as given rather than derived
  here.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from core.errors import (
    DuplicateAttemptError,
    InvalidAttemptError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.models import AttemptKind, Objective

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}/objectives", tags=["ingest"])


class AttemptKindName(str, Enum):
    """Mirrors ``core.models.AttemptKind`` by value, the same explicit-map
    pattern ``practice.py``'s ``LevelName`` and ``progress.py``'s copy use:
    a rename in ``core`` must break this module at the enum call, not a
    client in silence."""

    QUIZ = "quiz"
    EXERCISE = "exercise"
    LAB = "lab"
    EXAM_SIM = "exam_sim"
    SELF_REPORT = "self_report"


class ObjectiveIn(BaseModel):
    """One objective to register. Only ``objective_id`` and ``title`` are
    required (``core.models.Objective``, C-level fields); ``domain``,
    ``weight`` and ``tags`` are optional exactly as the engine has them."""

    objective_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    domain: str | None = None
    weight: float = 1.0
    tags: tuple[str, ...] = ()


class ObjectivesIn(BaseModel):
    """Body to register objectives on a topic."""

    objectives: list[ObjectiveIn] = Field(min_length=1)


class ObjectivesOut(BaseModel):
    """How many objectives were written. ``upsert_objectives`` is idempotent:
    registering the same objective again is not an error, it counts as
    written again, updated in place."""

    written: int


class AttemptIn(BaseModel):
    """An external source's verdict on one objective.

    ``correct`` is taken as given: this router never derives it, unlike
    ``practice.py``'s quiz answer, because the grading already happened
    outside this engine.

    ``at`` is caller-supplied and required, typed ``AwareDatetime`` so a
    naive value is rejected with 422 rather than silently assumed to be UTC
    -- the guard ``practice.py``'s ``AnswerIn`` docstring asks for, applied
    here because this is the first client that actually supplies its own
    time (SPEC I2: the engine never fabricates ``at`` itself).

    ``attempt_id`` is caller-supplied, not generated here, so a retried
    request carries the same id and ``DuplicateAttemptError`` (SPEC C9)
    rejects the retry instead of recording it twice.
    """

    correct: bool
    at: AwareDatetime
    kind: AttemptKindName
    note: str | None = None
    attempt_id: str = Field(min_length=1)


class AttemptOut(BaseModel):
    """The attempt exactly as persisted."""

    attempt_id: str
    objective_id: str
    at: AwareDatetime
    correct: bool
    kind: AttemptKindName
    note: str | None


def _to_objective(body: ObjectiveIn) -> Objective:
    return Objective(
        objective_id=body.objective_id,
        title=body.title,
        domain=body.domain,
        weight=body.weight,
        tags=body.tags,
    )


@router.post("", response_model=ObjectivesOut, status_code=201)
def register_objectives(
    topic_id: str, body: ObjectivesIn, resources: Resources = Depends(get_resources)
) -> ObjectivesOut:
    """Registers objectives on a topic, without going through material
    generation.

    404, naming the topic, when it does not exist: ``upsert_objectives``
    does not create the topic itself, matching how every other route here
    treats an unknown topic.

    Idempotent by design (``ProfileStore.upsert_objectives``): calling this
    twice with the same objectives is not an error, it upserts in place, so
    a source can register its full objective set on every run without
    tracking what it already sent.
    """
    try:
        resources.profiles.get_profile(topic_id)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc
    written = resources.profiles.upsert_objectives(
        topic_id, [_to_objective(o) for o in body.objectives]
    )
    return ObjectivesOut(written=written)


@router.post("/{objective_id}/attempts", response_model=AttemptOut, status_code=201)
def record_attempt(
    topic_id: str,
    objective_id: str,
    body: AttemptIn,
    resources: Resources = Depends(get_resources),
) -> AttemptOut:
    """Records an external source's verdict as one attempt.

    This is ``LearningTracker.record_attempt`` (SPEC section 9.4) reached
    directly over HTTP: no question lookup, no derived ``correct``, because
    the caller already graded whatever it graded. It does not touch how
    levels are computed (``core/leveling.py``) or the quiz path in
    ``practice.py``; it is a second door into the same append-only history.
    """
    tracker = resources.tracker_for(topic_id)
    try:
        attempt = tracker.record_attempt(
            objective_id=objective_id,
            correct=body.correct,
            at=body.at,
            kind=AttemptKind(body.kind.value),
            note=body.note,
            attempt_id=body.attempt_id,
        )
    except DuplicateAttemptError as exc:
        raise HTTPException(
            status_code=409, detail=f"attempt already recorded: {body.attempt_id}"
        ) from exc
    except (UnknownProfileError, UnknownObjectiveError) as exc:
        raise HTTPException(
            status_code=404,
            detail=f"unknown topic or objective: {topic_id}/{objective_id}",
        ) from exc
    except InvalidAttemptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AttemptOut(
        attempt_id=attempt.attempt_id,
        objective_id=attempt.objective_id,
        at=attempt.at,
        correct=attempt.correct,
        kind=AttemptKindName(attempt.kind.value),
        note=attempt.note,
    )


__all__ = ["router"]
