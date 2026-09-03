"""Tests de ``core/session.py`` contra SPEC.md §9.6, §8 (fallo 4), §6 (I1, I2, I8).

Convenciones:

* ``spec``: contrato de cada método de ``SessionRecorder`` (§9.6).
* ``invariant``: I1 (lo ya registrado no se pierde), I2 (tiempo inyectado),
  I8 (un intento fallido no cuenta).
* ``edge``: sesión vacía, cierre repetido, registro tras el cierre.

Todo corre sobre ``InMemory*`` con ``FixedClock``: la fecha nunca depende de
cuándo se ejecuta la suite (I2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.clock import FixedClock
from core.errors import (
    InvalidAttemptError,
    StorageError,
    TrackerError,
    UnknownObjectiveError,
)
from core.models import (
    Attempt,
    AttemptKind,
    Objective,
    Profile,
    SessionReport,
    SessionStatus,
)
from core.session import SessionRecorder
from core.tracker import LearningTracker
from store import InMemoryAttemptStore, InMemoryProfileStore

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
PID = "ai-103"
O1, O2, O3 = "D1.1-a", "D1.2-b", "D2.1-c"
NOW = T0 + DAY * 10


def d(n: int) -> datetime:
    return T0 + DAY * n


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def profiles() -> InMemoryProfileStore:
    store = InMemoryProfileStore()
    store.save_profile(
        Profile(
            profile_id=PID,
            name="AI-103",
            objectives={o: Objective(objective_id=o, title=o) for o in (O1, O2, O3)},
        )
    )
    return store


@pytest.fixture
def attempts() -> InMemoryAttemptStore:
    return InMemoryAttemptStore()


@pytest.fixture
def tracker(profiles, attempts) -> LearningTracker:
    return LearningTracker(PID, profiles, attempts, FixedClock(NOW))


# --------------------------------------------------------------- __init__


@pytest.mark.spec
def test_init_uses_given_id_and_started_at(tracker):
    s = SessionRecorder(tracker, session_id="s-1", started_at=d(3))
    assert s.session_id == "s-1"
    assert s.started_at == d(3)
    assert s.attempts_recorded == 0


@pytest.mark.invariant
def test_init_defaults_come_from_tracker_clock_not_system_time(tracker):
    """I2: ``started_at=None`` usa el reloj inyectado en el tracker."""
    s = SessionRecorder(tracker)
    assert s.started_at == NOW
    assert s.session_id  # generado, no vacío


@pytest.mark.spec
def test_generated_ids_are_unique(tracker):
    assert SessionRecorder(tracker).session_id != SessionRecorder(tracker).session_id


# ----------------------------------------------------------------- record


@pytest.mark.spec
def test_record_delegates_to_tracker_and_returns_persisted_attempt(tracker, attempts):
    s = SessionRecorder(tracker, "s-1")
    written = s.record(
        O1, correct=True, at=d(0), kind=AttemptKind.LAB, confidence=0.5, note="n"
    )
    assert isinstance(written, Attempt)
    assert written.objective_id == O1
    assert written.at == d(0)
    assert written.correct is True
    assert written.kind is AttemptKind.LAB
    assert written.confidence == 0.5
    assert written.note == "n"
    assert written.recorded_at == NOW
    assert attempts.list_for_objective(PID, O1) == [written]
    assert s.attempts_recorded == 1


@pytest.mark.invariant
def test_record_persists_immediately_not_on_close(tracker, attempts):
    """I1/I8: cada intento queda en el store en el momento, no al cerrar."""
    s = SessionRecorder(tracker, "s-1")
    s.record(O1, correct=False, at=d(0))
    s.record(O2, correct=True, at=d(1))
    assert attempts.count(PID) == 2  # sin haber cerrado


@pytest.mark.invariant
def test_record_failure_propagates_and_does_not_count(profiles, attempts):
    """I8: si la escritura falla, la excepción sale y el informe no miente al alza."""

    class BrokenStore(InMemoryAttemptStore):
        def append(self, profile_id, attempt):
            raise StorageError("disco lleno")

    tracker = LearningTracker(PID, profiles, BrokenStore(), FixedClock(NOW))
    s = SessionRecorder(tracker, "s-1")
    with pytest.raises(StorageError):
        s.record(O1, correct=True, at=d(0))
    assert s.attempts_recorded == 0
    assert s.close().status is SessionStatus.EMPTY


@pytest.mark.spec
@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"objective_id": "nope", "at": d(0)}, UnknownObjectiveError),
        ({"objective_id": O1, "at": datetime(2026, 1, 1)}, InvalidAttemptError),
        ({"objective_id": O1, "at": d(0), "confidence": 1.5}, InvalidAttemptError),
    ],
)
def test_record_invalid_attempt_raises_and_does_not_count(tracker, attempts, kwargs, error):
    s = SessionRecorder(tracker, "s-1")
    with pytest.raises(error):
        s.record(correct=True, **kwargs)
    assert s.attempts_recorded == 0
    assert attempts.count(PID) == 0


@pytest.mark.edge
def test_record_after_close_raises(tracker, attempts):
    s = SessionRecorder(tracker, "s-1")
    s.close()
    with pytest.raises(TrackerError):
        s.record(O1, correct=True, at=d(0))
    assert attempts.count(PID) == 0
    assert s.report.attempts_recorded == 0


# ------------------------------------------------------------------ close


@pytest.mark.spec
def test_close_produces_recorded_report(tracker):
    s = SessionRecorder(tracker, "s-1", started_at=d(5))
    s.record(O1, correct=False, at=d(0))
    s.record(O1, correct=True, at=d(1))
    report = s.close(ended_at=d(6))
    assert report == SessionReport(
        session_id="s-1",
        started_at=d(5),
        ended_at=d(6),
        attempts_recorded=2,
        objectives_touched=(O1,),
        status=SessionStatus.RECORDED,
    )


@pytest.mark.spec
def test_close_empty_session_is_visible_as_empty(tracker):
    """§8 fallo 4 / §9.6: cerrar en blanco es un resultado explícito, no un no-evento."""
    s = SessionRecorder(tracker, "s-1", started_at=d(5))
    report = s.close(ended_at=d(6))
    assert report.status is SessionStatus.EMPTY
    assert report.attempts_recorded == 0
    assert report.objectives_touched == ()
    assert report.started_at == d(5)
    assert report.ended_at == d(6)
    assert s.report is report  # y queda consultable después


@pytest.mark.invariant
def test_close_default_ended_at_comes_from_tracker_clock(tracker):
    """I2: ``ended_at=None`` usa el reloj inyectado en el tracker."""
    s = SessionRecorder(tracker, "s-1")
    assert s.close().ended_at == NOW


@pytest.mark.spec
def test_objectives_touched_counts_distinct_objectives(tracker):
    s = SessionRecorder(tracker, "s-1")
    s.record(O2, correct=True, at=d(0))
    s.record(O1, correct=False, at=d(1))
    s.record(O2, correct=True, at=d(2))
    s.record(O1, correct=True, at=d(3))
    s.record(O3, correct=True, at=d(4))
    report = s.close()
    assert report.attempts_recorded == 5
    assert len(report.objectives_touched) == 3
    assert set(report.objectives_touched) == {O1, O2, O3}
    assert report.objectives_touched == (O2, O1, O3)  # orden de primer toque


@pytest.mark.edge
def test_close_is_idempotent(tracker):
    s = SessionRecorder(tracker, "s-1")
    s.record(O1, correct=True, at=d(0))
    first = s.close(ended_at=d(6))
    second = s.close(ended_at=d(9))
    assert second is first
    assert second.ended_at == d(6)


# ----------------------------------------------------------------- report


@pytest.mark.spec
def test_report_before_close_raises(tracker):
    s = SessionRecorder(tracker, "s-1")
    with pytest.raises(TrackerError):
        s.report
    s.record(O1, correct=True, at=d(0))
    with pytest.raises(TrackerError):
        s.report


@pytest.mark.spec
def test_report_after_close_is_the_closed_report(tracker):
    s = SessionRecorder(tracker, "s-1")
    report = s.close()
    assert s.report is report


# ------------------------------------------------------- attempts_recorded


@pytest.mark.spec
def test_attempts_recorded_grows_with_each_record(tracker):
    s = SessionRecorder(tracker, "s-1")
    assert s.attempts_recorded == 0
    s.record(O1, correct=True, at=d(0))
    assert s.attempts_recorded == 1
    s.record(O1, correct=True, at=d(1))
    assert s.attempts_recorded == 2


# -------------------------------------------------------- context manager


@pytest.mark.spec
def test_enter_returns_self_and_exit_closes(tracker):
    recorder = SessionRecorder(tracker, "s-1")
    with recorder as s:
        assert s is recorder
        s.record(O1, correct=True, at=d(0))
        with pytest.raises(TrackerError):
            s.report  # aún abierta
    assert s.report.status is SessionStatus.RECORDED
    assert s.report.attempts_recorded == 1


@pytest.mark.spec
def test_with_empty_block_ends_as_empty(tracker):
    with SessionRecorder(tracker, "s-1") as s:
        pass
    assert s.report.status is SessionStatus.EMPTY


@pytest.mark.invariant
def test_exception_inside_with_propagates_and_keeps_recorded_attempts(tracker, attempts):
    """I1 + §9.6: el ``with`` revienta a mitad; lo ya escrito se queda y la
    excepción sale sin que ``__exit__`` la trague."""

    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with SessionRecorder(tracker, "s-1") as s:
            s.record(O1, correct=True, at=d(0))
            s.record(O2, correct=False, at=d(1))
            raise Boom("a mitad")
    assert attempts.count(PID) == 2
    assert {a.objective_id for a in attempts.list_all(PID)} == {O1, O2}
    # La sesión quedó cerrada e informa lo que sí se registró.
    assert s.report.status is SessionStatus.RECORDED
    assert s.report.attempts_recorded == 2


@pytest.mark.invariant
def test_exit_never_suppresses_exceptions(tracker):
    s = SessionRecorder(tracker, "s-1")
    s.__enter__()
    try:
        raise ValueError("x")
    except ValueError as exc:
        assert s.__exit__(ValueError, exc, exc.__traceback__) is False
    assert s.__exit__(None, None, None) is False


@pytest.mark.spec
def test_tracker_session_factory_returns_functional_recorder(tracker, attempts):
    """§9.4 / §9.6: ``tracker.session()`` entrega un recorder real."""
    with tracker.session("s-9") as s:
        assert isinstance(s, SessionRecorder)
        s.record(O1, correct=True, at=d(0))
    assert s.session_id == "s-9"
    assert s.report.status is SessionStatus.RECORDED
    assert attempts.count(PID) == 1
    assert tracker.get_state(O1).total_attempts == 1
