"""Practice router: what to study next, and grading the answer.

**Vocabulary**, same rule as ``topics.py``: the product says "topic", the
engine says "profile" (``core.models.Profile``). This module keeps to
"topic" in every request/response model and translates only at the call
into ``resources.tracker_for(topic_id)``.

**Ordering is the engine's job, not this layer's.** Which objective comes up
next is decided entirely by ``LearningTracker.get_due`` (most overdue first)
and, when nothing is due, ``LearningTracker.get_unstarted``. This router only
picks a question for the objective the engine names; it never ranks
objectives itself (SPEC section 9.4, section 5.2). A scope (``domain``,
``objective_id``) narrows *which* candidates are considered, never the order
they come in: the engine's list is filtered, never rebuilt or re-sorted.

**The solution never reaches the browser before the question is answered.**
``NextQuestionOut`` carries no ``correct_key`` and no ``explanation`` on
purpose (see ``tests/test_web.py`` for the assertion that pins this).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
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


def _count_of(noun: str, values: list[str]) -> str | None:
    """``2 domains``, ``1 objective``, or ``None`` for none of them."""
    if not values:
        return None
    return f"{len(values)} {noun}{'s' if len(values) > 1 else ''}"


def _describe_scope(domains: list[str], objective_ids: list[str]) -> str | None:
    """How a scope is named in a 404 detail, or ``None`` when unscoped.

    The wording is part of the contract: ``webui/js/format.js`` tells the
    practice view's empty states apart by matching on these details (see
    ``tests/test_web.py``, where the unscoped three are pinned verbatim).
    Every scoped detail is built from this one function so that the scope
    reads the same way in all three of them, and so that a reword touches
    one place rather than three.

    A selection of exactly one thing keeps the wording it had before
    selections existed (``domain D1``, ``objective D3.2.a``) down to the
    byte, because that is the shape the front end's own single-scope
    messages match on. Anything larger is named by *how many* of each it
    holds rather than by listing them: a selection may hold sixteen
    objectives, and a detail that spelled them all out would be a paragraph
    where a person wanted a reason (issue #62).
    """
    if not domains and len(objective_ids) == 1:
        return f"objective {objective_ids[0]}"
    if not objective_ids and len(domains) == 1:
        return f"domain {domains[0]}"
    parts = [
        part
        for part in (_count_of("domain", domains), _count_of("objective", objective_ids))
        if part is not None
    ]
    return " and ".join(parts) if parts else None


def _objectives_in_scope(
    resources: Resources, topic_id: str, domains: list[str], objective_ids: list[str]
) -> set[str]:
    """The objective ids a scope selects, read from the topic's own objectives.

    A scope is a *set*: the domains and the objective ids the caller sent are
    resolved independently and unioned, so asking for two units plus one
    loose objective selects everything those three name, with no precedence
    between them (issue #62). Union, not intersection: the caller ticked
    three boxes meaning "any of these", and an intersection of a domain with
    an objective outside it would answer with nothing at all.

    ``domain`` is free text on the objective (SPEC section 1.2), so it is
    matched exactly and never normalised: a case-folding or trimming rule
    invented here would be a second meaning of "same domain", living in the
    web layer, that nothing else in the system shares.

    The comparison is against the *stored* objectives rather than against
    the states the engine returned, because a scope that matches no
    objective at all and a scope whose objectives are simply neither due nor
    unstarted are different answers to the caller, and only the profile can
    tell them apart.
    """
    profile = resources.profiles.get_profile(topic_id)
    wanted_domains = set(domains)
    selected = {
        objective_id for objective_id in objective_ids if objective_id in profile.objectives
    }
    selected |= {
        candidate.objective_id
        for candidate in profile.objectives.values()
        if candidate.domain in wanted_domains
    }
    return selected


@router.get("/next", response_model=NextQuestionOut)
def next_question(
    topic_id: str,
    domain: list[str] | None = Query(default=None),
    objective_id: list[str] | None = Query(default=None),
    resources: Resources = Depends(get_resources),
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

    **Scope (issue #48, widened to a selection in issue #62).** ``domain``
    and ``objective_id`` narrow the walk to the objectives the caller asked
    for -- the practice tab lets rows of the topic tree be selected, and
    that selection has to reach the engine.
    The narrowing is a filter over the list the engine already ordered, so
    the priority inside a scope is the engine's unchanged: due first, most
    overdue first, then unstarted. It is deliberately not a call to
    ``get_due`` on some subset, and deliberately not a client-side pick:
    either would be a second copy of SPEC section 5.2 free to drift from the
    first, which is the divergence the engine exists to prevent (there is a
    note about this in ``webui/js/tree.js``).

    Both parameters repeat, and they combine: ``?domain=D1&domain=D2`` and
    ``?domain=D1&objective_id=D3.2.a`` are a single request for the *union*
    of what they name (``_objectives_in_scope``). Studying rarely lines up
    with one unit, and the shape stays one a browser can build and a person
    can read in the address bar -- repeated parameters, not an encoded blob,
    so a practice session is a URL somebody can keep. This is where issue
    #48's "either domain or objective_id, not both" 400 went: the pair it
    rejected was a caller contradicting itself only while a scope was a
    single thing. With a selection, the pair is the ordinary mixed case the
    tree produces, and the priority order it resolves to is still the
    engine's one list, filtered once.

    A selection of one, and no selection at all, behave exactly as they did
    before this parameter could repeat, down to the wording of the 404s.
    """
    domains = domain or []
    objective_ids = objective_id or []
    tracker = resources.tracker_for(topic_id)
    moment = resources.clock.now()
    try:
        due = tracker.get_due(moment)
        unstarted = tracker.get_unstarted(moment)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc

    scope = _describe_scope(domains, objective_ids)
    if scope is not None:
        # Filtering here, after the engine produced the order, is the whole
        # point: ``in_scope`` is a membership test, so the surviving states
        # keep the relative order ``get_due``/``get_unstarted`` gave them.
        in_scope = _objectives_in_scope(resources, topic_id, domains, objective_ids)
        if not in_scope:
            raise HTTPException(
                status_code=404,
                detail=f"topic {topic_id} has no objective matching {scope}",
            )
        due = [state for state in due if state.objective_id in in_scope]
        unstarted = [state for state in unstarted if state.objective_id in in_scope]

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

    # The scoped details say the same two things as the unscoped ones, plus
    # which scope they are about. The unscoped wording is left byte for byte
    # as it was: it is pinned in ``tests/test_web.py`` because the web UI
    # parses it.
    suffix = "" if scope is None else f" matching {scope}"
    if due or unstarted:
        candidates = ", ".join(s.objective_id for s in (*due, *unstarted))
        raise HTTPException(
            status_code=404,
            detail=(
                f"topic {topic_id} has no question for any due or unstarted "
                f"objective{suffix}: {candidates}"
            ),
        )
    raise HTTPException(
        status_code=404,
        detail=(
            f"nothing to study in topic {topic_id}{suffix}: "
            "no objective is due or unstarted"
        ),
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
