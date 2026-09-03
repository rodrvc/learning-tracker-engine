"""Cálculo del próximo repaso. Funciones puras. Ver SPEC.md §4.

Repetición espaciada con escalera fija ``[1, 3, 7, 14, 30]`` días. El intervalo
se **deriva** del historial en cada consulta: no hay ``ease`` ni ``interval``
almacenado que un bug pueda corromper de forma irreversible. Ese fue el fallo 3
de los sistemas anteriores.
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
    """Aciertos consecutivos al final del historial.

    Cuenta desde el intento más reciente hacia atrás hasta el primer fallo.

    .. warning::
       Esto **no es una medida de progreso** y no debe exponerse como tal. Es
       una variable local del cálculo de intervalo, y nada más. Confundir esta
       cifra con el avance del estudiante fue exactamente el fallo 1: un
       objetivo con cinco respuestas mixtas da ``1`` aquí, indistinguible de
       "no se guardó nada". Para progreso está ``ObjectiveState.score``.

    Args:
        attempts: intentos ya ordenados y cortados por ``as_of``.

    Returns:
        ``0`` si el último intento fue fallo o si no hay intentos.
    """
    run = 0
    for attempt in reversed(attempts):
        if not attempt.correct:
            break
        run += 1
    return run


def interval_days(success_run: int, level: Level) -> int:
    """Días hasta el próximo repaso. SPEC §4.2.

    ``success_run == 0`` (último intento fallido) da el primer peldaño, 1 día.
    A partir de ahí ``índice = min(success_run - 1, 4)`` sobre
    ``SCHEDULE_DAYS``. Si el nivel es ``MASTERED``, el resultado se multiplica
    por ``MASTERY_INTERVAL_MULTIPLIER``, con techo ``MAX_INTERVAL_DAYS``.

    Args:
        success_run: salida de :func:`trailing_success_run`.
        level: nivel actual del objetivo.

    Returns:
        Días, siempre ``>= 1``.
    """
    index = 0 if success_run == 0 else min(success_run - 1, len(SCHEDULE_DAYS) - 1)
    days = SCHEDULE_DAYS[index]
    if level is Level.MASTERED:
        days = min(days * MASTERY_INTERVAL_MULTIPLIER, MAX_INTERVAL_DAYS)
    return days


def compute_next_review(
    attempts: Sequence[Attempt], level: Level
) -> datetime | None:
    """Instante del próximo repaso. SPEC §4.2.

    ``last_attempt_at + interval_days(...)``.

    Args:
        attempts: intentos ya cortados por ``as_of``.
        level: nivel actual, que puede alargar el intervalo si es ``MASTERED``.

    Returns:
        ``None`` si no hay intentos. Un objetivo sin evidencia no está
        "vencido", está sin empezar, y se lista aparte (SPEC §5.2, C1).
    """
    if not attempts:
        return None
    days = interval_days(trailing_success_run(attempts), level)
    return attempts[-1].at + timedelta(days=days)


def is_due(next_review_at: datetime | None, as_of: datetime) -> bool:
    """Si el repaso está vencido en esa fecha.

    ``next_review_at is not None and next_review_at <= as_of``.
    """
    return next_review_at is not None and next_review_at <= as_of
