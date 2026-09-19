"""Ingest router: let an external source register objectives and report verdicts.

**The gap this closes.** Every other write path into this engine goes through
its own multiple-choice quiz bank: ``POST .../practice/answer``
(``web/routers/practice.py``) requires a ``question_id`` from this engine's
own store and derives ``correct`` itself by comparing keys. A source that
grades something else -- free text, a written exercise, a spoken answer, a
simulated exam -- has no HTTP path in, even though the engine underneath is
subject-agnostic by design (``INTEGRATION.md``) and already accepts a
caller-supplied verdict via the CLI's ``record --correct|--wrong``.

**Vocabulary**, the same rule as every other router: "topic" in every
request/response model, "profile"/"objective" in every call into
``resources``, matching the engine's own words.

**Two routes:**

* ``POST /topics/{id}/objectives`` wraps ``ProfileStore.upsert_objectives``
  (``core/storage.py``), idempotent by design. That store call is a full
  replace, not a merge, so this router merges a partial payload onto what
  is already stored before calling it -- see ``_merge_objective``.
* ``POST /topics/{id}/objectives/{objective_id}/attempts`` wraps
  ``LearningTracker.record_attempt`` (``core/tracker.py``): a
  caller-supplied ``at`` and ``attempt_id``, ``correct`` taken as given
  rather than derived here.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from core.errors import (
    DuplicateAttemptError,
    InvalidAttemptError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.models import AttemptKind, Objective

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}/objectives", tags=["ingest"])

#: Largest batch accepted in one registration call. ``upsert_objectives``
#: issues one sequential ``INSERT`` per objective inside a single pooled
#: connection (``store/postgres.py``): an unbounded batch holds that
#: connection for the whole loop against ``POOL_MAX_SIZE=10`` (``web/deps
#: .py``) and a five second checkout timeout -- a self-inflicted 503 for
#: every other request waiting on the pool.
MAX_OBJECTIVES_PER_CALL = 500

#: Largest ``attempt_id``/``note`` accepted. Attempts are append-only with
#: no delete path (SPEC I1): an oversized value here is permanent.
MAX_ATTEMPT_ID_CHARS = 200
MAX_NOTE_CHARS = 2_000


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
    ``weight`` and ``tags`` are optional exactly as the engine has them.
    ``extra="forbid"`` fails a stray field loudly instead of discarding it
    silently. Unset ``domain``/``weight``/``tags`` are **not** the same as
    sending their default: :func:`_merge_objective` reads
    ``model_fields_set`` to tell the two apart and merge a partial payload
    onto what is already stored.
    """

    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    domain: str | None = Field(default=None, max_length=200)
    weight: float = Field(default=1.0, ge=0)
    tags: tuple[str, ...] = ()


class ObjectivesIn(BaseModel):
    """Body to register objectives on a topic."""

    model_config = ConfigDict(extra="forbid")

    objectives: list[ObjectiveIn] = Field(min_length=1, max_length=MAX_OBJECTIVES_PER_CALL)


class ObjectivesOut(BaseModel):
    """How many objectives were written. ``upsert_objectives`` is idempotent:
    registering the same objective again is not an error, it counts as
    written again, updated in place."""

    written: int


class AttemptIn(BaseModel):
    """An external source's verdict on one objective.

    ``correct`` is taken as given: unlike ``practice.py``'s quiz answer,
    this router never derives it -- the grading already happened outside
    this engine.

    ``at`` is caller-supplied and required, typed ``AwareDatetime`` so a
    naive value is rejected with 422 rather than silently assumed to be UTC
    -- the guard ``practice.py``'s ``AnswerIn`` docstring asks for (SPEC I2:
    the engine never fabricates ``at`` itself).

    ``attempt_id`` is caller-supplied, so a retried request carries the same
    id and ``DuplicateAttemptError`` (SPEC C9) rejects the retry. It is a
    single primary key shared by every topic (``store/postgres.py``'s
    ``exists``, "in any profile"), not scoped to this one -- see
    ``INTEGRATION.md`` for why it must be a UUID, not a local counter.

    ``confidence`` is exposed here (unlike the quiz answer) because a
    source grading free text has a self-assessment worth recording
    (``core.models.Attempt``); ``extra="forbid"`` is what stops any other
    field vanishing silently if the caller sends it anyway.
    """

    model_config = ConfigDict(extra="forbid")

    correct: bool
    at: AwareDatetime
    kind: AttemptKindName
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    attempt_id: str = Field(min_length=1, max_length=MAX_ATTEMPT_ID_CHARS)


class AttemptOut(BaseModel):
    """The attempt exactly as persisted."""

    attempt_id: str
    objective_id: str
    at: AwareDatetime
    correct: bool
    kind: AttemptKindName
    confidence: float | None
    note: str | None


def _merge_objective(body: ObjectiveIn, existing: Objective | None) -> Objective:
    """Builds the ``Objective`` to write, merging onto what is already stored.

    ``upsert_objectives`` (``core/storage.py``, ``store/postgres.py``) is a
    full replace, not a merge: every column is overwritten with whatever
    this call passes, including this model's own defaults for a field the
    caller never sent. Left uncorrected, a source that re-registers only
    ``objective_id`` and ``title`` on every run -- the safe-to-repeat usage
    this router documents -- would silently erase ``domain``/``weight``/
    ``tags`` on an objective that already had them. The store's own
    contract stays a full replace (correct for a caller that always sends
    the full record, e.g. material generation); this router is the one
    that promises a partial payload is safe, so the merge happens here, via
    ``body.model_fields_set`` -- which fields the client actually sent.

    ``existing`` is ``None`` for a brand new ``objective_id``: nothing to
    merge onto, so an unsent field takes ``ObjectiveIn``'s own default.
    """
    fallback = existing.domain if existing else None
    domain = body.domain if "domain" in body.model_fields_set else fallback
    weight = body.weight if "weight" in body.model_fields_set else (
        existing.weight if existing else 1.0
    )
    tags = body.tags if "tags" in body.model_fields_set else (existing.tags if existing else ())
    return Objective(
        objective_id=body.objective_id,
        title=body.title,
        domain=domain,
        weight=weight,
        tags=tags,
    )


@router.post("", response_model=ObjectivesOut, status_code=201)
def register_objectives(
    topic_id: str, body: ObjectivesIn, resources: Resources = Depends(get_resources)
) -> ObjectivesOut:
    """Registers objectives on a topic, without going through material
    generation.

    404, naming the topic, when it does not exist: ``upsert_objectives``
    does not create the topic itself, matching every other route here.

    Idempotent and safe to repeat: a caller may send only ``objective_id``
    and ``title`` on a later call, and an unsent ``domain``/``weight``/
    ``tags`` is merged onto whatever is already stored rather than erased
    (:func:`_merge_objective`), so a source can register its full objective
    set on every run without tracking what it already sent.
    """
    try:
        resources.profiles.get_profile(topic_id)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc
    existing = resources.profiles.list_objectives(topic_id)
    existing_by_id = {objective.objective_id: objective for objective in existing}
    merged = [
        _merge_objective(o, existing_by_id.get(o.objective_id)) for o in body.objectives
    ]
    written = resources.profiles.upsert_objectives(topic_id, merged)
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
            confidence=body.confidence,
            note=body.note,
            attempt_id=body.attempt_id,
        )
    except DuplicateAttemptError as exc:
        # attempt_id is one primary key shared by every topic and objective
        # (store/postgres.py's exists(): "in any profile"), not scoped to
        # this one. A message that says "attempt already recorded" without
        # qualification reads as "my retry landed, I can stop" -- true only
        # when the id collided with this exact request. A different caller,
        # topic or objective reusing the same id is a genuinely new verdict
        # that was just discarded, and the message must not say it was saved.
        raise HTTPException(
            status_code=409,
            detail=(
                f"attempt_id already taken: {body.attempt_id} "
                "(attempt_id is unique across every topic, not just this one)"
            ),
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
        confidence=attempt.confidence,
        note=attempt.note,
    )


__all__ = ["router"]
