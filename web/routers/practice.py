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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from content.errors import UnknownQuestionError
from core.errors import DuplicateAttemptError, UnknownObjectiveError, UnknownProfileError
from core.models import AttemptKind

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}/practice", tags=["practice"])


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
    """

    question_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    selected_key: str = Field(min_length=1)


class ObjectiveStateOut(BaseModel):
    """The objective's new state, deliberately without a streak or run field
    (SPEC I10) -- see ``core.models.ObjectiveState``."""

    level: str
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
        level=state.level.name,
        score=state.score,
        total_attempts=state.total_attempts,
        correct_attempts=state.correct_attempts,
        is_due=state.is_due,
        next_review_at=state.next_review_at,
    )


@router.get("/next", response_model=NextQuestionOut)
def next_question(
    topic_id: str, resources: Resources = Depends(get_resources)
) -> NextQuestionOut:
    """Picks the objective the engine says is most urgent, then a question for it.

    Order of preference, entirely the engine's: what is due (most overdue
    first), and only when nothing is due, what has never been practised
    (SPEC section 5.2). A topic the engine has nothing to say about, or an
    objective that is due but has no question in the store, fails with a
    named 404 rather than an empty success that would look like there is
    nothing left to study.
    """
    tracker = resources.tracker_for(topic_id)
    moment = resources.clock.now()
    try:
        due = tracker.get_due(moment, limit=1)
        objective_id = due[0].objective_id if due else None
        if objective_id is None:
            unstarted = tracker.get_unstarted(moment)
            objective_id = unstarted[0].objective_id if unstarted else None
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc
    if objective_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"nothing to study in topic {topic_id}: no objective is due or unstarted",
        )
    questions = [
        q for q in resources.questions.list_for_objective(objective_id) if q.topic_id == topic_id
    ]
    if not questions:
        raise HTTPException(
            status_code=404,
            detail=f"objective {objective_id} is due but has no questions in topic {topic_id}",
        )
    question = questions[0]
    return NextQuestionOut(
        topic_id=topic_id,
        objective_id=objective_id,
        question_id=question.question_id,
        stem=question.stem,
        options=[OptionOut(key=key, text=text) for key, text in question.options],
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
    state = tracker.get_state(question.objective_id, at)
    return AnswerOut(
        correct=correct,
        explanation=question.explanation,
        objective_id=question.objective_id,
        state=_to_state_out(state),
    )


__all__ = ["router"]
