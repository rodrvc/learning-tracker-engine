"""Recording session. See SPEC.md section 9.6.

It exists because of failure 4: *nothing forced recording*. An engine cannot
force anyone to run a command, but it can make **not running it visible**. That
is what this class does: a session closed without having recorded anything ends
in state ``EMPTY``, which is an explicit, queryable result rather than a silence
indistinguishable from "all good".
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING
from uuid import uuid4

from .errors import TrackerError
from .models import Attempt, AttemptKind, SessionReport, SessionStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .tracker import LearningTracker


class SessionRecorder:
    """Context manager that groups the attempts of a study session.

    Intended use::

        with tracker.session() as s:
            s.record("D3.2", correct=False, at=when)
            s.record("D3.2", correct=True, at=later)
        report = s.report  # attempts_recorded == 2, status == RECORDED

    And the case that matters::

        with tracker.session() as s:
            pass
        s.report.status  # SessionStatus.EMPTY  <- the session went blank,
                         #    and there is a record of it

    Every attempt is persisted **at the moment** :meth:`record` is called, not
    on close: if the ``with`` block blows up halfway, whatever was already
    recorded stays in the store (I1, append-only) and the exception propagates
    without this object touching it.

    Args:
        tracker: engine the attempts are recorded against.
        session_id: identifier; when ``None`` one is generated.
        started_at: opening instant, injected. ``None`` uses the tracker's
            clock.
    """

    def __init__(
        self,
        tracker: "LearningTracker",
        session_id: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self._tracker = tracker
        self._session_id = uuid4().hex if session_id is None else session_id
        # I2: time arrives through a parameter or through the Clock injected in
        # the tracker. Never the system clock.
        self._started_at = self._now() if started_at is None else started_at
        self._attempts: list[Attempt] = []
        self._report: SessionReport | None = None

    def _now(self) -> datetime:
        """``now()`` of the **tracker's** clock (SPEC I2)."""
        return self._tracker.clock.now()

    @property
    def session_id(self) -> str:
        """Identifier of the session."""
        return self._session_id

    @property
    def started_at(self) -> datetime:
        """Opening instant (injected)."""
        return self._started_at

    def record(
        self,
        objective_id: str,
        correct: bool,
        at: datetime,
        kind: AttemptKind = AttemptKind.QUIZ,
        confidence: float | None = None,
        note: str | None = None,
    ) -> Attempt:
        """Records an attempt inside the session.

        It delegates to :meth:`~core.tracker.LearningTracker.record_attempt` and
        also counts it for the report. If the write fails, the exception
        propagates and the attempt does **not** count: the report never
        overstates.

        The message text of the errors stays in Spanish on purpose: it reaches
        the user through the CLI.
        """
        if self._report is not None:
            raise TrackerError(
                f"la sesión {self._session_id!r} ya está cerrada; no admite intentos"
            )
        # It is persisted NOW (I8): if record_attempt raises, the append below
        # is never reached and the counter does not go up.
        attempt = self._tracker.record_attempt(
            objective_id,
            correct=correct,
            at=at,
            kind=kind,
            confidence=confidence,
            note=note,
        )
        self._attempts.append(attempt)
        return attempt

    def close(self, ended_at: datetime | None = None) -> SessionReport:
        """Closes the session and produces the report.

        Closing an already closed session returns the same report: closing is
        idempotent and the report does not change once issued.

        Args:
            ended_at: closing instant, injected. ``None`` uses the tracker's
                clock.

        Returns:
            A :class:`~core.models.SessionReport` with ``status=RECORDED`` when
            at least one attempt was recorded, or ``EMPTY`` when not. Closing
            blank is a result, not a non-event.
        """
        if self._report is not None:
            return self._report
        touched: list[str] = []
        for attempt in self._attempts:
            if attempt.objective_id not in touched:
                touched.append(attempt.objective_id)
        recorded = len(self._attempts)
        self._report = SessionReport(
            session_id=self._session_id,
            started_at=self._started_at,
            ended_at=self._now() if ended_at is None else ended_at,
            attempts_recorded=recorded,
            objectives_touched=tuple(touched),
            status=SessionStatus.RECORDED if recorded > 0 else SessionStatus.EMPTY,
        )
        return self._report

    @property
    def report(self) -> SessionReport:
        """The report of the session.

        Raises:
            TrackerError: if the session has not been closed yet.
        """
        if self._report is None:
            raise TrackerError(
                f"la sesión {self._session_id!r} aún no se ha cerrado: no hay informe"
            )
        return self._report

    @property
    def attempts_recorded(self) -> int:
        """How many attempts have been recorded so far in this session."""
        return len(self._attempts)

    def __enter__(self) -> "SessionRecorder":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Closes the session. It never suppresses an in-flight exception."""
        self.close()
        return False
