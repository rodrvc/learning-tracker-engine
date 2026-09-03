"""Tests de ``core/tracker.py`` contra SPEC.md §5, §9.4, §9.5, §6 y §7.

Convenciones:

* ``spec``: contrato de cada método de la tabla §9.4 y de §9.5.
* ``invariant``: I4 (derivación total), I5 (monotonía del corte), I6
  (reconstrucción), I8 (registro verificable), I9 (consistencia por conteo).
* ``edge``: C4, C6, C7, C8, C9.

Todo corre sobre ``InMemory*`` con ``FixedClock`` / ``OffsetClock``: la fecha
nunca depende de cuándo se ejecuta la suite (I2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.clock import FixedClock, OffsetClock
from core.constants import DEFAULT_STALE_DAYS
from core.errors import (
    DuplicateAttemptError,
    InvalidAttemptError,
    InvalidRangeError,
    StorageError,
    UnknownObjectiveError,
)
from core.leveling import compute_state
from core.models import (
    Attempt,
    AttemptKind,
    ConsistencyReport,
    Level,
    Objective,
    ObjectiveState,
    Profile,
    SessionStatus,
    StateComparison,
)
from core.session import SessionRecorder
from core.tracker import LearningTracker
from store import InMemoryAttemptStore, InMemoryProfileStore

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
PID = "ai-103"
O1, O2, O3, O4 = "D1.1-a", "D1.2-b", "D2.1-c", "D2.2-d"
ALL_OBJECTIVES = (O1, O2, O3, O4)


def d(n: int) -> datetime:
    """``T0 + n`` días."""
    return T0 + DAY * n


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def profiles() -> InMemoryProfileStore:
    store = InMemoryProfileStore()
    store.save_profile(
        Profile(
            profile_id=PID,
            name="AI-103",
            objectives={o: Objective(objective_id=o, title=o) for o in ALL_OBJECTIVES},
        )
    )
    return store


@pytest.fixture
def attempts() -> InMemoryAttemptStore:
    return InMemoryAttemptStore()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(d(10))


@pytest.fixture
def tracker(profiles, attempts, clock) -> LearningTracker:
    return LearningTracker(PID, profiles, attempts, clock)


# ------------------------------------------------------------------ clock


@pytest.mark.spec
def test_clock_property_is_the_injected_clock(profiles, attempts, clock):
    """§9.4 / I2: ``tracker.clock`` es exactamente el ``Clock`` inyectado."""
    tracker = LearningTracker(PID, profiles, attempts, clock)
    assert tracker.clock is clock
    assert tracker.clock.now() == d(10)


# --------------------------------------------------------- record_attempt


@pytest.mark.spec
def test_record_attempt_returns_persisted_attempt_from_store(tracker, attempts):
    """§9.4 / I8: devuelve el Attempt tal como quedó en el store, con su id."""
    written = tracker.record_attempt(
        O1, correct=True, at=d(0), kind=AttemptKind.LAB, confidence=0.5, note="n",
        attempt_id="x1",
    )
    assert isinstance(written, Attempt)
    assert written.attempt_id == "x1"
    assert written.objective_id == O1
    assert written.at == d(0)
    assert written.correct is True
    assert written.kind is AttemptKind.LAB
    assert written.confidence == 0.5
    assert written.note == "n"
    assert attempts.list_for_objective(PID, O1) == [written]


@pytest.mark.spec
def test_record_attempt_generates_unique_ids_when_none(tracker):
    a = tracker.record_attempt(O1, correct=True, at=d(0))
    b = tracker.record_attempt(O1, correct=True, at=d(0))
    assert a.attempt_id and b.attempt_id
    assert a.attempt_id != b.attempt_id


@pytest.mark.spec
def test_record_attempt_stamps_recorded_at_from_injected_clock(tracker, clock):
    """``recorded_at`` sale del Clock inyectado, nunca del sistema (I2)."""
    written = tracker.record_attempt(O1, correct=True, at=d(0))
    assert written.recorded_at == clock.now()


@pytest.mark.spec
def test_record_attempt_rejects_naive_at(tracker):
    with pytest.raises(InvalidAttemptError):
        tracker.record_attempt(O1, correct=True, at=datetime(2026, 1, 1))


@pytest.mark.spec
def test_record_attempt_rejects_confidence_out_of_range(tracker):
    with pytest.raises(InvalidAttemptError):
        tracker.record_attempt(O1, correct=True, at=d(0), confidence=1.5)


@pytest.mark.edge
def test_c8_unknown_objective_raises_and_is_not_autocreated(tracker, profiles, attempts):
    with pytest.raises(UnknownObjectiveError):
        tracker.record_attempt("typo", correct=True, at=d(0))
    assert "typo" not in profiles.get_profile(PID).objectives
    assert attempts.count(PID) == 0


@pytest.mark.edge
def test_c9_duplicate_attempt_id_raises_and_keeps_single_copy(tracker, attempts):
    tracker.record_attempt(O1, correct=True, at=d(0), attempt_id="dup")
    with pytest.raises(DuplicateAttemptError):
        tracker.record_attempt(O1, correct=False, at=d(1), attempt_id="dup")
    with pytest.raises(DuplicateAttemptError):
        tracker.record_attempt(O2, correct=False, at=d(1), attempt_id="dup")
    assert attempts.count(PID) == 1
    assert attempts.list_all(PID)[0].correct is True


class _FailingAppendStore(InMemoryAttemptStore):
    """Store cuya escritura falla siempre: simula un disco roto."""

    def append(self, profile_id, attempt):
        raise StorageError("disco lleno")


@pytest.mark.invariant
def test_i8_failed_write_propagates_and_records_nothing(profiles, clock):
    broken = _FailingAppendStore()
    tracker = LearningTracker(PID, profiles, broken, clock)
    with pytest.raises(StorageError):
        tracker.record_attempt(O1, correct=True, at=d(0), attempt_id="x")
    assert broken.count(PID) == 0
    assert not broken.exists("x")
    assert tracker.get_state(O1).total_attempts == 0


class _SilentStore(InMemoryAttemptStore):
    """Store que "acepta" y no escribe: el tracker no debe disimularlo."""

    def append(self, profile_id, attempt):
        return None


@pytest.mark.invariant
def test_i8_record_attempt_returns_exactly_what_store_returned(profiles, clock):
    """El tracker no fabrica un éxito: devuelve lo que el store devolvió."""
    silent = _SilentStore()
    tracker = LearningTracker(PID, profiles, silent, clock)
    assert tracker.record_attempt(O1, correct=True, at=d(0)) is None


# ---------------------------------------------------------- record_series


@pytest.mark.spec
def test_record_series_spaces_attempts_by_step(tracker, attempts):
    results = [False, False, False, True, False]
    written = tracker.record_series(O1, results, start=d(0), step=DAY, kind=AttemptKind.EXAM_SIM)
    assert [a.correct for a in written] == results
    assert [a.at for a in written] == [d(i) for i in range(5)]
    assert all(a.kind is AttemptKind.EXAM_SIM for a in written)
    assert attempts.list_for_objective(PID, O1) == written


@pytest.mark.spec
def test_record_series_unknown_objective_raises(tracker):
    with pytest.raises(UnknownObjectiveError):
        tracker.record_series("nope", [True], start=d(0))


# ---------------------------------------------------------------- session


@pytest.mark.spec
def test_session_returns_working_session_recorder(tracker, attempts):
    """§9.6: ``session()`` devuelve un ``SessionRecorder`` real y funcional.

    Los internos del recorder se prueban en ``test_session.py``; aquí solo que
    la factoría del tracker entrega el objeto correcto, con el id pedido y
    ``started_at`` tomado del reloj del tracker.
    """
    recorder = tracker.session("s-1")
    assert isinstance(recorder, SessionRecorder)
    assert recorder.session_id == "s-1"
    assert recorder.started_at == d(10)
    with recorder as s:
        s.record(O1, correct=True, at=d(0))
    assert s.report.status is SessionStatus.RECORDED
    assert s.report.attempts_recorded == 1
    assert attempts.count(PID) == 1


@pytest.mark.spec
def test_session_generates_id_when_none(tracker):
    a, b = tracker.session(), tracker.session()
    assert a.session_id and b.session_id
    assert a.session_id != b.session_id


# ------------------------------------------------- get_level / get_state


@pytest.mark.spec
def test_get_level_unknown_objective_raises(tracker):
    with pytest.raises(UnknownObjectiveError):
        tracker.get_level("nope")
    with pytest.raises(UnknownObjectiveError):
        tracker.get_state("nope")


@pytest.mark.spec
def test_get_level_without_attempts_is_unassessed_not_error(tracker):
    """C1: existe pero sin intentos → UNASSESSED."""
    assert tracker.get_level(O1) is Level.UNASSESSED
    state = tracker.get_state(O1)
    assert state.total_attempts == 0
    assert state.next_review_at is None


@pytest.mark.spec
def test_get_level_matches_get_state_level(tracker):
    tracker.record_series(O1, [True, True], start=d(0))
    assert tracker.get_level(O1, d(1)) is tracker.get_state(O1, d(1)).level
    assert tracker.get_level(O1, d(1)) is Level.COMPETENT


@pytest.mark.spec
def test_as_of_none_uses_injected_clock_now(profiles, attempts):
    """§9.4: ``as_of=None`` significa ``clock.now()``; con FixedClock es fijo."""
    tracker = LearningTracker(PID, profiles, attempts, FixedClock(d(3)))
    tracker.record_series(O1, [True, True, True, True], start=d(0))
    assert tracker.get_state(O1).as_of == d(3)
    assert tracker.get_state(O1).total_attempts == 4
    assert tracker.get_state(O1) == tracker.get_state(O1, d(3))
    assert tracker.get_all_states()[0].as_of == d(3)
    assert tracker.get_summary().as_of == d(3)
    assert tracker.check_consistency().as_of == d(3)


@pytest.mark.spec
def test_offset_clock_moves_the_default_as_of(profiles, attempts):
    base = FixedClock(d(0))
    early = LearningTracker(PID, profiles, attempts, base)
    early.record_series(O1, [True, True], start=d(0))
    later = LearningTracker(PID, profiles, attempts, OffsetClock(base, DAY * 30))
    assert early.get_state(O1).as_of == d(0)
    assert later.get_state(O1).as_of == d(30)
    assert later.get_state(O1).is_due is True
    assert early.get_state(O1).is_due is False


@pytest.mark.invariant
def test_i4_get_state_is_compute_state_over_store_contents(tracker, attempts):
    """I4: el tracker envuelve ``compute_state``; no calcula nada aparte."""
    tracker.record_series(O1, [False, True, True, False, True], start=d(0))
    for as_of in (d(-1), d(0), d(2), d(4), d(40)):
        expected = compute_state(
            O1, attempts.list_for_objective(PID, O1, until=as_of), as_of
        )
        assert tracker.get_state(O1, as_of) == expected
        assert tracker.get_state_at(O1, as_of) == expected


@pytest.mark.invariant
def test_i4_state_has_no_streak_field(tracker):
    """I10 de rebote: el estado que devuelve el tracker no expone racha."""
    tracker.record_series(O1, [True, True], start=d(0))
    assert not hasattr(tracker.get_state(O1), "streak")


# ------------------------------------------------------------ get_state_at


@pytest.mark.spec
def test_get_state_at_ignores_attempts_after_as_of(tracker):
    """§5.1: todo intento con ``at > as_of`` se ignora."""
    tracker.record_series(O1, [True, True, False, False], start=d(0))
    assert tracker.get_state_at(O1, d(1)).total_attempts == 2
    assert tracker.get_state_at(O1, d(1)).level is Level.COMPETENT
    assert tracker.get_state_at(O1, d(3)).total_attempts == 4


@pytest.mark.spec
def test_get_state_at_does_not_change_when_later_attempts_arrive(tracker):
    """§5.1: reproducibilidad histórica — lo pasado no se reescribe."""
    tracker.record_series(O1, [True, True], start=d(0))
    before = tracker.get_state_at(O1, d(1))
    tracker.record_series(O1, [False] * 5, start=d(2))
    assert tracker.get_state_at(O1, d(1)) == before


@pytest.mark.spec
def test_get_state_at_is_insensitive_to_write_order(profiles, clock):
    """§5.1: registrar en cualquier orden da los mismos estados."""
    series = [(d(i), r) for i, r in enumerate([False, True, True, False, True])]

    def build(order):
        attempts = InMemoryAttemptStore()
        t = LearningTracker(PID, profiles, attempts, clock)
        for i in order:
            at, r = series[i]
            t.record_attempt(O1, correct=r, at=at, attempt_id=f"a{i}")
        return t

    forward = build([0, 1, 2, 3, 4])
    shuffled = build([3, 0, 4, 1, 2])
    for n in range(-1, 7):
        assert forward.get_state_at(O1, d(n)) == shuffled.get_state_at(O1, d(n))


@pytest.mark.edge
def test_c4_late_insertion_changes_state_on_that_date_but_not_before(profiles, attempts):
    """C4: insertar con ``at`` antiguo y ``recorded_at`` reciente.

    El estado en ``día 4`` cambia (se añadió información sobre el pasado) y
    eso es correcto; los estados anteriores a ``at`` no cambian.
    """
    tracker = LearningTracker(PID, profiles, attempts, FixedClock(d(0)))
    tracker.record_attempt(O1, correct=True, at=d(1), attempt_id="d1")
    tracker.record_attempt(O1, correct=True, at=d(5), attempt_id="d5")
    before_day4 = tracker.get_state_at(O1, d(4))
    before_day2 = tracker.get_state_at(O1, d(2))
    before_day0 = tracker.get_state_at(O1, d(0))
    assert before_day4.total_attempts == 1
    assert before_day4.level is Level.UNASSESSED

    late = LearningTracker(PID, profiles, attempts, FixedClock(d(100)))
    inserted = late.record_attempt(O1, correct=True, at=d(3), attempt_id="d3")
    assert inserted.recorded_at == d(100)
    assert inserted.at == d(3)

    after_day4 = tracker.get_state_at(O1, d(4))
    assert after_day4.total_attempts == 2
    assert after_day4.level is Level.COMPETENT
    assert after_day4 != before_day4
    # Anterior a at=d(3): nada cambia.
    assert tracker.get_state_at(O1, d(2)) == before_day2
    assert tracker.get_state_at(O1, d(0)) == before_day0
    # El corte es por at, nunca por recorded_at: el intento con recorded_at
    # d(100) cuenta en d(4).
    assert tracker.get_state_at(O1, d(4)).last_attempt_at == d(3)


@pytest.mark.edge
def test_c6_as_of_before_first_attempt_is_unassessed(tracker):
    tracker.record_series(O1, [True, True, True], start=d(5))
    state = tracker.get_state_at(O1, d(2))
    assert state.level is Level.UNASSESSED
    assert state.score == 0.0
    assert state.total_attempts == 0
    assert state.first_attempt_at is None
    assert state.is_due is False


@pytest.mark.edge
def test_c7_as_of_in_the_future_applies_decay(tracker):
    tracker.record_series(O1, [True, True], start=d(0))
    now_state = tracker.get_state_at(O1, d(1))
    future = tracker.get_state_at(O1, d(200))
    assert future.total_attempts == 2
    assert future.days_since_last == pytest.approx(199.0)
    assert future.retention < now_state.retention
    assert future.score < now_state.score
    assert future.is_due is True


@pytest.mark.invariant
def test_i5_attempt_set_is_monotone_in_as_of_but_level_is_not(tracker, attempts):
    """I5: t1 <= t2 ⇒ intentos(t1) ⊆ intentos(t2). El nivel no es monótono."""
    tracker.record_series(O1, [True, True, False, False, False], start=d(0))
    cuts = [d(n) for n in range(-1, 8)]
    for t1, t2 in zip(cuts, cuts[1:]):
        ids1 = {a.attempt_id for a in attempts.list_for_objective(PID, O1, until=t1)}
        ids2 = {a.attempt_id for a in attempts.list_for_objective(PID, O1, until=t2)}
        assert ids1 <= ids2
        s1, s2 = tracker.get_state_at(O1, t1), tracker.get_state_at(O1, t2)
        assert s1.total_attempts <= s2.total_attempts
    # Nivel NO monótono: COMPETENT en d(1), WEAK en d(2) tras el fallo.
    assert tracker.get_level(O1, d(1)) is Level.COMPETENT
    assert tracker.get_level(O1, d(2)) is Level.WEAK
    assert tracker.get_level(O1, d(2)) < tracker.get_level(O1, d(1))


# ---------------------------------------------------------- get_all_states


@pytest.mark.spec
def test_get_all_states_covers_every_objective_ordered_by_id(tracker):
    tracker.record_series(O3, [True, True], start=d(0))
    states = tracker.get_all_states(d(1))
    assert [s.objective_id for s in states] == sorted(ALL_OBJECTIVES)
    assert all(isinstance(s, ObjectiveState) for s in states)
    assert all(s.as_of == d(1) for s in states)
    by_id = {s.objective_id: s for s in states}
    assert by_id[O3].total_attempts == 2
    assert by_id[O1].total_attempts == 0


# ----------------------------------------------------------------- get_due


@pytest.mark.spec
def test_get_due_orders_most_overdue_first_then_score_then_id(tracker):
    """§5.2: vencido mayor primero; empate → score menor; empate → id asc."""
    # O2: next_review = d(2) + 1 = d(3)  (run de aciertos 0 → 1 día)
    tracker.record_series(O2, [True, True, False], start=d(0))
    # O1: next_review = d(1) + 3 = d(4); score alto
    tracker.record_series(O1, [True, True], start=d(0))
    # O3: next_review = d(1) + 3 = d(4); score más bajo que O1 (dos fallos)
    tracker.record_series(O3, [False, False, True, True], start=d(-2))
    # O4: sin intentos → nunca vencido
    as_of = d(20)
    due = tracker.get_due(as_of)
    assert [s.objective_id for s in due] == [O2, O3, O1]
    assert all(s.is_due for s in due)
    assert due[1].next_review_at == due[2].next_review_at == d(4)
    assert due[1].score < due[2].score


@pytest.mark.spec
def test_get_due_breaks_full_ties_by_objective_id(tracker):
    tracker.record_series(O3, [True, True], start=d(0))
    tracker.record_series(O1, [True, True], start=d(0))
    assert [s.objective_id for s in tracker.get_due(d(20))] == [O1, O3]


@pytest.mark.spec
def test_get_due_excludes_unstarted_and_not_yet_due(tracker):
    tracker.record_series(O1, [True, True], start=d(0))  # next d(4)
    assert tracker.get_due(d(3)) == []
    assert [s.objective_id for s in tracker.get_due(d(4))] == [O1]
    assert O4 not in {s.objective_id for s in tracker.get_due(d(400))}


@pytest.mark.spec
def test_get_due_respects_limit_and_default_clock(tracker):
    tracker.record_series(O2, [True, True, False], start=d(0))
    tracker.record_series(O1, [True, True], start=d(0))
    assert [s.objective_id for s in tracker.get_due(limit=1)] == [O2]
    assert len(tracker.get_due()) == 2  # clock = d(10): ambos vencidos
    assert tracker.get_due(limit=0) == []


# ---------------------------------------------------------- get_unstarted


@pytest.mark.spec
def test_get_unstarted_lists_objectives_without_attempts_until_as_of(tracker):
    tracker.record_series(O1, [True], start=d(5))
    assert [s.objective_id for s in tracker.get_unstarted(d(6))] == [O2, O3, O4]
    # Antes del primer intento de O1, también O1 está sin empezar (C6).
    assert [s.objective_id for s in tracker.get_unstarted(d(4))] == list(sorted(ALL_OBJECTIVES))
    assert all(s.level is Level.UNASSESSED for s in tracker.get_unstarted())


# -------------------------------------------------------------- get_stale


@pytest.mark.spec
def test_get_stale_uses_default_stale_days_and_excludes_unstarted(tracker):
    tracker.record_series(O1, [True], start=d(0))
    tracker.record_series(O2, [True], start=d(0))
    tracker.record_series(O2, [True], start=d(10))
    at = d(DEFAULT_STALE_DAYS + 1)
    assert [s.objective_id for s in tracker.get_stale(at)] == [O1]
    # Exactamente en el umbral no es stale (estrictamente mayor).
    assert tracker.get_stale(d(DEFAULT_STALE_DAYS)) == []
    # Con as_of anterior a la segunda actividad de O2, O2 también es stale:
    # el corte es por at (§5.1).
    assert [s.objective_id for s in tracker.get_stale(d(DEFAULT_STALE_DAYS + 1), days=5)] == [O1]
    assert [s.objective_id for s in tracker.get_stale(d(9), days=5)] == [O1, O2]
    # Los sin intentos nunca aparecen aquí: van en get_unstarted.
    assert O3 not in {s.objective_id for s in tracker.get_stale(d(500))}


@pytest.mark.spec
def test_get_stale_with_explicit_days_and_default_clock(tracker):
    tracker.record_series(O1, [True], start=d(0))  # clock = d(10)
    assert [s.objective_id for s in tracker.get_stale(days=3)] == [O1]
    assert tracker.get_stale(days=30) == []


# ------------------------------------------------------------ get_timeline


@pytest.mark.spec
def test_get_timeline_is_get_state_at_over_a_grid(tracker):
    tracker.record_series(O1, [False, False, False, True, False], start=d(0))
    timeline = tracker.get_timeline(O1, start=d(-1), end=d(5), step=DAY)
    assert [s.as_of for s in timeline] == [d(n) for n in range(-1, 6)]
    for state in timeline:
        assert state == tracker.get_state_at(O1, state.as_of)
    assert [s.total_attempts for s in timeline] == [0, 1, 2, 3, 4, 5, 5]


@pytest.mark.spec
def test_get_timeline_grid_stops_at_end(tracker):
    tl = tracker.get_timeline(O1, start=d(0), end=d(0) + timedelta(hours=30), step=timedelta(hours=12))
    assert [s.as_of for s in tl] == [d(0) + timedelta(hours=h) for h in (0, 12, 24)]
    assert len(tracker.get_timeline(O1, start=d(0), end=d(0))) == 1


@pytest.mark.spec
def test_get_timeline_rejects_bad_ranges(tracker):
    with pytest.raises(InvalidRangeError):
        tracker.get_timeline(O1, start=d(2), end=d(1))
    with pytest.raises(InvalidRangeError):
        tracker.get_timeline(O1, start=d(0), end=d(1), step=timedelta(0))
    with pytest.raises(InvalidRangeError):
        tracker.get_timeline(O1, start=d(0), end=d(1), step=-DAY)
    with pytest.raises(UnknownObjectiveError):
        tracker.get_timeline("nope", start=d(0), end=d(1))


# ---------------------------------------------------------- compare_states


@pytest.mark.spec
def test_compare_states_detects_improvement(tracker):
    tracker.record_series(O1, [False, False, True, True, True, True], start=d(0))
    cmp = tracker.compare_states(O1, earlier=d(1), later=d(5))
    assert isinstance(cmp, StateComparison)
    assert cmp.earlier == tracker.get_state_at(O1, d(1))
    assert cmp.later == tracker.get_state_at(O1, d(5))
    assert cmp.level_delta == int(cmp.later.level) - int(cmp.earlier.level) > 0
    assert cmp.score_delta == pytest.approx(cmp.later.score - cmp.earlier.score)
    assert cmp.improved is True and cmp.regressed is False


@pytest.mark.spec
def test_compare_states_detects_regression_two_weeks_ago(tracker):
    """La pregunta del usuario: ¿hace dos semanas estaba mejor?"""
    tracker.record_series(O1, [True, True], start=d(0))
    today = d(15)
    cmp = tracker.compare_states(O1, earlier=today - DAY * 14, later=today)
    assert cmp.regressed is True and cmp.improved is False
    assert cmp.score_delta < 0
    assert cmp.level_delta == 0


@pytest.mark.spec
def test_compare_states_equal_dates_and_bad_range(tracker):
    cmp = tracker.compare_states(O1, earlier=d(1), later=d(1))
    assert cmp.score_delta == 0 and not cmp.improved and not cmp.regressed
    with pytest.raises(InvalidRangeError):
        tracker.compare_states(O1, earlier=d(2), later=d(1))


# ------------------------------------------------------------- get_summary


@pytest.mark.spec
def test_get_summary_aggregates_profile(tracker):
    tracker.record_series(O1, [True, True], start=d(0))        # COMPETENT, due en d(10)
    tracker.record_series(O2, [True, True, False], start=d(0))  # WEAK, due
    tracker.record_series(O3, [True], start=d(10))             # UNASSESSED (n<2), no due
    tracker.record_series(O3, [True], start=d(30))             # fuera del corte
    summary = tracker.get_summary(d(10))
    states = {s.objective_id: s for s in tracker.get_all_states(d(10))}
    assert summary.profile_id == PID
    assert summary.as_of == d(10)
    assert summary.total_objectives == 4
    assert set(summary.by_level) == set(Level)
    assert summary.by_level[Level.COMPETENT] == 1
    assert summary.by_level[Level.WEAK] == 1
    assert summary.by_level[Level.UNASSESSED] == 2
    assert summary.by_level[Level.LEARNING] == 0
    assert summary.by_level[Level.MASTERED] == 0
    assert summary.assessed_objectives == 2
    assert summary.unstarted_objectives == 1
    assert summary.due_objectives == 2
    assert summary.total_attempts == 6
    assert summary.mean_score == pytest.approx(sum(s.score for s in states.values()) / 4)
    assert summary.coverage == pytest.approx(0.5)


@pytest.mark.spec
def test_get_summary_empty_profile_has_zero_coverage(profiles, attempts, clock):
    profiles.save_profile(Profile(profile_id="empty", name="e"))
    summary = LearningTracker("empty", profiles, attempts, clock).get_summary()
    assert summary.total_objectives == 0
    assert summary.coverage == 0.0
    assert summary.mean_score == 0.0
    assert summary.by_level == {level: 0 for level in Level}


@pytest.mark.spec
def test_get_profile_returns_the_profile(tracker, profiles):
    assert tracker.get_profile() == profiles.get_profile(PID)
    assert tracker.profile_id == PID


# ------------------------------------------------------ check_consistency


@pytest.mark.spec
def test_check_consistency_ok_on_healthy_store(tracker):
    tracker.record_series(O1, [True, False, True], start=d(0))
    tracker.record_series(O2, [False], start=d(0))
    report = tracker.check_consistency(d(10))
    assert isinstance(report, ConsistencyReport)
    assert report.ok is True
    assert report.objectives_checked == 4
    assert report.failures == ()
    assert report.as_of == d(10)
    names = {c.name for c in report.checks}
    assert {"attempt_count", "correct_sum", "unique_attempt_ids", "orphan_attempts",
            "store_count", "profile_attempt_count", "profile_correct_sum"} <= names
    counts = {c.detail: c for c in report.checks if c.name == "attempt_count"}
    o1 = next(c for det, c in counts.items() if det.startswith(O1))
    assert (o1.expected, o1.actual) == (3, 3)
    total = next(c for c in report.checks if c.name == "profile_correct_sum")
    assert (total.expected, total.actual) == (2, 2)


@pytest.mark.spec
def test_check_consistency_reports_numbers_on_both_sides(tracker):
    """§9.5: cada check lleva expected y actual numéricos, no conjuntos."""
    tracker.record_series(O1, [True, True], start=d(0))
    for check in tracker.check_consistency().checks:
        assert isinstance(check.expected, (int, float))
        assert isinstance(check.actual, (int, float))
        assert check.passed == (check.expected == check.actual)


@pytest.mark.spec
def test_check_consistency_not_ok_with_zero_objectives(profiles, attempts, clock):
    """Un reporte vacío no es verde: ok exige objectives_checked >= 1."""
    profiles.save_profile(Profile(profile_id="empty", name="e"))
    report = LearningTracker("empty", profiles, attempts, clock).check_consistency()
    assert report.objectives_checked == 0
    assert report.failures == ()
    assert report.ok is False


class _DuplicatingListStore(InMemoryAttemptStore):
    """Store corrupto: ``list_all`` devuelve un intento dos veces."""

    def list_all(self, profile_id, until=None):
        listed = super().list_all(profile_id, until)
        return listed + listed[:1] if listed else listed


class _LyingCountStore(InMemoryAttemptStore):
    """Store corrupto: ``count`` devuelve uno más de lo que hay."""

    def count(self, profile_id, objective_id=None):
        return super().count(profile_id, objective_id) + 1


@pytest.mark.invariant
def test_i9_detects_count_mismatch_from_duplicated_listing(profiles, clock):
    store = _DuplicatingListStore()
    tracker = LearningTracker(PID, profiles, store, clock)
    tracker.record_series(O1, [True, True], start=d(0))
    report = tracker.check_consistency()
    assert report.ok is False
    failed = {c.name for c in report.failures}
    # Un comparador de conjuntos no vería nada: el duplicado es el mismo id.
    assert "unique_attempt_ids" in failed
    assert "attempt_count" in failed or "profile_attempt_count" in failed
    dup = next(c for c in report.failures if c.name == "unique_attempt_ids")
    assert (dup.expected, dup.actual) == (3, 2)


@pytest.mark.invariant
def test_i9_detects_lying_count(profiles, clock):
    store = _LyingCountStore()
    tracker = LearningTracker(PID, profiles, store, clock)
    tracker.record_series(O1, [True], start=d(0))
    report = tracker.check_consistency()
    assert report.ok is False
    lie = next(c for c in report.failures if c.name == "store_count")
    assert (lie.expected, lie.actual) == (1, 2)


@pytest.mark.invariant
def test_i9_detects_orphan_attempts(profiles, clock):
    store = InMemoryAttemptStore()
    tracker = LearningTracker(PID, profiles, store, clock)
    tracker.record_series(O1, [True], start=d(0))
    # Escribir directamente en el store, saltándose C8 del tracker.
    store.append(PID, Attempt("orphan", "ghost", d(0), True))
    report = tracker.check_consistency()
    assert report.ok is False
    orphan = next(c for c in report.failures if c.name == "orphan_attempts")
    assert (orphan.expected, orphan.actual) == (0, 1)


# ----------------------------------------------------------------- rebuild


@pytest.mark.invariant
def test_i6_rebuild_recomputes_every_objective_and_changes_nothing(tracker):
    tracker.record_series(O1, [False, True, True], start=d(0))
    tracker.record_series(O2, [True], start=d(0))
    before = tracker.get_all_states(d(10))
    assert tracker.rebuild(d(10)) == len(ALL_OBJECTIVES)
    assert tracker.get_all_states(d(10)) == before
    assert tracker.rebuild() == len(ALL_OBJECTIVES)
    assert tracker.check_consistency(d(10)).ok is True


@pytest.mark.invariant
def test_i6_rebuild_after_dropping_a_cache_gives_identical_state(tracker):
    """Si alguna implementación cacheara, borrar y recalcular es idéntico."""
    tracker.record_series(O1, [True, True, False, True], start=d(0))
    snapshot = [tracker.get_state_at(O1, d(n)) for n in range(6)]
    for attr in list(vars(tracker)):
        if "cache" in attr:
            setattr(tracker, attr, None)
    tracker.rebuild(d(5))
    assert [tracker.get_state_at(O1, d(n)) for n in range(6)] == snapshot
