"""Practice router: what to study next, and grading the answer.

**Vocabulary**, same rule as ``topics.py``: the product says "topic", the
engine says "profile" (``core.models.Profile``). This module keeps to
"topic" in every request/response model and translates only at the call
into ``resources.tracker_for(topic_id)``.

**Ordering is the engine's job, not this layer's.** Which objective comes up
next is decided entirely by ``LearningTracker.get_due`` (most overdue first)
and, when nothing is due, ``LearningTracker.get_unstarted``. This router only
picks a question for the objective the engine names; it never ranks
objectives itself (SPEC section 9.4, section 5.2).

**The solution never reaches the browser before the question is answered.**
``NextQuestionOut`` carries no ``correct_key`` and no ``explanation`` on
purpose (see ``tests/test_web.py`` for the assertion that pins this).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from content.errors import UnknownQuestionError
from content.models import Question
from core.errors import (
    DuplicateAttemptError,
    InvalidAttemptError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.models import AttemptKind

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}/practice", tags=["practice"])


class LevelName(str, Enum):
    """Mirrors ``core.models.Level`` by name (see ``web.routers.progress``'s
    own copy of this pattern).

    Serializing ``state.level.name`` as a bare ``str`` would publish a Python
    enum member's identifier as the HTTP contract: renaming it in ``core``
    would silently change every client's response with no signal here. This
    enum is the explicit map, so a rename in ``core`` breaks this module at
    the ``LevelName(...)`` call instead of breaking clients in silence.
    """

    UNASSESSED = "UNASSESSED"
    WEAK = "WEAK"
    LEARNING = "LEARNING"
    COMPETENT = "COMPETENT"
    MASTERED = "MASTERED"


class OptionOut(BaseModel):
    """One answer choice, with no hint of which one is correct."""

    key: str
    text: str


class NextQuestionOut(BaseModel):
    """The question to answer next. No ``correct_key``, no ``explanation``."""

    topic_id: str
    objective_id: str
    question_id: str
    stem: str
    options: list[OptionOut]


class AnswerIn(BaseModel):
    """Body to answer a question.

    ``attempt_id`` is supplied by the caller, not generated here, so that a
    retried request carries the same id and the engine's own duplicate
    detection (SPEC C9) rejects the retry instead of recording it twice.

    There is deliberately no ``at`` field: the moment of the attempt is taken
    from the server's injected clock (``resources.clock``, SPEC I2), never
    from the caller. If a client-supplied time is ever added -- the likely
    path being a queued or offline answer replayed with its original time --
    it must be typed as an aware ``datetime`` (e.g. pydantic's
    ``AwareDatetime``, as ``web.routers.progress`` already uses) that
    *rejects* a naive value rather than silently assuming UTC for it: a
    historical answer's meaning must not depend on server configuration.
    """

    question_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    selected_key: str = Field(min_length=1)


class ObjectiveStateOut(BaseModel):
    """The objective's new state, deliberately without a streak or run field
    (SPEC I10) -- see ``core.models.ObjectiveState``."""

    level: LevelName
    score: float
    total_attempts: int
    correct_attempts: int
    is_due: bool
    next_review_at: datetime | None


class AnswerOut(BaseModel):
    """Result of grading one answer."""

    correct: bool
    explanation: str
    objective_id: str
    state: ObjectiveStateOut


def _to_state_out(state) -> ObjectiveStateOut:
    return ObjectiveStateOut(
        level=LevelName(state.level.name),
        score=state.score,
        total_attempts=state.total_attempts,
        correct_attempts=state.correct_attempts,
        is_due=state.is_due,
        next_review_at=state.next_review_at,
    )


def _questions_for(resources: Resources, topic_id: str, objective_id: str) -> list[Question]:
    return [
        q for q in resources.questions.list_for_objective(objective_id) if q.topic_id == topic_id
    ]


def _pick_question(questions: list[Question], total_attempts: int) -> Question:
    """Rotates through an objective's questions as attempts accumulate.

    ``total_attempts`` only grows (SPEC: attempts are append-only), so
    ``total_attempts % len(questions)`` advances by one on every recorded
    attempt and cycles back deterministically -- no randomness, so the pick
    is reproducible from the state alone, and testable without mocking one.
    A fixed "first in canonical order" pick would instead serve the very
    same question forever until the level moved, which turns spaced
    repetition into "do you remember this one card", not the concept.
    """
    return questions[total_attempts % len(questions)]


@router.get("/next", response_model=NextQuestionOut)
def next_question(
    topic_id: str, resources: Resources = Depends(get_resources)
) -> NextQuestionOut:
    """Picks the objective the engine says is most urgent, then a question for it.

    Order of preference, entirely the engine's: what is due (most overdue
    first), and only when nothing is due, what has never been practised
    (SPEC section 5.2). Within that order, this walks every candidate
    objective until it finds one with an available question: stopping at the
    first (most urgent) candidate regardless of content coverage would brick
    the endpoint the moment that one objective has no question, even though
    the store has questions for other objectives (this repo currently has
    questions for only a fraction of its objectives -- see ``HANDOFF.md``).
    The engine still decides the order; this loop only keeps walking it
    instead of discarding it after one element.

    A topic the engine has nothing to say about, or one where *no* due or
    unstarted objective has a question, fails with a named 404 rather than
    an empty success that would look like there is nothing left to study.
    """
    tracker = resources.tracker_for(topic_id)
    moment = resources.clock.now()
    try:
        due = tracker.get_due(moment)
        unstarted = tracker.get_unstarted(moment)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc

    for state in (*due, *unstarted):
        questions = _questions_for(resources, topic_id, state.objective_id)
        if questions:
            question = _pick_question(questions, state.total_attempts)
            return NextQuestionOut(
                topic_id=topic_id,
                objective_id=state.objective_id,
                question_id=question.question_id,
                stem=question.stem,
                options=[OptionOut(key=key, text=text) for key, text in question.options],
            )

    if due or unstarted:
        candidates = ", ".join(s.objective_id for s in (*due, *unstarted))
        raise HTTPException(
            status_code=404,
            detail=(
                f"topic {topic_id} has no question for any due or unstarted "
                f"objective: {candidates}"
            ),
        )
    raise HTTPException(
        status_code=404,
        detail=f"nothing to study in topic {topic_id}: no objective is due or unstarted",
    )


@router.post("/answer", response_model=AnswerOut)
def answer_question(
    topic_id: str, body: AnswerIn, resources: Resources = Depends(get_resources)
) -> AnswerOut:
    """Grades one answer and records exactly one attempt for it.

    One question, one recorded attempt: this handler calls
    ``record_attempt`` exactly once, never grouping several answers into one
    call, so the engine's recency weighting sees each answer separately
    (SPEC section 2.2 step 3). If recording fails, the exception propagates
    to the application's ``StorageError`` handler: the caller learns the
    answer was graded but not saved, rather than getting a silent success
    (SPEC I8).
    """
    try:
        question = resources.questions.get(body.question_id)
    except UnknownQuestionError as exc:
        raise HTTPException(
            status_code=404, detail=f"unknown question: {body.question_id}"
        ) from exc
    if question.topic_id != topic_id:
        raise HTTPException(
            status_code=404, detail=f"unknown question: {body.question_id}"
        )
    correct = body.selected_key == question.correct_key
    tracker = resources.tracker_for(topic_id)
    at = resources.clock.now()
    try:
        tracker.record_attempt(
            objective_id=question.objective_id,
            correct=correct,
            at=at,
            kind=AttemptKind.QUIZ,
            note=body.selected_key,
            attempt_id=body.attempt_id,
        )
    except DuplicateAttemptError as exc:
        raise HTTPException(
            status_code=409, detail=f"attempt already recorded: {body.attempt_id}"
        ) from exc
    except (UnknownProfileError, UnknownObjectiveError) as exc:
        raise HTTPException(
            status_code=404,
            detail=f"unknown topic or objective for question {body.question_id}",
        ) from exc
    except InvalidAttemptError as exc:
        # Unreachable today -- every field ``record_attempt`` validates here
        # (``at``, ``correct``, ``kind``) is built by this handler, not the
        # caller. Caught anyway for the day a client-supplied field (see
        # ``AnswerIn``'s docstring) reaches this call: without this, that
        # would surface as an unhandled 500 instead of a 400.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = tracker.get_state(question.objective_id, at)
    return AnswerOut(
        correct=correct,
        explanation=question.explanation,
        objective_id=question.objective_id,
        state=_to_state_out(state),
    )


__all__ = ["router"]
