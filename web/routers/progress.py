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
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.errors import InvalidRangeError, UnknownObjectiveError, UnknownProfileError
from core.models import Level, ObjectiveState, ProfileSummary, StateComparison

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}", tags=["progress"])


class ObjectiveStateOut(BaseModel):
    """The derived state of one objective at a date. Mirrors ``ObjectiveState``
    field for field (SPEC section 1.5); nothing computed here."""

    objective_id: str
    as_of: datetime
    level: str
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
    by_level: dict[str, int]
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
        level=state.level.name,
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


def _to_summary_out(topic_id: str, summary: ProfileSummary) -> ProfileSummaryOut:
    return ProfileSummaryOut(
        topic_id=topic_id,
        as_of=summary.as_of,
        total_objectives=summary.total_objectives,
        by_level={level.name: count for level, count in summary.by_level.items()},
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
    as_of: datetime | None = Query(default=None),
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


@router.get("/due", response_model=list[ObjectiveStateOut])
def get_due(
    topic_id: str,
    as_of: datetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    resources: Resources = Depends(get_resources),
) -> list[ObjectiveStateOut]:
    """What is due for review, most overdue first (SPEC section 5.2).

    Objectives without a single attempt never appear here: an objective that
    was never seen is not "due", it is unstarted (SPEC ``get_unstarted``,
    not exposed by this router — nothing in ACU-251 asked for it).
    """
    tracker = resources.tracker_for(topic_id)
    try:
        due = tracker.get_due(as_of, limit=limit)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return [_to_state_out(state) for state in due]


@router.get("/summary", response_model=ProfileSummaryOut)
def get_summary(
    topic_id: str,
    as_of: datetime | None = Query(default=None),
    resources: Resources = Depends(get_resources),
) -> ProfileSummaryOut:
    """Topic aggregate: coverage, mean score, objectives per level (SPEC
    section 9.4, ``get_summary``)."""
    tracker = resources.tracker_for(topic_id)
    try:
        summary = tracker.get_summary(as_of)
    except UnknownProfileError as exc:
        raise _unknown_topic(topic_id, exc)
    return _to_summary_out(topic_id, summary)


@router.get("/objectives/{objective_id}/compare", response_model=StateComparisonOut)
def compare_states(
    topic_id: str,
    objective_id: str,
    earlier: datetime = Query(...),
    later: datetime = Query(...),
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
