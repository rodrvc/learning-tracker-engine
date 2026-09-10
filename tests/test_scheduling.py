"""Tests of core/scheduling.py against SPEC.md section 4, section 6 I10,
section 7 (C1, C2, C5) and section 8.

Conventions:

* ``spec``: section 4.1 ladder, section 4.2 rule (points 1-6) and section 4.3
  due state, with the numeric example of the spec copied verbatim.
* ``edge``: C1 (no attempts), C2 (a single attempt), C5 (long gap).
* ``invariant``: I10, ``ObjectiveState`` does not expose ``streak`` (failure 1
  of section 8).

No magic numbers: the ladder, the multiplier and the ceiling come from
``core/constants.py``. If a value of the spec does not match the code, the
discrepancy is reported; the test is not adjusted.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.constants import (
    MASTERY_INTERVAL_MULTIPLIER,
    MAX_INTERVAL_DAYS,
    MIN_ATTEMPTS,
    SCHEDULE_DAYS,
)
from core.leveling import compute_state
from core.models import Attempt, Level, ObjectiveState
from core.scheduling import (
    compute_next_review,
    interval_days,
    is_due,
    trailing_success_run,
)

OBJ = "X"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)

#: Levels that do NOT stretch the interval (every one but MASTERED).
NON_MASTERED = [lvl for lvl in Level if lvl is not Level.MASTERED]


def attempt(i: int, correct: bool, at: datetime) -> Attempt:
    return Attempt(attempt_id=f"a{i:03d}", objective_id=OBJ, at=at, correct=correct)


def daily(results: str, start: datetime = T0) -> list[Attempt]:
    """'FFFCF' -> one attempt per consecutive day, in order, from ``start``."""
    return [attempt(i, ch == "C", start + i * DAY) for i, ch in enumerate(results)]


# ---------------------------------------------------------------------------
# Section 4.2 point 1 - the trailing run S (local variable, not a progress measure)
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ("", 0),
        ("F", 0),
        ("C", 1),
        ("FFFCF", 0),  # row 5 of section 3: the last one is a miss
        ("FFFC", 1),  # row 4 of section 3
        ("CCF", 0),
        ("FCC", 2),
        ("CFCCC", 3),
        ("C" * 8, 8),  # row 13 of section 3.1
    ],
)
def test_trailing_success_run_counts_back_to_the_first_miss(results, expected):
    assert trailing_success_run(daily(results)) == expected


# ---------------------------------------------------------------------------
# Sections 4.1 + 4.2 points 2-3 - the complete ladder
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_the_ladder_is_the_one_in_the_spec():
    assert SCHEDULE_DAYS == (1, 3, 7, 14, 30)


@pytest.mark.spec
@pytest.mark.parametrize("level", NON_MASTERED)
@pytest.mark.parametrize(
    ("success_run", "step"),
    [
        (0, 0),  # last attempt failed => index 0 => 1 day
        (1, 0),  # S=1 -> 1d
        (2, 1),  # S=2 -> 3d
        (3, 2),  # S=3 -> 7d
        (4, 3),  # S=4 -> 14d
        (5, 4),  # S=5 -> 30d
        (6, 4),  # S>=5 saturates on the last rung
        (8, 4),  # S=8 (row 13 of section 3.1) -> 30d
    ],
)
def test_ladder_without_mastered(success_run, step, level):
    assert interval_days(success_run, level) == SCHEDULE_DAYS[step]


@pytest.mark.spec
def test_ladder_literal_values_from_the_spec():
    """The numbers of section 4.2.3 verbatim, so that a change in constants.py
    without touching SPEC.md trips here."""
    expected = {0: 1, 1: 1, 2: 3, 3: 7, 4: 14, 5: 30, 8: 30}
    assert {s: interval_days(s, Level.WEAK) for s in expected} == expected


@pytest.mark.spec
def test_the_interval_is_always_at_least_one_day():
    for level in Level:
        for s in range(0, 20):
            assert interval_days(s, level) >= 1


# ---------------------------------------------------------------------------
# Section 4.2 point 5 - MASTERED multiplies by 2 with a ceiling of 60
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize("success_run", range(0, 10))
def test_mastered_multiplies_with_a_ceiling(success_run):
    base = interval_days(success_run, Level.COMPETENT)
    assert interval_days(success_run, Level.MASTERED) == min(
        base * MASTERY_INTERVAL_MULTIPLIER, MAX_INTERVAL_DAYS
    )


@pytest.mark.spec
def test_mastered_literal_values_from_the_spec():
    assert MASTERY_INTERVAL_MULTIPLIER == 2
    assert MAX_INTERVAL_DAYS == 60
    assert interval_days(5, Level.MASTERED) == 60
    assert interval_days(8, Level.MASTERED) == 60
    assert interval_days(4, Level.MASTERED) == 28
    assert interval_days(0, Level.MASTERED) == 2


@pytest.mark.spec
def test_the_ceiling_is_never_exceeded():
    for s in range(0, 50):
        assert interval_days(s, Level.MASTERED) <= MAX_INTERVAL_DAYS


@pytest.mark.spec
def test_only_mastered_stretches_the_interval():
    for s in range(0, 10):
        base = {interval_days(s, lvl) for lvl in NON_MASTERED}
        assert len(base) == 1, "a non-MASTERED level does not influence the interval"


# ---------------------------------------------------------------------------
# Section 4.2 point 4 - next_review_at = last_attempt_at + interval
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    ("results", "level"),
    [
        ("FFFCF", Level.WEAK),
        ("FFFC", Level.WEAK),
        ("FCC", Level.LEARNING),
        ("C" * 8, Level.COMPETENT),
        ("C" * 8, Level.MASTERED),
        ("C", Level.UNASSESSED),
    ],
)
def test_next_review_is_last_attempt_plus_interval(results, level):
    history = daily(results)
    expected_days = interval_days(trailing_success_run(history), level)
    assert compute_next_review(history, level) == history[-1].at + timedelta(days=expected_days)


@pytest.mark.spec
def test_next_review_keeps_the_time_of_day_of_the_last_attempt():
    late = T0.replace(hour=23, minute=59)
    history = [attempt(0, True, late)]
    result = compute_next_review(history, Level.UNASSESSED)
    assert result == late + timedelta(days=SCHEDULE_DAYS[0])
    assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# Section 4.3 - due state and the numeric example of the spec
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_is_due_definition():
    t = T0
    assert is_due(None, t) is False
    assert is_due(t, t) is True  # <=, not <
    assert is_due(t - timedelta(seconds=1), t) is True
    assert is_due(t + timedelta(seconds=1), t) is False


@pytest.mark.spec
def test_example_4_3_after_row_5_next_review_is_2026_01_06():
    """After row 5 (the miss of 2026-01-05), S=0 => 1 day => 2026-01-06."""
    history = daily("FFFCF")
    assert history[-1].at.date() == datetime(2026, 1, 5).date()
    state = compute_state(OBJ, history, history[-1].at)
    assert state.level is Level.WEAK
    assert trailing_success_run(history) == 0
    assert state.next_review_at == datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)
    assert state.next_review_at.date() == datetime(2026, 1, 6).date()
    assert state.is_due is False
    assert is_due(state.next_review_at, state.next_review_at) is True


@pytest.mark.spec
def test_example_4_3_after_row_13_mastered_and_2026_03_14():
    """After row 13 (2026-01-13), S=8 and MASTERED => 30 x 2 = 60 => 2026-03-14."""
    history = daily("FFFCF" + "C" * 8)
    assert len(history) == 13
    assert history[-1].at.date() == datetime(2026, 1, 13).date()
    state = compute_state(OBJ, history, history[-1].at)
    assert state.level is Level.MASTERED
    assert trailing_success_run(history) == 8
    assert interval_days(8, Level.MASTERED) == MAX_INTERVAL_DAYS == 60
    assert state.next_review_at == datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    assert state.next_review_at.date() == datetime(2026, 3, 14).date()
    assert state.is_due is False


@pytest.mark.spec
def test_example_4_3_row_12_already_mastered_but_run_of_7():
    """Row 12: MASTERED with S=7 (>=5 => 30d) x2 = 60d => 2026-03-13.
    It checks that the ceiling, not the index, governs the result."""
    history = daily("FFFCF" + "C" * 7)
    state = compute_state(OBJ, history, history[-1].at)
    assert state.level is Level.MASTERED
    assert state.next_review_at == history[-1].at + timedelta(days=MAX_INTERVAL_DAYS)


# ---------------------------------------------------------------------------
# Section 7 - edge cases
# ---------------------------------------------------------------------------


@pytest.mark.edge
@pytest.mark.parametrize("level", list(Level))
def test_c1_without_attempts_next_review_is_none_and_not_due(level):
    """Section 4.2 point 6 / C1: with no evidence there is no review and no due."""
    assert compute_next_review([], level) is None
    assert is_due(compute_next_review([], level), T0) is False
    assert is_due(None, T0 + 3650 * DAY) is False


@pytest.mark.edge
def test_c1_without_attempts_through_compute_state():
    state = compute_state(OBJ, [], T0)
    assert state.next_review_at is None
    assert state.is_due is False
    assert state.level is Level.UNASSESSED


@pytest.mark.edge
@pytest.mark.parametrize("correct", [True, False])
def test_c2_a_single_attempt_is_unassessed_but_has_a_next_review(correct):
    history = [attempt(0, correct, T0)]
    assert len(history) < MIN_ATTEMPTS
    state = compute_state(OBJ, history, T0)
    assert state.level is Level.UNASSESSED
    assert state.score == 0.0
    assert state.total_attempts == 1
    # The review IS computed: S=1 (hit) or S=0 (miss), both 1 day.
    assert state.next_review_at == T0 + timedelta(days=SCHEDULE_DAYS[0])
    assert compute_next_review(history, Level.UNASSESSED) == state.next_review_at
    assert state.is_due is False
    assert is_due(state.next_review_at, T0 + DAY) is True


@pytest.mark.edge
def test_c5_long_gap_next_review_in_the_past_and_due():
    history = daily("C" * 8)
    last = history[-1].at
    for gap_days in (90, 365, 3650):
        as_of = last + gap_days * DAY
        state = compute_state(OBJ, history, as_of)
        # The review does not depend on as_of: it is last_attempt_at + interval.
        assert state.next_review_at == compute_next_review(history, state.level)
        assert state.next_review_at <= last + timedelta(days=MAX_INTERVAL_DAYS)
        assert state.next_review_at < as_of
        assert state.is_due is True
        assert (as_of - state.next_review_at) >= (gap_days - MAX_INTERVAL_DAYS) * DAY


@pytest.mark.edge
def test_c5_the_most_overdue_is_the_one_with_the_largest_gap():
    """Basis of the get_due order (section 5.2): the larger the gap, the older
    next_review_at."""
    recent = daily("C" * 3, start=T0 + 100 * DAY)
    old = daily("C" * 3, start=T0)
    as_of = T0 + 400 * DAY
    nr_recent = compute_next_review(recent, Level.LEARNING)
    nr_old = compute_next_review(old, Level.LEARNING)
    assert nr_old < nr_recent
    assert is_due(nr_old, as_of) and is_due(nr_recent, as_of)


# ---------------------------------------------------------------------------
# Section 6 I10 / section 8 failure 1 - ObjectiveState does not expose streak
# ---------------------------------------------------------------------------

FORBIDDEN_FIELD_NAMES = {"streak", "racha", "success_run", "trailing_success_run"}


@pytest.mark.invariant
def test_i10_objective_state_has_no_streak_field():
    names = {f.name for f in dataclasses.fields(ObjectiveState)}
    assert "streak" not in names
    assert not (names & FORBIDDEN_FIELD_NAMES)


@pytest.mark.invariant
def test_i10_grep_models_does_not_declare_streak_as_a_field():
    """Automated grep over core/models.py: no line declares a field named
    ``streak`` (``streak: <type>``). Mentioning it in a docstring to say it does
    NOT exist is allowed; declaring it is not."""
    source = Path(__file__).resolve().parent.parent / "core" / "models.py"
    text = source.read_text(encoding="utf-8")
    field_decl = re.compile(r"^\s*\w*streak\w*\s*:", re.IGNORECASE | re.MULTILINE)
    assert field_decl.search(text) is None, "core/models.py declares a streak field"


@pytest.mark.invariant
def test_i10_row_5_of_the_spec_is_indistinguishable_from_nothing_with_only_a_run():
    """Failure 1 of section 8, demonstrated: the run of row 5 is 0 and that of
    row 4 is 1, but the state exposes total_attempts, recent_window and score."""
    history = daily("FFFCF")
    assert trailing_success_run(history[:4]) == 1
    assert trailing_success_run(history) == 0
    state = compute_state(OBJ, history, history[-1].at)
    assert state.total_attempts == 5
    assert state.recent_window == (False, False, False, True, False)
    assert state.score == pytest.approx(4 / 15, abs=1e-6)
    assert not hasattr(state, "streak")


@pytest.mark.invariant
def test_i3_determinism_of_the_review():
    history = daily("FCCFCC")
    first = compute_next_review(history, Level.LEARNING)
    for _ in range(5):
        assert compute_next_review(list(history), Level.LEARNING) == first
