"""Next review computation. Pure functions. See SPEC.md section 4.

Spaced repetition with the fixed ladder ``[1, 3, 7, 14, 30]`` days. The interval
is **derived** from the history on every query: there is no stored ``ease`` or
``interval`` that a bug could corrupt irreversibly. That was failure 3 of the
earlier systems.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from .constants import (
    MASTERY_INTERVAL_MULTIPLIER,
    MAX_INTERVAL_DAYS,
    SCHEDULE_DAYS,
)
from .models import Attempt, Level


def trailing_success_run(attempts: Sequence[Attempt]) -> int:
    """Consecutive hits at the end of the history.

    Counts from the most recent attempt backwards until the first miss.

    .. warning::
       This is **not a measure of progress** and must not be exposed as one. It
       is a local variable of the interval computation, nothing more. Confusing
       this number with the student's progress was exactly failure 1: an
       objective with five mixed answers yields ``1`` here, indistinguishable
       from "nothing was saved". For progress there is
       ``ObjectiveState.score``.

    Args:
        attempts: attempts already sorted and cut by ``as_of``.

    Returns:
        ``0`` if the last attempt was a miss or if there are no attempts.
    """
    run = 0
    for attempt in reversed(attempts):
        if not attempt.correct:
            break
        run += 1
    return run


def interval_days(success_run: int, level: Level) -> int:
    """Days until the next review. SPEC section 4.2.

    ``success_run == 0`` (last attempt failed) yields the first rung, 1 day.
    From there on ``index = min(success_run - 1, 4)`` over ``SCHEDULE_DAYS``. If
    the level is ``MASTERED``, the result is multiplied by
    ``MASTERY_INTERVAL_MULTIPLIER``, capped at ``MAX_INTERVAL_DAYS``.

    Args:
        success_run: output of :func:`trailing_success_run`.
        level: current level of the objective.

    Returns:
        Days, always ``>= 1``.
    """
    index = 0 if success_run == 0 else min(success_run - 1, len(SCHEDULE_DAYS) - 1)
    days = SCHEDULE_DAYS[index]
    if level is Level.MASTERED:
        days = min(days * MASTERY_INTERVAL_MULTIPLIER, MAX_INTERVAL_DAYS)
    return days


def compute_next_review(
    attempts: Sequence[Attempt], level: Level
) -> datetime | None:
    """Instant of the next review. SPEC section 4.2.

    ``last_attempt_at + interval_days(...)``.

    Args:
        attempts: attempts already cut by ``as_of``.
        level: current level, which may stretch the interval when ``MASTERED``.

    Returns:
        ``None`` if there are no attempts. An objective with no evidence is not
        "due", it is unstarted, and it is listed separately (SPEC section 5.2,
        C1).
    """
    if not attempts:
        return None
    days = interval_days(trailing_success_run(attempts), level)
    return attempts[-1].at + timedelta(days=days)


def is_due(next_review_at: datetime | None, as_of: datetime) -> bool:
    """Whether the review is due at that date.

    ``next_review_at is not None and next_review_at <= as_of``.
    """
    return next_review_at is not None and next_review_at <= as_of
