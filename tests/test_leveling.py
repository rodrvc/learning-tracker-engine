"""Tests of core/leveling.py against SPEC.md sections 2, 3, 3.1 and 7.

Conventions:

* ``spec``: one test per step of section 2.2.
* ``edge``: edge cases of section 7 (C1, C2, C3, C5, C6, C7, C10).
* ``invariant``: determinism (I3) and independence from insertion order.

The numbers of the acceptance tests (sections 3 and 3.1) are the ones in the
spec table, copied verbatim. If a number does not match, the discrepancy is
reported; the test is not adjusted.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.constants import (
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
from core.leveling import (
    attempts_until,
    compute_level,
    compute_score,
    compute_state,
    distinct_attempt_days,
    order_attempts,
    recent_window,
    retention_factor,
    weighted_raw_score,
)
from core.models import Attempt, Level, ObjectiveState

OBJ = "X"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)

#: Tolerance for comparing against the 3 decimals of the spec tables.
TABLE_TOL = 0.0005


def attempt(
    i: int,
    correct: bool,
    at: datetime,
    recorded_at: datetime | None = None,
    attempt_id: str | None = None,
) -> Attempt:
    return Attempt(
        attempt_id=attempt_id or f"a{i:03d}",
        objective_id=OBJ,
        at=at,
        correct=correct,
        recorded_at=recorded_at,
    )


def daily(results: str, start: datetime = T0) -> list[Attempt]:
    """'FFFCF' -> one attempt per consecutive day, in order, from ``start``."""
    return [
        attempt(i, ch == "C", start + i * DAY) for i, ch in enumerate(results)
    ]


# ---------------------------------------------------------------------------
# Section 2.2 step 1 - filter and sort
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_step1_order_attempts_sorts_by_at_and_breaks_ties_by_attempt_id():
    a = attempt(0, True, T0 + DAY, attempt_id="b")
    b = attempt(1, True, T0 + DAY, attempt_id="a")
    c = attempt(2, True, T0, attempt_id="z")
    original = [a, b, c]
    ordered = order_attempts(original)
    assert [x.attempt_id for x in ordered] == ["z", "a", "b"]
    assert original == [a, b, c], "it must not mutate the input"
    assert ordered is not original


@pytest.mark.spec
def test_step1_attempts_until_cuts_by_at_inclusively():
    history = daily("CCC")
    cut = attempts_until(history, T0 + DAY)
    assert [x.attempt_id for x in cut] == ["a000", "a001"]


@pytest.mark.spec
def test_step1_attempts_until_ignores_recorded_at():
    late_write = T0 + 30 * DAY
    history = [
        attempt(0, True, T0, recorded_at=late_write),
        attempt(1, True, T0 + DAY, recorded_at=late_write),
        attempt(2, True, T0 + 2 * DAY, recorded_at=T0 + 2 * DAY),
    ]
    cut = attempts_until(history, T0 + DAY)
    assert [x.attempt_id for x in cut] == ["a000", "a001"]
    assert attempts_until(history, late_write) == order_attempts(history)


# ---------------------------------------------------------------------------
# Section 2.2 step 2 - n < MIN_ATTEMPTS => UNASSESSED
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize("correct", [True, False])
def test_step2_fewer_than_min_attempts_is_unassessed_with_score_zero(correct):
    history = [attempt(0, correct, T0)]
    assert len(history) < MIN_ATTEMPTS
    assert compute_score(history, T0) == 0.0
    assert compute_level(0.0, history, T0) is Level.UNASSESSED
    # Even if someone passes a high score, with n<MIN_ATTEMPTS it stays UNASSESSED.
    assert compute_level(1.0, history, T0) is Level.UNASSESSED


@pytest.mark.spec
def test_step2_with_min_attempts_a_level_is_assigned():
    history = daily("F" * MIN_ATTEMPTS)
    as_of = history[-1].at
    assert compute_level(compute_score(history, as_of), history, as_of) is Level.WEAK


# ---------------------------------------------------------------------------
# Section 2.2 step 3 - recent window
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_step3_recent_window_is_the_last_window_oldest_to_newest():
    history = daily("F" * 3 + "C" * WINDOW)
    window = recent_window(history)
    assert len(window) == WINDOW
    assert window == (True,) * WINDOW
    history = daily("FC")
    assert recent_window(history) == (False, True)
    assert recent_window([]) == ()


@pytest.mark.spec
def test_step3_positional_weights_of_a_full_window_add_up_to_36():
    # With a full window the weights are 1..8 (sum 36): a single hit in the
    # most recent position weighs 8/36.
    window = (False,) * (WINDOW - 1) + (True,)
    total = sum(range(1, WINDOW + 1))
    assert total == 36
    assert weighted_raw_score(window) == pytest.approx(WINDOW / total)
    # ...and the oldest one weighs 1/36.
    assert weighted_raw_score((True,) + (False,) * (WINDOW - 1)) == pytest.approx(1 / total)


# ---------------------------------------------------------------------------
# Section 2.2 step 4 - raw
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_step4_raw_is_the_sum_of_hit_weights_over_the_total():
    # Row 4 of section 3: [F,F,F,C] -> 4/10.
    assert weighted_raw_score((False, False, False, True)) == pytest.approx(0.4)
    # Row 5 of section 3: [F,F,F,C,F] -> 4/15.
    assert weighted_raw_score((False, False, False, True, False)) == pytest.approx(4 / 15)


@pytest.mark.spec
def test_step4_raw_has_no_floor_and_can_be_zero_or_one():
    assert weighted_raw_score((False, False, False)) == 0.0
    assert weighted_raw_score((True,) * WINDOW) == 1.0
    assert weighted_raw_score(()) == 0.0
    assert 0.0 < RETENTION_FLOOR, "el suelo existe, pero no toca al raw"


@pytest.mark.spec
def test_step4_table_2_4_a_residual_miss():
    full = (True,) * WINDOW
    oldest_fail = (False,) + (True,) * (WINDOW - 1)
    second_oldest_fail = (True, False) + (True,) * (WINDOW - 2)
    assert weighted_raw_score(full) == pytest.approx(1.0)
    assert weighted_raw_score(oldest_fail) == pytest.approx(0.972, abs=TABLE_TOL)
    assert weighted_raw_score(second_oldest_fail) == pytest.approx(0.944, abs=TABLE_TOL)
    assert weighted_raw_score(oldest_fail) >= MASTERY_MIN_RAW
    assert weighted_raw_score(second_oldest_fail) < MASTERY_MIN_RAW


# ---------------------------------------------------------------------------
# Section 2.2 step 5 - decay with a floor
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    "gap_days, expected",
    [(0, 1.000), (7, 0.948), (15, 0.891), (30, 0.794), (60, 0.630),
     (90, 0.500), (180, 0.400), (365, 0.400)],
)
def test_step5_retention_table(gap_days, expected):
    assert retention_factor(T0, T0 + gap_days * DAY) == pytest.approx(
        expected, abs=TABLE_TOL
    )


@pytest.mark.spec
def test_step5_retention_formula_with_a_fractional_gap():
    gap = timedelta(days=45, hours=12)
    expected = 0.5 ** ((45 + 0.5) / DECAY_HALF_LIFE_DAYS)
    assert retention_factor(T0, T0 + gap) == pytest.approx(expected)
    assert retention_factor(T0, T0 + timedelta(days=DECAY_HALF_LIFE_DAYS)) == pytest.approx(0.5)


@pytest.mark.spec
def test_step5_a_non_positive_gap_or_no_attempts_gives_one():
    assert retention_factor(T0, T0) == 1.0
    assert retention_factor(T0 + DAY, T0) == 1.0
    assert retention_factor(None, T0) == 1.0


@pytest.mark.spec
def test_step5_the_floor_applies_only_to_retention_never_to_raw():
    # Mastered and abandoned for a year: raw 1.0 x 0.40 = 0.400.
    mastered_abandoned = daily("C" * WINDOW)
    a_year_later = mastered_abandoned[-1].at + 365 * DAY
    assert retention_factor(mastered_abandoned[-1].at, a_year_later) == RETENTION_FLOOR
    assert compute_score(mastered_abandoned, a_year_later) == pytest.approx(RETENTION_FLOOR)
    # Always missed, just seen: raw 0.0 x 1.0 = 0.0 (the floor does NOT lift it).
    always_wrong = daily("F" * WINDOW)
    assert compute_score(always_wrong, always_wrong[-1].at) == 0.0
    # Always missed and abandoned: 0.0 x 0.40 = 0.0, not 0.40.
    assert compute_score(always_wrong, always_wrong[-1].at + 365 * DAY) == 0.0


@pytest.mark.spec
def test_step5_score_is_raw_times_retention_rounded():
    history = daily("FCCC")
    as_of = history[-1].at + 33 * DAY
    raw = weighted_raw_score(recent_window(history))
    retention = retention_factor(history[-1].at, as_of)
    assert compute_score(history, as_of) == round(raw * retention, SCORE_PRECISION)


# ---------------------------------------------------------------------------
# Section 2.2 step 6 - thresholds closed from below
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    "score, expected",
    [
        (0.0, Level.WEAK),
        (THRESHOLD_LEARNING - 1e-6, Level.WEAK),
        (THRESHOLD_LEARNING, Level.LEARNING),
        (THRESHOLD_COMPETENT - 1e-6, Level.LEARNING),
        (THRESHOLD_COMPETENT, Level.COMPETENT),
        (1.0, Level.COMPETENT),
    ],
)
def test_step6_thresholds(score, expected):
    # One afternoon of history: it can never be MASTERED (span 0), so the test
    # isolates step 6 from step 7.
    history = [attempt(i, True, T0 + i * timedelta(minutes=1)) for i in range(WINDOW)]
    assert compute_level(score, history, history[-1].at) is expected


# ---------------------------------------------------------------------------
# Section 2.2 step 7 - promotion to MASTERED
# ---------------------------------------------------------------------------


def _mastery_candidate(span_days: int, results: str = "C" * WINDOW) -> list[Attempt]:
    """Attempts spread between T0 and T0+span_days, on distinct days."""
    step = timedelta(days=span_days) / max(len(results) - 1, 1)
    return [attempt(i, ch == "C", T0 + i * step) for i, ch in enumerate(results)]


@pytest.mark.spec
def test_step7_mastered_with_the_three_conditions():
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS)
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert distinct_attempt_days(history) >= MASTERY_MIN_DAYS
    assert compute_level(score, history, as_of) is Level.MASTERED


@pytest.mark.spec
def test_step7_without_enough_span_it_stays_competent():
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS - 1)
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert compute_level(score, history, as_of) is Level.COMPETENT


@pytest.mark.spec
def test_step7_without_distinct_days_it_stays_competent():
    # Every attempt on the same calendar day; a span >= 7 days is impossible
    # then, so distinct_days == 1 is forced here with span 0.
    history = [attempt(i, True, T0 + i * timedelta(hours=1)) for i in range(WINDOW)]
    as_of = history[-1].at
    assert distinct_attempt_days(history) == 1 < MASTERY_MIN_DAYS
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert compute_level(score, history, as_of) is Level.COMPETENT


@pytest.mark.spec
def test_step7_raw_below_0_95_stays_competent():
    # Miss with weight 2: raw = 34/36 = 0.944 < 0.95, score >= 0.85.
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS * 2, "CF" + "C" * (WINDOW - 2))
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert weighted_raw_score(recent_window(history)) < MASTERY_MIN_RAW
    assert compute_level(score, history, as_of) is Level.COMPETENT
    # Miss with weight 1: raw = 35/36 = 0.972 >= 0.95 -> MASTERED.
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS * 2, "F" + "C" * (WINDOW - 1))
    as_of = history[-1].at
    assert compute_level(compute_score(history, as_of), history, as_of) is Level.MASTERED


@pytest.mark.spec
def test_step7_mastered_is_lost_through_decay_not_through_sustain():
    # Section 2.4: the score drops below 0.85 after 22 days and falls to LEARNING.
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS * 2)
    last = history[-1].at
    assert compute_level(compute_score(history, last + 21 * DAY), history, last + 21 * DAY) is Level.MASTERED
    assert compute_level(compute_score(history, last + 22 * DAY), history, last + 22 * DAY) is Level.LEARNING


# ---------------------------------------------------------------------------
# distinct_attempt_days (C3)
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_distinct_attempt_days_compares_calendar_dates():
    same_day = [
        attempt(0, True, datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)),
        attempt(1, True, datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)),
    ]
    assert distinct_attempt_days(same_day) == 1
    # One minute apart, but across midnight: two days.
    across_midnight = [
        attempt(0, True, datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)),
        attempt(1, True, datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)),
    ]
    assert distinct_attempt_days(across_midnight) == 2
    assert same_day[0].at.date() == date(2026, 1, 1)
    assert distinct_attempt_days([]) == 0


@pytest.mark.edge
def test_distinct_attempt_days_with_mixed_zones_uses_the_utc_date():
    # C3: "same day" is the same UTC date of the instant, not the date in the
    # zone each attempt was recorded with. 23:00-05:00 of day 1 is 04:00Z of
    # day 2, half an hour before 04:30Z: a single day.
    minus5 = timezone(timedelta(hours=-5))
    same_utc_day = [
        attempt(0, True, datetime(2026, 1, 1, 23, 0, tzinfo=minus5)),
        attempt(1, True, datetime(2026, 1, 2, 4, 30, tzinfo=timezone.utc)),
    ]
    assert same_utc_day[0].at.date() != same_utc_day[1].at.date()
    assert distinct_attempt_days(same_utc_day) == 1
    # The inverse case: same local date in different zones, different UTC day.
    # 23:30-05:00 of day 1 is 04:30Z of day 2; 01:00+00:00 is day 1.
    same_local_date = [
        attempt(0, True, datetime(2026, 1, 1, 23, 30, tzinfo=minus5)),
        attempt(1, True, datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)),
    ]
    assert same_local_date[0].at.date() == same_local_date[1].at.date()
    assert distinct_attempt_days(same_local_date) == 2


@pytest.mark.spec
def test_step7_distinct_days_are_counted_in_utc_not_in_local_date():
    # Eight hits within the same UTC day (raw = 1.0 >= 0.95), noted in
    # alternating zones so that their local dates are two different ones.
    # Counting days by local date would give distinct_days == 2; in UTC it is 1,
    # so there is no promotion to MASTERED. (A span >= 7 days within a single
    # UTC day is impossible, so condition 2 fails here too; what this test pins
    # down is the reference zone of condition 1.)
    minus5 = timezone(timedelta(hours=-5))
    plus9 = timezone(timedelta(hours=9))
    base = datetime(2026, 1, 2, 6, 0, tzinfo=timezone.utc)
    history = [
        attempt(i, True, (base + i * timedelta(hours=2)).astimezone(minus5 if i % 2 else plus9))
        for i in range(WINDOW)
    ]
    assert len({a.at.date() for a in history}) == 2
    assert len({a.at.astimezone(timezone.utc).date() for a in history}) == 1
    assert distinct_attempt_days(history) == 1 < MASTERY_MIN_DAYS
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert weighted_raw_score(recent_window(history)) >= MASTERY_MIN_RAW
    assert compute_level(score, history, as_of) is Level.COMPETENT
    assert compute_state(OBJ, history, as_of).distinct_days == 1


# ---------------------------------------------------------------------------
# Sections 3 and 3.1 - acceptance tests, number by number against the table
# ---------------------------------------------------------------------------

# (#, result, raw, score, level) from the tables of sections 3 and 3.1. Row 1
# has no raw in the table ("-"); it is encoded as None.
RECORRIDO = [
    (1, "F", None, 0.000, Level.UNASSESSED),
    (2, "F", 0.000, 0.000, Level.WEAK),
    (3, "F", 0.000, 0.000, Level.WEAK),
    (4, "C", 0.400, 0.400, Level.WEAK),
    (5, "F", 0.267, 0.267, Level.WEAK),
    (6, "C", 0.476, 0.476, Level.WEAK),
    (7, "C", 0.607, 0.607, Level.LEARNING),
    (8, "C", 0.694, 0.694, Level.LEARNING),
    (9, "C", 0.806, 0.806, Level.LEARNING),
    (10, "C", 0.889, 0.889, Level.COMPETENT),
    (11, "C", 0.944, 0.944, Level.COMPETENT),
    (12, "C", 0.972, 0.972, Level.MASTERED),
    (13, "C", 1.000, 1.000, Level.MASTERED),
]
RECORRIDO_RESULTADOS = "".join(row[1] for row in RECORRIDO)
RECORRIDO_INICIO = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.spec
@pytest.mark.parametrize("row", RECORRIDO, ids=[f"fila{r[0]}" for r in RECORRIDO])
def test_walkthrough_of_sections_3_and_3_1(row):
    n, _, raw_expected, score_expected, level_expected = row
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    as_of = history[n - 1].at
    state = compute_state(OBJ, history, as_of)
    window = recent_window(attempts_until(history, as_of))
    assert state.total_attempts == n
    assert len(window) == min(n, WINDOW)
    if raw_expected is not None:
        assert weighted_raw_score(window) == pytest.approx(raw_expected, abs=TABLE_TOL)
    assert state.retention == 1.0
    assert state.score == pytest.approx(score_expected, abs=TABLE_TOL)
    assert state.level is level_expected


@pytest.mark.spec
def test_walkthrough_row_12_mastered_conditions():
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    state = compute_state(OBJ, history, history[11].at)
    assert state.distinct_days == 12
    assert state.last_attempt_at - state.first_attempt_at == 11 * DAY
    assert state.recent_window == (False,) + (True,) * (WINDOW - 1)


OLVIDO = [
    (datetime(2026, 1, 13, 12, 0, tzinfo=timezone.utc), 0, 1.000, 1.000, Level.MASTERED),
    (datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc), 7, 0.948, 0.948, Level.MASTERED),
    (datetime(2026, 2, 3, 12, 0, tzinfo=timezone.utc), 21, 0.851, 0.851, Level.MASTERED),
    (datetime(2026, 2, 4, 12, 0, tzinfo=timezone.utc), 22, 0.844, 0.844, Level.LEARNING),
    (datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc), 30, 0.794, 0.794, Level.LEARNING),
    (datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc), 60, 0.630, 0.630, Level.LEARNING),
    (datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc), 90, 0.500, 0.500, Level.WEAK),
    (datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc), 180, 0.400, 0.400, Level.WEAK),
    (datetime(2027, 1, 13, 12, 0, tzinfo=timezone.utc), 365, 0.400, 0.400, Level.WEAK),
]


@pytest.mark.spec
@pytest.mark.parametrize("row", OLVIDO, ids=[f"gap{r[1]}d" for r in OLVIDO])
def test_forgetting_of_section_3_1_without_new_attempts(row):
    as_of, gap, retention_expected, score_expected, level_expected = row
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    assert as_of - history[-1].at == gap * DAY
    state = compute_state(OBJ, history, as_of)
    assert state.days_since_last == pytest.approx(gap)
    assert state.retention == pytest.approx(retention_expected, abs=TABLE_TOL)
    assert state.score == pytest.approx(score_expected, abs=TABLE_TOL)
    assert state.level is level_expected


# ---------------------------------------------------------------------------
# Section 7 - edge cases
# ---------------------------------------------------------------------------


@pytest.mark.edge
def test_c1_objective_without_attempts():
    state = compute_state(OBJ, [], T0)
    assert state == ObjectiveState(
        objective_id=OBJ,
        as_of=T0,
        level=Level.UNASSESSED,
        score=0.0,
        total_attempts=0,
        correct_attempts=0,
        recent_window=(),
        first_attempt_at=None,
        last_attempt_at=None,
        distinct_days=0,
        days_since_last=None,
        retention=1.0,
        next_review_at=None,
        is_due=False,
    )


@pytest.mark.edge
@pytest.mark.parametrize("correct", [True, False])
def test_c2_a_single_attempt(correct):
    history = [attempt(0, correct, T0)]
    state = compute_state(OBJ, history, T0)
    assert state.level is Level.UNASSESSED
    assert state.score == 0.0
    assert state.total_attempts == 1
    assert state.correct_attempts == int(correct)
    assert state.recent_window == (correct,)
    assert state.first_attempt_at == state.last_attempt_at == T0
    assert state.next_review_at is not None
    assert state.next_review_at > T0


@pytest.mark.edge
def test_c3_two_attempts_on_the_same_day_are_independent_but_one_day():
    history = [
        attempt(0, False, T0),
        attempt(1, True, T0 + timedelta(hours=2)),
    ]
    state = compute_state(OBJ, history, history[-1].at)
    assert state.total_attempts == 2
    assert state.recent_window == (False, True)
    assert state.score == pytest.approx(2 / 3)
    assert state.distinct_days == 1


@pytest.mark.edge
def test_c3_the_exact_same_at_is_tie_broken_by_attempt_id():
    a = attempt(0, True, T0, attempt_id="b")
    b = attempt(1, False, T0, attempt_id="a")
    state = compute_state(OBJ, [a, b], T0)
    # Order: "a" (miss) and then "b" (hit): the hit is the most recent one.
    assert state.recent_window == (False, True)
    assert compute_state(OBJ, [b, a], T0) == state


@pytest.mark.edge
def test_c5_long_gap_with_the_floor():
    history = daily("C" * WINDOW)
    last = history[-1].at
    ninety = compute_state(OBJ, history, last + 90 * DAY)
    assert ninety.retention == pytest.approx(0.5)
    assert ninety.score == pytest.approx(0.5)
    assert ninety.level is Level.WEAK
    year = compute_state(OBJ, history, last + 365 * DAY)
    assert year.retention == RETENTION_FLOOR
    assert year.score == pytest.approx(RETENTION_FLOOR)
    assert year.level is Level.WEAK
    decade = compute_state(OBJ, history, last + 3650 * DAY)
    assert decade.score == year.score
    assert year.is_due is True
    assert year.next_review_at < last + 365 * DAY


@pytest.mark.edge
def test_c6_as_of_before_the_first_attempt_is_equivalent_to_c1():
    history = daily("CCC", T0 + 10 * DAY)
    state = compute_state(OBJ, history, T0)
    assert state == compute_state(OBJ, [], T0)
    assert state.level is Level.UNASSESSED


@pytest.mark.edge
def test_c7_a_future_as_of_is_legal_and_applies_the_future_gap():
    history = daily("C" * WINDOW)
    exam_day = history[-1].at + 30 * DAY
    state = compute_state(OBJ, history, exam_day)
    assert state.total_attempts == WINDOW
    assert state.days_since_last == pytest.approx(30)
    assert state.retention == pytest.approx(0.794, abs=TABLE_TOL)
    assert state.level is Level.LEARNING


@pytest.mark.edge
def test_c10_an_exact_tie_at_the_threshold():
    # One afternoon of history (span 0): step 7 does not interfere.
    history = [attempt(i, True, T0 + i * timedelta(minutes=1)) for i in range(WINDOW)]
    as_of = history[-1].at
    assert compute_level(THRESHOLD_COMPETENT, history, as_of) is Level.COMPETENT
    assert compute_level(THRESHOLD_LEARNING, history, as_of) is Level.LEARNING
    # Rounding to 6 decimals BEFORE the threshold: 0.8499999999 is 0.85.
    assert compute_level(THRESHOLD_COMPETENT - 1e-9, history, as_of) is Level.COMPETENT
    assert compute_level(THRESHOLD_LEARNING - 1e-9, history, as_of) is Level.LEARNING
    # And compute_score returns it already rounded.
    score = compute_score(history, as_of + 21 * DAY)
    assert score == round(score, SCORE_PRECISION)


@pytest.mark.edge
def test_c10_a_rounded_score_produces_a_real_tie():
    # We build a score that, unrounded, would sit ~1e-9 below 0.85 and check
    # that compute_score hands it back rounded to 6 decimals.
    history = daily("C" * WINDOW)
    last = history[-1].at
    target_gap = DECAY_HALF_LIFE_DAYS * (-__import__("math").log2(THRESHOLD_COMPETENT))
    as_of = last + timedelta(days=target_gap)
    score = compute_score(history, as_of)
    assert score == pytest.approx(THRESHOLD_COMPETENT, abs=10 ** -SCORE_PRECISION)
    assert len(str(score).split(".")[1]) <= SCORE_PRECISION


# ---------------------------------------------------------------------------
# I3 / C4 - determinism and independence from insertion order
# ---------------------------------------------------------------------------


@pytest.mark.invariant
def test_i3_permuting_the_insertion_order_gives_the_same_state():
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    as_of = history[-1].at + 5 * DAY
    reference = compute_state(OBJ, history, as_of)
    for permuted in (list(reversed(history)), history[5:] + history[:5], history[::2] + history[1::2]):
        assert compute_state(OBJ, permuted, as_of) == reference
    assert compute_state(OBJ, tuple(history), as_of) == reference


@pytest.mark.invariant
def test_c4_a_late_insertion_changes_the_past_only_through_at():
    history = daily("CCCCC")
    day_4 = history[3].at
    before = compute_state(OBJ, history, day_4)
    late = attempt(99, False, history[2].at + timedelta(hours=1), recorded_at=history[-1].at + 10 * DAY)
    after = compute_state(OBJ, history + [late], day_4)
    assert after.total_attempts == before.total_attempts + 1
    assert after.score < before.score
    # And nothing changes for queries earlier than its ``at``.
    assert compute_state(OBJ, history + [late], history[1].at) == compute_state(OBJ, history, history[1].at)


@pytest.mark.invariant
def test_i10_objective_state_does_not_expose_streak():
    state = compute_state(OBJ, daily("CCC"), T0 + 2 * DAY)
    assert not hasattr(state, "streak")
    assert "streak" not in ObjectiveState.__dataclass_fields__


@pytest.mark.invariant
def test_i5_compute_state_does_not_mutate_the_input():
    history = daily("FCF")
    snapshot = list(history)
    compute_state(OBJ, history, history[-1].at)
    assert history == snapshot


# ------------------------------------- public wrappers vs compute_state


@pytest.mark.invariant
@pytest.mark.parametrize(
    "results", ["", "C", "FFFCF", "FFFCFCCCCC", "CCCCCCCCCCCC", "FCFCFCFCFCFC"]
)
def test_public_wrappers_match_compute_state_on_shuffled_input(results):
    """compute_score and compute_level still work on their own and unsorted.

    compute_state sorts once and delegates to private helpers; the public
    wrappers must give exactly the same result even when they receive the
    history in any order (SPEC section 2.2 step 1, and C4), including a future
    attempt that the cut must ignore.
    """
    history = daily(results) + [attempt(99, True, T0 + 40 * DAY)]
    shuffled = list(reversed(history))
    for as_of in (T0 - DAY, T0 + 2 * DAY, T0 + 12 * DAY, T0 + 30 * DAY):
        state = compute_state(OBJ, shuffled, as_of)
        score = compute_score(shuffled, as_of)
        assert score == state.score
        assert compute_level(score, shuffled, as_of) == state.level
        assert state == compute_state(OBJ, history, as_of)
