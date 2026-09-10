"""Level computation. Pure functions. See SPEC.md section 2.

Nothing here touches the store or the clock: a list of :class:`Attempt` and an
``as_of`` go in, a number or a level comes out. That purity is what makes the
engine testable without infrastructure and what guarantees determinism (SPEC
I3).

**The logic lives in SPEC section 2.2, step by step and with numbers.** If the
spec and an intuition disagree, the spec wins.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from .constants import (
    DECAY_HALF_LIFE_DAYS,
    MASTERY_MIN_DAYS,
    MASTERY_MIN_RAW,
    MASTERY_MIN_SPAN_DAYS,
    MIN_ATTEMPTS,
    RETENTION_FLOOR,
    SCORE_PRECISION,
    THRESHOLD_COMPETENT,
    THRESHOLD_LEARNING,
    WINDOW,
)
from .models import Attempt, Level, ObjectiveState
from .scheduling import compute_next_review, is_due

def order_attempts(attempts: Sequence[Attempt]) -> list[Attempt]:
    """Sorts by ascending ``at``, breaking ties by ``attempt_id``.

    The tie break is not cosmetic: it is what makes inserting the attempts in
    any order produce the same result (SPEC section 2.2 step 1, and C4).

    Args:
        attempts: attempts in any order.

    Returns:
        A new sorted list. It does not mutate the input.
    """
    return sorted(attempts, key=lambda a: (a.at, a.attempt_id))


def attempts_until(
    attempts: Sequence[Attempt], as_of: datetime
) -> list[Attempt]:
    """Filters the attempts with ``at <= as_of`` and sorts them.

    This is the operation that materializes "the state as it was at a past
    date" (SPEC section 5.1). It cuts by ``at``, **never** by ``recorded_at``.

    Args:
        attempts: full history of the objective.
        as_of: cut date, inclusive.

    Returns:
        The attempts in force at that date, sorted.
    """
    return order_attempts([a for a in attempts if a.at <= as_of])


def recent_window(attempts: Sequence[Attempt]) -> tuple[bool, ...]:
    """The last ``WINDOW`` (8) results, from oldest to most recent.

    Args:
        attempts: attempts already sorted and already cut by ``as_of``.

    Returns:
        Tuple of booleans (``True`` = hit). Empty when there are no attempts,
        and shorter than ``WINDOW`` when there are fewer attempts than that.
    """
    return tuple(a.correct for a in attempts[-WINDOW:])


def weighted_raw_score(window: Sequence[bool]) -> float:
    """Raw score weighted by recency. SPEC section 2.2, steps 3-4.

    The most recent entry of the window weighs ``len(window)``, the previous one
    weighs one less, and so on down to ``1``. ``raw`` is the sum of the weights
    of the hits divided by the sum of every weight. With a full window (8) the
    weights are ``1..8`` and add up to 36; with fewer attempts, ``1..n``.

    **The retention floor is NOT applied here.** ``raw`` may be 0.0.

    Args:
        window: results from oldest to most recent. **The order is
            significant.**

    Returns:
        A value in [0.0, 1.0]. With an empty window, ``0.0``.
    """
    if not window:
        return 0.0
    weights = range(1, len(window) + 1)
    correct_weight = sum(w for w, ok in zip(weights, window) if ok)
    return correct_weight / sum(weights)


def retention_factor(
    last_attempt_at: datetime | None, as_of: datetime
) -> float:
    """Decay through inactivity. SPEC section 2.2, step 5.

    ``max(RETENTION_FLOOR, 0.5 ** (gap_in_days / DECAY_HALF_LIFE_DAYS))``, with
    a fractional ``gap``. If ``gap <= 0`` (or there are no attempts), it returns
    ``1.0``.

    The floor is applied here and only here, **never to** ``raw``.

    Returns:
        A factor in [RETENTION_FLOOR, 1.0].
    """
    if last_attempt_at is None:
        return 1.0
    gap_days = _days_between(last_attempt_at, as_of)
    if gap_days <= 0:
        return 1.0
    return max(RETENTION_FLOOR, 0.5 ** (gap_days / DECAY_HALF_LIFE_DAYS))


def compute_score(attempts: Sequence[Attempt], as_of: datetime) -> float:
    """The final ``score`` of an objective. SPEC section 2.2, steps 1-5.

    ``raw * retention``, rounded to ``SCORE_PRECISION`` decimals so that
    floating point does not decide a level at the edge of a threshold (SPEC
    C10).

    Returns ``0.0`` when there are fewer than ``MIN_ATTEMPTS`` attempts: a
    single hit is not evidence.

    Args:
        attempts: history of the objective, in any order.
        as_of: cut date.

    Returns:
        A value in [0.0, 1.0].
    """
    ordered = attempts_until(attempts, as_of)
    window = recent_window(ordered)
    return _score_of(ordered, weighted_raw_score(window), as_of)


def distinct_attempt_days(attempts: Sequence[Attempt]) -> int:
    """How many distinct calendar days have at least one attempt.

    It compares **calendar dates**, not instants: two attempts on the same day
    count as one day (SPEC C3). It feeds the sustain condition of ``MASTERED``.

    The calendar day is the **UTC date** of the instant ``at``, whatever the
    timezone it was recorded with (SPEC section 2.2 step 7, and C3). If the date
    in each attempt's own timezone were used, two attempts half an hour apart
    but noted in different timezones could count as two days, and the result
    would depend on how the date was expressed rather than on when it happened.
    """
    return len({a.at.astimezone(timezone.utc).date() for a in attempts})


def compute_level(
    score: float, attempts: Sequence[Attempt], as_of: datetime
) -> Level:
    """Translates ``score`` into a :class:`Level`. SPEC section 2.2, steps 2, 6
    and 7.

    Thresholds are closed from below (``>=``). Fewer than ``MIN_ATTEMPTS``
    attempts is ``UNASSESSED``. A ``COMPETENT`` is promoted to ``MASTERED`` only
    if it also meets the three sustain conditions of step 7.

    Args:
        score: the value from :func:`compute_score`.
        attempts: needed for the sustain conditions.
        as_of: cut date.
    """
    ordered = attempts_until(attempts, as_of)
    raw = weighted_raw_score(recent_window(ordered))
    return _level_of(score, ordered, raw)


def compute_state(
    objective_id: str, attempts: Sequence[Attempt], as_of: datetime
) -> ObjectiveState:
    """Builds the complete :class:`ObjectiveState`. SPEC sections 1.5 and 2.

    Pure function: the same history and the same ``as_of`` always give the same
    state (SPEC I3, section 5.1).

    Args:
        objective_id: identifier of the objective.
        attempts: history of the objective, in any order. It may be empty (case
            C1: yields ``UNASSESSED``, not an error).
        as_of: cut date. It may precede the first attempt (C6) or be in the
            future (C7); both are legal.
    """
    # It is sorted and cut ONCE; the private helpers receive the list already
    # prepared and do not sort it again. Same result as calling compute_score
    # and compute_level separately (which are wrappers around those very
    # helpers).
    ordered = attempts_until(attempts, as_of)
    first_at = ordered[0].at if ordered else None
    last_at = ordered[-1].at if ordered else None
    window = recent_window(ordered)
    raw = weighted_raw_score(window)
    retention = retention_factor(last_at, as_of)
    score = _score_of(ordered, raw, as_of, retention)
    level = _level_of(score, ordered, raw)
    next_review_at = compute_next_review(ordered, level)
    return ObjectiveState(
        objective_id=objective_id,
        as_of=as_of,
        level=level,
        score=score,
        total_attempts=len(ordered),
        correct_attempts=sum(1 for a in ordered if a.correct),
        recent_window=window,
        first_attempt_at=first_at,
        last_attempt_at=last_at,
        distinct_days=distinct_attempt_days(ordered),
        days_since_last=(
            _days_between(last_at, as_of) if last_at is not None else None
        ),
        retention=retention,
        next_review_at=next_review_at,
        is_due=is_due(next_review_at, as_of),
    )


def _days_between(start: datetime, end: datetime) -> float:
    """Fractional days from ``start`` to ``end`` (negative if ``end`` is earlier)."""
    return (end - start) / timedelta(days=1)


def _score_of(
    ordered: Sequence[Attempt],
    raw: float,
    as_of: datetime,
    retention: float | None = None,
) -> float:
    """Core of :func:`compute_score` over an already sorted and cut list.

    Args:
        ordered: attempts already sorted and cut by ``as_of``.
        raw: ``weighted_raw_score(recent_window(ordered))``, already computed.
        as_of: cut date.
        retention: ``retention_factor(ordered[-1].at, as_of)`` when the caller
            already has it; ``None`` computes it here.
    """
    if len(ordered) < MIN_ATTEMPTS:
        return 0.0
    if retention is None:
        retention = retention_factor(ordered[-1].at, as_of)
    return round(raw * retention, SCORE_PRECISION)


def _level_of(score: float, ordered: Sequence[Attempt], raw: float) -> Level:
    """Core of :func:`compute_level` over an already sorted and cut list.

    Args:
        score: the value from :func:`compute_score`.
        ordered: attempts already sorted and cut by ``as_of``.
        raw: ``weighted_raw_score(recent_window(ordered))``, already computed;
            the sustain condition consumes it.
    """
    if len(ordered) < MIN_ATTEMPTS:
        return Level.UNASSESSED
    score = round(score, SCORE_PRECISION)
    if score < THRESHOLD_LEARNING:
        return Level.WEAK
    if score < THRESHOLD_COMPETENT:
        return Level.LEARNING
    if _is_sustained(ordered, raw):
        return Level.MASTERED
    return Level.COMPETENT


def _is_sustained(ordered: Sequence[Attempt], raw: float) -> bool:
    """The three sustain conditions of SPEC section 2.2, step 7.

    Args:
        ordered: attempts already sorted and cut by ``as_of``, non empty.
        raw: raw score of the recent window, already computed.
    """
    span = ordered[-1].at - ordered[0].at
    return (
        distinct_attempt_days(ordered) >= MASTERY_MIN_DAYS
        and span >= timedelta(days=MASTERY_MIN_SPAN_DAYS)
        and raw >= MASTERY_MIN_RAW
    )
