"""Cálculo del nivel. Funciones puras. Ver SPEC.md §2.

Nada aquí toca el store ni el reloj: entran una lista de :class:`Attempt` y un
``as_of``, sale un número o un nivel. Esa pureza es lo que hace el motor
testeable sin infraestructura y lo que garantiza el determinismo (SPEC I3).

**La lógica está en SPEC §2.2, paso a paso y con números.** Si la spec y una
intuición discrepan, gana la spec.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from .constants import (
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
from .models import Attempt, Level, ObjectiveState
from .scheduling import compute_next_review, is_due

def order_attempts(attempts: Sequence[Attempt]) -> list[Attempt]:
    """Ordena por ``at`` ascendente, desempatando por ``attempt_id``.

    El desempate no es cosmético: es lo que hace que insertar los intentos en
    cualquier orden produzca el mismo resultado (SPEC §2.2 paso 1 y C4).

    Args:
        attempts: intentos en cualquier orden.

    Returns:
        Una lista nueva ordenada. No muta la entrada.
    """
    return sorted(attempts, key=lambda a: (a.at, a.attempt_id))


def attempts_until(
    attempts: Sequence[Attempt], as_of: datetime
) -> list[Attempt]:
    """Filtra los intentos con ``at <= as_of`` y los ordena.

    Es la operación que materializa "el estado tal como era en una fecha
    pasada" (SPEC §5.1). Corta por ``at``, **nunca** por ``recorded_at``.

    Args:
        attempts: historial completo del objetivo.
        as_of: fecha de corte, inclusiva.

    Returns:
        Los intentos vigentes en esa fecha, ordenados.
    """
    return order_attempts([a for a in attempts if a.at <= as_of])


def recent_window(attempts: Sequence[Attempt]) -> tuple[bool, ...]:
    """Los últimos ``WINDOW`` (8) resultados, del más antiguo al más reciente.

    Args:
        attempts: intentos ya ordenados y ya cortados por ``as_of``.

    Returns:
        Tupla de booleanos (``True`` = acierto). Vacía si no hay intentos, y
        más corta que ``WINDOW`` si hay menos intentos que eso.
    """
    return tuple(a.correct for a in attempts[-WINDOW:])


def weighted_raw_score(window: Sequence[bool]) -> float:
    """Puntuación cruda ponderada por recencia. SPEC §2.2 pasos 3-4.

    El más reciente de la ventana pesa ``len(window)``, el anterior uno menos,
    y así hasta ``1``. ``raw`` es la suma de los pesos de los aciertos dividida
    por la suma de todos los pesos. Con la ventana llena (8) los pesos son
    ``1..8`` y suman 36; con menos intentos, ``1..n``.

    **El suelo de retención NO se aplica aquí.** ``raw`` puede valer 0.0.

    Args:
        window: resultados del más antiguo al más reciente. **El orden es
            significativo.**

    Returns:
        Un valor en [0.0, 1.0]. Con ventana vacía, ``0.0``.
    """
    if not window:
        return 0.0
    weights = range(1, len(window) + 1)
    correct_weight = sum(w for w, ok in zip(weights, window) if ok)
    return correct_weight / sum(weights)


def retention_factor(
    last_attempt_at: datetime | None, as_of: datetime
) -> float:
    """Decaimiento por inactividad. SPEC §2.2 paso 5.

    ``max(RETENTION_FLOOR, 0.5 ** (gap_en_dias / DECAY_HALF_LIFE_DAYS))``, con
    ``gap`` fraccionario. Si ``gap <= 0`` (o no hay intentos), devuelve ``1.0``.

    El suelo se aplica aquí y solo aquí, **nunca al** ``raw``.

    Returns:
        Un factor en [RETENTION_FLOOR, 1.0].
    """
    if last_attempt_at is None:
        return 1.0
    gap_days = _days_between(last_attempt_at, as_of)
    if gap_days <= 0:
        return 1.0
    return max(RETENTION_FLOOR, 0.5 ** (gap_days / DECAY_HALF_LIFE_DAYS))


def compute_score(attempts: Sequence[Attempt], as_of: datetime) -> float:
    """El ``score`` final de un objetivo. SPEC §2.2 pasos 1-5.

    ``raw * retention``, redondeado a ``SCORE_PRECISION`` decimales para que la
    coma flotante no decida un nivel en el borde de un umbral (SPEC C10).

    Devuelve ``0.0`` si hay menos de ``MIN_ATTEMPTS`` intentos: un solo acierto
    no es evidencia.

    Args:
        attempts: historial del objetivo, en cualquier orden.
        as_of: fecha de corte.

    Returns:
        Un valor en [0.0, 1.0].
    """
    ordered = attempts_until(attempts, as_of)
    if len(ordered) < MIN_ATTEMPTS:
        return 0.0
    raw = weighted_raw_score(recent_window(ordered))
    retention = retention_factor(ordered[-1].at, as_of)
    return round(raw * retention, SCORE_PRECISION)


def distinct_attempt_days(attempts: Sequence[Attempt]) -> int:
    """Cuántos días naturales distintos tienen al menos un intento.

    Compara **fechas naturales**, no instantes: dos intentos del mismo día
    cuentan como un día (SPEC C3). Alimenta la condición de sostenimiento de
    ``MASTERED``.

    El día natural es la **fecha en UTC** del instante ``at``, sea cual sea la
    zona con que se registró (SPEC seccion 2.2 paso 7 y C3). Si se usara la
    fecha en la zona propia de cada intento, dos intentos separados media hora
    pero anotados en zonas distintas podrían contar como dos días, y el
    resultado dependería de cómo se expresó la fecha y no de cuándo ocurrió.
    """
    return len({a.at.astimezone(timezone.utc).date() for a in attempts})


def compute_level(
    score: float, attempts: Sequence[Attempt], as_of: datetime
) -> Level:
    """Traduce ``score`` a :class:`Level`. SPEC §2.2 pasos 2, 6 y 7.

    Umbrales cerrados por abajo (``>=``). Menos de ``MIN_ATTEMPTS`` intentos es
    ``UNASSESSED``. Un ``COMPETENT`` asciende a ``MASTERED`` solo si además
    cumple las tres condiciones de sostenimiento del paso 7.

    Args:
        score: el valor de :func:`compute_score`.
        attempts: se necesitan para las condiciones de sostenimiento.
        as_of: fecha de corte.
    """
    ordered = attempts_until(attempts, as_of)
    if len(ordered) < MIN_ATTEMPTS:
        return Level.UNASSESSED
    score = round(score, SCORE_PRECISION)
    if score < THRESHOLD_LEARNING:
        return Level.WEAK
    if score < THRESHOLD_COMPETENT:
        return Level.LEARNING
    if _is_sustained(ordered):
        return Level.MASTERED
    return Level.COMPETENT


def compute_state(
    objective_id: str, attempts: Sequence[Attempt], as_of: datetime
) -> ObjectiveState:
    """Construye el :class:`ObjectiveState` completo. SPEC §1.5 y §2.

    Función pura: el mismo historial y el mismo ``as_of`` dan siempre el mismo
    estado (SPEC I3, §5.1).

    Args:
        objective_id: identificador del objetivo.
        attempts: historial del objetivo, en cualquier orden. Puede estar vacío
            (caso C1: da ``UNASSESSED``, no un error).
        as_of: fecha de corte. Puede ser anterior al primer intento (C6) o
            futura (C7); ambas son legales.
    """
    ordered = attempts_until(attempts, as_of)
    first_at = ordered[0].at if ordered else None
    last_at = ordered[-1].at if ordered else None
    score = compute_score(ordered, as_of)
    level = compute_level(score, ordered, as_of)
    next_review_at = compute_next_review(ordered, level)
    return ObjectiveState(
        objective_id=objective_id,
        as_of=as_of,
        level=level,
        score=score,
        total_attempts=len(ordered),
        correct_attempts=sum(1 for a in ordered if a.correct),
        recent_window=recent_window(ordered),
        first_attempt_at=first_at,
        last_attempt_at=last_at,
        distinct_days=distinct_attempt_days(ordered),
        days_since_last=(
            _days_between(last_at, as_of) if last_at is not None else None
        ),
        retention=retention_factor(last_at, as_of),
        next_review_at=next_review_at,
        is_due=is_due(next_review_at, as_of),
    )


def _days_between(start: datetime, end: datetime) -> float:
    """Días fraccionarios de ``start`` a ``end`` (negativo si ``end`` es antes)."""
    return (end - start) / timedelta(days=1)


def _is_sustained(ordered: Sequence[Attempt]) -> bool:
    """Las tres condiciones de sostenimiento de SPEC §2.2 paso 7.

    Args:
        ordered: intentos ya ordenados y cortados por ``as_of``, no vacíos.
    """
    raw = weighted_raw_score(recent_window(ordered))
    span = ordered[-1].at - ordered[0].at
    return (
        distinct_attempt_days(ordered) >= MASTERY_MIN_DAYS
        and span >= timedelta(days=MASTERY_MIN_SPAN_DAYS)
        and raw >= MASTERY_MIN_RAW
    )
