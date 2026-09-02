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

from .models import Attempt, AttemptKind, SessionReport

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
        raise NotImplementedError

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
        raise NotImplementedError

    def close(self, ended_at: datetime | None = None) -> SessionReport:
        """Cierra la sesión y produce el informe.

        Args:
            ended_at: instante de cierre, inyectado. ``None`` usa el reloj del
                tracker.

        Returns:
            Un :class:`~core.models.SessionReport` con ``status=RECORDED`` si
            se registró al menos un intento, o ``EMPTY`` si no. Cerrar en
            blanco es un resultado, no un no-evento.
        """
        raise NotImplementedError

    @property
    def report(self) -> SessionReport:
        """El informe de la sesión.

        Raises:
            TrackerError: si la sesión aún no se ha cerrado.
        """
        raise NotImplementedError

    @property
    def attempts_recorded(self) -> int:
        """Cuántos intentos se han registrado hasta ahora en esta sesión."""
        raise NotImplementedError

    def __enter__(self) -> "SessionRecorder":
        raise NotImplementedError

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Cierra la sesión. Nunca suprime una excepción en curso."""
        raise NotImplementedError
