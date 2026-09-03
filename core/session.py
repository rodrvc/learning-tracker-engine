"""Sesión de registro. Ver SPEC.md §9.6.

Existe por el fallo 4: *nada forzaba el registro*. Un motor no puede obligar a
nadie a ejecutar un comando, pero sí puede hacer que **no ejecutarlo sea
visible**. Eso es lo que hace esta clase: una sesión que se cierra sin haber
registrado nada termina en estado ``EMPTY``, que es un resultado explícito y
consultable, no un silencio indistinguible de "todo bien".
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING
from uuid import uuid4

from .errors import TrackerError
from .models import Attempt, AttemptKind, SessionReport, SessionStatus

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from .tracker import LearningTracker


class SessionRecorder:
    """Context manager que agrupa los intentos de una sesión de estudio.

    Uso previsto::

        with tracker.session() as s:
            s.record("D3.2", correct=False, at=cuando)
            s.record("D3.2", correct=True, at=cuando_mas_tarde)
        report = s.report  # attempts_recorded == 2, status == RECORDED

    Y el caso que importa::

        with tracker.session() as s:
            pass
        s.report.status  # SessionStatus.EMPTY  <- la sesión pasó en blanco,
                         #    y queda constancia de ello

    Cada intento se persiste **en el momento** de llamar a :meth:`record`, no
    al cerrar: si el bloque ``with`` revienta a mitad, lo ya registrado se
    queda en el store (I1, append-only) y la excepción se propaga sin que este
    objeto la toque.

    Args:
        tracker: motor sobre el que se registran los intentos.
        session_id: identificador; si es ``None`` se genera uno.
        started_at: instante de apertura, inyectado. ``None`` usa el reloj del
            tracker.
    """

    def __init__(
        self,
        tracker: "LearningTracker",
        session_id: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self._tracker = tracker
        self._session_id = uuid4().hex if session_id is None else session_id
        # I2: el tiempo viene por parámetro o por el Clock inyectado en el
        # tracker. Nunca el reloj de sistema.
        self._started_at = self._now() if started_at is None else started_at
        self._attempts: list[Attempt] = []
        self._report: SessionReport | None = None

    def _now(self) -> datetime:
        """``now()`` del reloj **del tracker** (SPEC I2)."""
        return self._tracker.clock.now()

    @property
    def session_id(self) -> str:
        """Identificador de la sesión."""
        return self._session_id

    @property
    def started_at(self) -> datetime:
        """Instante de apertura (inyectado)."""
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
        """Registra un intento dentro de la sesión.

        Delega en :meth:`~core.tracker.LearningTracker.record_attempt` y además
        lo contabiliza para el informe. Si la escritura falla, la excepción se
        propaga y el intento **no** cuenta: el informe nunca miente al alza.
        """
        if self._report is not None:
            raise TrackerError(
                f"la sesión {self._session_id!r} ya está cerrada; no admite intentos"
            )
        # Se persiste AHORA (I8): si record_attempt lanza, no se llega al
        # append de abajo y el contador no sube.
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
        """Cierra la sesión y produce el informe.

        Cerrar una sesión ya cerrada devuelve el mismo informe: cerrar es
        idempotente y el informe no cambia una vez emitido.

        Args:
            ended_at: instante de cierre, inyectado. ``None`` usa el reloj del
                tracker.

        Returns:
            Un :class:`~core.models.SessionReport` con ``status=RECORDED`` si
            se registró al menos un intento, o ``EMPTY`` si no. Cerrar en
            blanco es un resultado, no un no-evento.
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
        """El informe de la sesión.

        Raises:
            TrackerError: si la sesión aún no se ha cerrado.
        """
        if self._report is None:
            raise TrackerError(
                f"la sesión {self._session_id!r} aún no se ha cerrado: no hay informe"
            )
        return self._report

    @property
    def attempts_recorded(self) -> int:
        """Cuántos intentos se han registrado hasta ahora en esta sesión."""
        return len(self._attempts)

    def __enter__(self) -> "SessionRecorder":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Cierra la sesión. Nunca suprime una excepción en curso."""
        self.close()
        return False
