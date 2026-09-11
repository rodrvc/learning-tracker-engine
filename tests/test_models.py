"""Tests of core/models.py against SPEC.md sections 1 and 9.2, and invariants
I1 and I10.

Conventions:

* ``spec``: the validations section 1.3 demands of an ``Attempt``, and the fact
  that ``confidence``/``weight`` do not affect any computation (section 10).
* ``invariant``: immutability (I1) and absence of ``streak`` (I10).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from core.errors import InvalidAttemptError, TrackerError
from core.leveling import compute_score
from core.models import (
    Attempt,
    AttemptKind,
    ConsistencyCheck,
    ConsistencyReport,
    Level,
    Objective,
    ObjectiveState,
    Profile,
    ProfileSummary,
    SessionReport,
    SessionStatus,
    StateComparison,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
OBJ = "D3.2-content-understanding"

MODEL_TYPES = (
    Profile,
    Objective,
    Attempt,
    ObjectiveState,
    ProfileSummary,
    StateComparison,
    ConsistencyCheck,
    ConsistencyReport,
    SessionReport,
)


def attempt(i: int, correct: bool, **overrides) -> Attempt:
    fields = dict(
        attempt_id=f"a{i:03d}",
        objective_id=OBJ,
        at=T0 + timedelta(days=i),
        correct=correct,
    )
    fields.update(overrides)
    return Attempt(**fields)


def state(**overrides) -> ObjectiveState:
    fields = dict(
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
    fields.update(overrides)
    return ObjectiveState(**fields)


# --------------------------------------------------------------------------
# I1: immutability
# --------------------------------------------------------------------------


@pytest.mark.invariant
def test_i1_attempt_cannot_be_mutated():
    a = attempt(0, True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.correct = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.at = T0 + timedelta(days=1)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del a.note  # type: ignore[misc]
    assert a.correct is True


@pytest.mark.invariant
@pytest.mark.parametrize("model", MODEL_TYPES, ids=lambda t: t.__name__)
def test_i1_every_model_is_frozen(model):
    assert dataclasses.is_dataclass(model)
    assert model.__dataclass_params__.frozen is True


@pytest.mark.invariant
def test_i1_objective_state_cannot_be_mutated():
    s = state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.score = 1.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# I10: no streak
# --------------------------------------------------------------------------


@pytest.mark.invariant
def test_i10_objective_state_does_not_expose_streak():
    names = {f.name for f in dataclasses.fields(ObjectiveState)}
    assert "streak" not in names
    assert not any("streak" in n for n in names)
    assert not hasattr(ObjectiveState, "streak")


@pytest.mark.invariant
def test_i10_objective_stores_no_progress():
    names = {f.name for f in dataclasses.fields(Objective)}
    assert names == {"objective_id", "title", "domain", "weight", "tags"}


@pytest.mark.spec
def test_objective_state_has_the_fields_of_spec_1_5():
    names = {f.name for f in dataclasses.fields(ObjectiveState)}
    required = {
        "objective_id",
        "as_of",
        "level",
        "score",
        "total_attempts",
        "correct_attempts",
        "recent_window",
        "first_attempt_at",
        "last_attempt_at",
        "distinct_days",
        "next_review_at",
        "is_due",
    }
    assert required <= names


# --------------------------------------------------------------------------
# Section 1.4: ordered Level
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_level_is_ordered_and_has_the_spec_values():
    assert [lvl.value for lvl in Level] == [0, 1, 2, 3, 4]
    assert Level.UNASSESSED < Level.WEAK < Level.LEARNING < Level.COMPETENT < Level.MASTERED
    assert Level.MASTERED - Level.WEAK == 3


@pytest.mark.spec
def test_attempt_kind_has_the_five_spec_values():
    assert {k.value for k in AttemptKind} == {
        "quiz",
        "exercise",
        "lab",
        "exam_sim",
        "self_report",
    }


# --------------------------------------------------------------------------
# Section 1.3: Attempt validations
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_a_valid_attempt_is_built_with_defaults():
    a = attempt(0, True)
    assert a.kind is AttemptKind.QUIZ
    assert a.confidence is None
    assert a.note is None
    assert a.recorded_at is None


@pytest.mark.spec
def test_attempt_at_and_recorded_at_are_separate_fields():
    recorded = T0 + timedelta(days=30)
    a = attempt(0, True, recorded_at=recorded)
    assert a.at == T0
    assert a.recorded_at == recorded
    assert a.at != a.recorded_at


@pytest.mark.spec
def test_naive_attempt_at_raises_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, at=datetime(2026, 1, 1, 12, 0))


@pytest.mark.spec
def test_naive_recorded_at_raises_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, recorded_at=datetime(2026, 1, 1, 12, 0))


@pytest.mark.spec
def test_non_datetime_at_raises_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, at="2026-01-01T12:00:00+00:00")


@pytest.mark.spec
@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_objective_id_raises_invalid_attempt(bad):
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, objective_id=bad)


@pytest.mark.spec
@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_attempt_id_raises_invalid_attempt(bad):
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, attempt_id=bad)


@pytest.mark.spec
@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_out_of_range_confidence_raises_invalid_attempt(bad):
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, confidence=bad)


@pytest.mark.spec
@pytest.mark.parametrize("ok", [0.0, 0.5, 1.0, None])
def test_in_range_confidence_is_valid(ok):
    assert attempt(0, True, confidence=ok).confidence == ok


@pytest.mark.spec
def test_invalid_kind_raises_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, kind="quiz")


@pytest.mark.spec
def test_non_bool_correct_raises_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, correct=1)


@pytest.mark.spec
def test_invalid_attempt_error_inherits_from_tracker_error():
    assert issubclass(InvalidAttemptError, TrackerError)


# --------------------------------------------------------------------------
# Section 10: confidence and weight do not affect any computation
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_confidence_does_not_move_the_score():
    results = [False, True, True, False, True, True, True, False, True, True]
    without = [attempt(i, r) for i, r in enumerate(results)]
    with_extras = [
        attempt(i, r, confidence=(0.05 if r else 0.95), kind=AttemptKind.EXAM_SIM)
        for i, r in enumerate(results)
    ]
    as_of = T0 + timedelta(days=len(results))
    assert compute_score(without, as_of) == compute_score(with_extras, as_of)
    assert compute_score(without, as_of) > 0.0


@pytest.mark.spec
def test_objective_weight_is_informational_only():
    """The score computation does not even receive the ``Objective``; its
    ``weight`` cannot influence the level."""
    heavy = Objective(objective_id=OBJ, title="t", weight=10.0)
    light = Objective(objective_id=OBJ, title="t", weight=0.1)
    assert heavy.weight != light.weight
    history = [attempt(i, True) for i in range(5)]
    as_of = T0 + timedelta(days=5)
    # There is no way to pass a weight to compute_score: same history => same score.
    assert compute_score(history, as_of) == compute_score(list(history), as_of)
    assert Objective(objective_id=OBJ, title="t").weight == 1.0


# --------------------------------------------------------------------------
# Sections 1.1 / 1.2: Profile and Objective
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_profile_indexes_objectives_by_id():
    o = Objective(objective_id=OBJ, title="Content understanding", domain="D3")
    p = Profile(profile_id="ai-103", name="Microsoft AI-103", objectives={OBJ: o})
    assert p.objectives[OBJ] is o
    assert Profile(profile_id="x", name="x").objectives == {}


# --------------------------------------------------------------------------
# Sections 9.5 / 8 failure 2: ConsistencyReport.failures
# --------------------------------------------------------------------------


def check(name: str, expected: float, actual: float) -> ConsistencyCheck:
    return ConsistencyCheck(
        name=name, expected=expected, actual=actual, passed=expected == actual
    )


@pytest.mark.spec
def test_consistency_report_failures_returns_only_the_failed_ones():
    ok = check("attempt_count", 5, 5)
    bad = check("correct_sum", 3, 4)
    report = ConsistencyReport(
        ok=False, checks=(ok, bad), objectives_checked=1, as_of=T0
    )
    assert report.failures == (bad,)


@pytest.mark.spec
def test_consistency_report_without_failures_returns_an_empty_tuple():
    report = ConsistencyReport(
        ok=True,
        checks=(check("attempt_count", 5, 5),),
        objectives_checked=1,
        as_of=T0,
    )
    assert report.failures == ()
    assert isinstance(report.failures, tuple)


@pytest.mark.spec
def test_consistency_check_compares_numbers_without_tolerance():
    assert check("attempt_count", 5, 5).passed is True
    assert check("attempt_count", 5, 6).passed is False


# --------------------------------------------------------------------------
# Section 9.6: SessionReport
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_session_report_empty_is_an_explicit_status():
    report = SessionReport(
        session_id="s1",
        started_at=T0,
        ended_at=T0 + timedelta(minutes=5),
        attempts_recorded=0,
        objectives_touched=(),
        status=SessionStatus.EMPTY,
    )
    assert report.status is SessionStatus.EMPTY
    assert SessionStatus.EMPTY != SessionStatus.RECORDED


# --------------------------------------------------------------------------
# Section 5.1: StateComparison
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_state_comparison_keeps_both_states():
    earlier = state(level=Level.WEAK, score=0.3)
    later = state(as_of=T0 + timedelta(days=14), level=Level.COMPETENT, score=0.8)
    cmp = StateComparison(
        objective_id=OBJ,
        earlier=earlier,
        later=later,
        level_delta=later.level - earlier.level,
        score_delta=later.score - earlier.score,
        improved=True,
        regressed=False,
    )
    assert cmp.level_delta == 2
    assert cmp.improved and not cmp.regressed
