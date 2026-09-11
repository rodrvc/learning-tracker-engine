"""Progress router: what the engine knows about a topic's objectives.

**Vocabulary translation, contained here and nowhere else in this module's
area:** the product calls the thing being studied a "topic"; the engine calls
the exact same object a "profile" (``core.tracker.LearningTracker`` is bound
to one ``profile_id``). Every request/response model here says "topic"; every
call into ``resources.tracker_for`` passes the profile id, matching the
engine's own words.

**This layer recomputes nothing.** Every field returned here comes straight
from a :class:`~core.models.ObjectiveState`, :class:`~core.models.StateComparison`
or :class:`~core.models.ProfileSummary` built by ``LearningTracker``. There is
no persisted aggregate and no arithmetic of this module's own: the whole point
of the engine (SPEC section 0) is that state is a projection recomputed from
the attempts every time, and adding a shortcut here would reintroduce exactly
the failure that design prevents.

Deliberately absent: a streak or run count. ``ObjectiveState`` has no such
field (SPEC I10) and this layer does not invent one.

**Every cut date must be aware.** ``AwareDatetime`` rejects a naive value with
422 instead of coercing it to UTC: assuming a timezone for a naive input would
make "was I better two weeks ago" depend on server configuration, which is the
same quiet reshaping the recompute-nothing rule forbids elsewhere. The engine
already demands aware datetimes on every ``Attempt`` (``core.models``); this is
the boundary where the same guard belongs for the cut date, because until this
router no datetime ever entered through HTTP.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel

from core.errors import InvalidRangeError, UnknownObjectiveError, UnknownProfileError
from core.models import ObjectiveState, ProfileSummary, StateComparison

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}", tags=["progress"])


class LevelName(str, Enum):
    """Mirrors ``core.models.Level`` by name, in the same spec-ordered ladder.

    Serializing the level by name (rather than the underlying int) keeps a
    client from doing arithmetic on it, but a bare ``str`` field would lose
    the one property ``Level`` documents as deliberate: it is ordered. This
    enum keeps the OpenAPI schema enumerated and in the SPEC section 1.4
    ladder, so a client can sort on it without hardcoding the levels.
    """

    UNASSESSED = "UNASSESSED"
    WEAK = "WEAK"
    LEARNING = "LEARNING"
    COMPETENT = "COMPETENT"
    MASTERED = "MASTERED"


class ObjectiveStateOut(BaseModel):
    """The derived state of one objective at a date. Mirrors ``ObjectiveState``
    field for field (SPEC section 1.5); nothing computed here."""

    objective_id: str
    as_of: datetime
    level: LevelName
    score: float
    total_attempts: int
    correct_attempts: int
    recent_window: tuple[bool, ...]
    first_attempt_at: datetime | None
    last_attempt_at: datetime | None
    distinct_days: int
    days_since_last: float | None
    retention: float
    next_review_at: datetime | None
    is_due: bool


class StateComparisonOut(BaseModel):
    """Two states of the same objective at two dates (SPEC section 5.1)."""

    objective_id: str
    earlier: ObjectiveStateOut
    later: ObjectiveStateOut
    level_delta: int
    score_delta: float
    improved: bool
    regressed: bool


class ProfileSummaryOut(BaseModel):
    """Topic aggregate at a date (SPEC section 9.4)."""

    topic_id: str
    as_of: datetime
    total_objectives: int
    by_level: dict[LevelName, int]
    assessed_objectives: int
    unstarted_objectives: int
    due_objectives: int
    total_attempts: int
    mean_score: float
    coverage: float


def _to_state_out(state: ObjectiveState) -> ObjectiveStateOut:
    return ObjectiveStateOut(
        objective_id=state.objective_id,
        as_of=state.as_of,
        level=LevelName(state.level.name),
        score=state.score,
        total_attempts=state.total_attempts,
        correct_attempts=state.correct_attempts,
        recent_window=state.recent_window,
        first_attempt_at=state.first_attempt_at,
        last_attempt_at=state.last_attempt_at,
        distinct_days=state.distinct_days,
        days_since_last=state.days_since_last,
        retention=state.retention,
        next_review_at=state.next_review_at,
        is_due=state.is_due,
    )


def _to_comparison_out(comparison: StateComparison) -> StateComparisonOut:
    return StateComparisonOut(
        objective_id=comparison.objective_id,
        earlier=_to_state_out(comparison.earlier),
        later=_to_state_out(comparison.later),
        level_delta=comparison.level_delta,
        score_delta=comparison.score_delta,
        improved=comparison.improved,
        regressed=comparison.regressed,
    )


def _to_summary_out(summary: ProfileSummary) -> ProfileSummaryOut:
    return ProfileSummaryOut(
        # The engine's own profile_id, not the path parameter: this layer
        # reports what LearningTracker says, it does not assert an identity
        # of its own (they are always equal today, but the rule is what
        # matters here, not the coincidence).
        topic_id=summary.profile_id,
        as_of=summary.as_of,
        total_objectives=summary.total_objectives,
        by_level={
            LevelName(level.name): count for level, count in summary.by_level.items()
        },
        assessed_objectives=summary.assessed_objectives,
        unstarted_objectives=summary.unstarted_objectives,
        due_objectives=summary.due_objectives,
        total_attempts=summary.total_attempts,
        mean_score=summary.mean_score,
        coverage=summary.coverage,
    )


def _unknown_topic(topic_id: str, exc: UnknownProfileError) -> HTTPException:
    http_exc = HTTPException(status_code=404, detail=f"unknown topic: {topic_id}")
    http_exc.__cause__ = exc
    return http_exc


@router.get("/objectives/states", response_model=list[ObjectiveStateOut])
def get_objective_states(
    topic_id: str,
    as_of: AwareDatetime | None = Query(default=None),
    resources: Resources = Depends(get_resources),
) -> list[ObjectiveStateOut]:
    """The state of every objective of the topic (SPEC ``get_all_states``).

    ``as_of`` is the cut date; omitted, the tracker uses its own clock
    (``clock.now()``), never the current time read here.
    """
    tracker = resources.tracker_for(topic_id)
    try:
        states = tracker.get_all_states(as_of)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return [_to_state_out(state) for state in states]


@router.get("/objectives/due", response_model=list[ObjectiveStateOut])
def get_due(
    topic_id: str,
    as_of: AwareDatetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    resources: Resources = Depends(get_resources),
) -> list[ObjectiveStateOut]:
    """What is due for review, most overdue first (SPEC section 5.2).

    Objectives without a single attempt never appear here: an objective that
    was never seen is not "due", it is unstarted — see ``/objectives/unstarted``.
    """
    tracker = resources.tracker_for(topic_id)
    try:
        due = tracker.get_due(as_of, limit=limit)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return [_to_state_out(state) for state in due]


@router.get("/objectives/unstarted", response_model=list[ObjectiveStateOut])
def get_unstarted(
    topic_id: str,
    as_of: AwareDatetime | None = Query(default=None),
    resources: Resources = Depends(get_resources),
) -> list[ObjectiveStateOut]:
    """Objectives without a single attempt up to ``as_of`` (SPEC ``get_unstarted``).

    ``/summary`` reports ``unstarted_objectives`` as a count; this is the list
    behind that count, so uncovered material is nameable, not just countable.
    """
    tracker = resources.tracker_for(topic_id)
    try:
        unstarted = tracker.get_unstarted(as_of)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return [_to_state_out(state) for state in unstarted]


@router.get("/objectives/stale", response_model=list[ObjectiveStateOut])
def get_stale(
    topic_id: str,
    as_of: AwareDatetime | None = Query(default=None),
    days: int | None = Query(default=None, ge=0),
    resources: Resources = Depends(get_resources),
) -> list[ObjectiveStateOut]:
    """Objectives with no recent activity (SPEC ``get_stale``, failure 4, layer 2).

    ``days`` is passed through unchanged; ``None`` lets the engine apply its
    own default rather than this router restating that number.
    """
    tracker = resources.tracker_for(topic_id)
    try:
        stale = tracker.get_stale(as_of, days=days)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return [_to_state_out(state) for state in stale]


@router.get("/summary", response_model=ProfileSummaryOut)
def get_summary(
    topic_id: str,
    as_of: AwareDatetime | None = Query(default=None),
    resources: Resources = Depends(get_resources),
) -> ProfileSummaryOut:
    """Topic aggregate: coverage, mean score, objectives per level (SPEC
    section 9.4, ``get_summary``)."""
    tracker = resources.tracker_for(topic_id)
    try:
        summary = tracker.get_summary(as_of)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return _to_summary_out(summary)


@router.get("/objectives/{objective_id}/compare", response_model=StateComparisonOut)
def compare_states(
    topic_id: str,
    objective_id: str,
    earlier: AwareDatetime = Query(...),
    later: AwareDatetime = Query(...),
    resources: Resources = Depends(get_resources),
) -> StateComparisonOut:
    """Was the objective better at ``earlier`` than at ``later``? (SPEC
    section 5.1, ``compare_states``). The question this project exists to
    answer, e.g. ``earlier=today-14d&later=today``.
    """
    tracker = resources.tracker_for(topic_id)
    try:
        comparison = tracker.compare_states(objective_id, earlier, later)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    except UnknownObjectiveError as exc:
        raise HTTPException(
            status_code=404, detail=f"unknown objective: {objective_id}"
        ) from exc
    except InvalidRangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_comparison_out(comparison)


__all__ = ["router"]
