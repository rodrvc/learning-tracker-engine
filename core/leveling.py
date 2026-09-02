"""Cálculo del nivel. Funciones puras. Ver SPEC.md §2.

Nada aquí toca el store ni el reloj: entran una lista de :class:`Attempt` y un
``as_of``, sale un número o un nivel. Esa pureza es lo que hace el motor
testeable sin infraestructura y lo que garantiza el determinismo (SPEC I3).

**La lógica está en SPEC §2.2, paso a paso y con números.** Estos stubs solo
fijan las firmas. Quien implemente debe seguir la spec literalmente; si la spec
y una intuición discrepan, gana la spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .models import Attempt, Level, ObjectiveState


def order_attempts(attempts: Sequence[Attempt]) -> list[Attempt]:
    """Ordena por ``at`` ascendente, desempatando por ``attempt_id``.

    El desempate no es cosmético: es lo que hace que insertar los intentos en
    cualquier orden produzca el mismo resultado (SPEC §2.2 paso 1 y C4).

    Args:
        attempts: intentos en cualquier orden.

    Returns:
        Una lista nueva ordenada. No muta la entrada.
    """
    raise NotImplementedError


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
    raise NotImplementedError


def recent_window(attempts: Sequence[Attempt]) -> tuple[bool, ...]:
    """Los últimos ``WINDOW`` resultados, del más antiguo al más reciente.

    Args:
        attempts: intentos ya ordenados y ya cortados por ``as_of``.

    Returns:
        Tupla de booleanos (``True`` = acierto). Vacía si no hay intentos, y
        más corta que ``WINDOW`` si hay menos intentos que eso.
    """
    raise NotImplementedError


def weighted_raw_score(window: Sequence[bool]) -> float:
    """Puntuación cruda ponderada por recencia. SPEC §2.2 pasos 3-4.

    El más reciente de la ventana pesa ``len(window)``, el anterior uno menos,
    y así hasta ``1``. ``raw`` es la suma de los pesos de los aciertos dividida
    por la suma de todos los pesos.

    Ponderar por recencia es lo que hace que la tendencia se vea: un fallo
    reciente duele más que uno antiguo, sin necesidad de reiniciar nada.

    Args:
        window: resultados del más antiguo al más reciente. **El orden es
            significativo.**

    Returns:
        Un valor en [0.0, 1.0]. Con ventana vacía, ``0.0``.
    """
    raise NotImplementedError


def retention_factor(
    last_attempt_at: datetime | None, as_of: datetime
) -> float:
    """Decaimiento por inactividad. SPEC §2.2 paso 5.

    ``0.5 ** (gap_en_dias / DECAY_HALF_LIFE_DAYS)``, con ``gap`` fraccionario.
    Si ``gap <= 0`` (o no hay intentos), devuelve ``1.0``.

    Modela que el conocimiento se oxida: un objetivo perfecto sin tocar en 60
    días vale un cuarto. Es lo que permite que ``MASTERED`` se pierda sin
    registrar ningún intento nuevo, solo por el paso del tiempo.

    Returns:
        Un factor en (0.0, 1.0].
    """
    raise NotImplementedError


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
    raise NotImplementedError


def distinct_attempt_days(attempts: Sequence[Attempt]) -> int:
    """Cuántos días naturales distintos tienen al menos un intento.

    Compara **fechas naturales**, no instantes: dos intentos del mismo día
    cuentan como un día (SPEC C3). Alimenta la condición de sostenimiento de
    ``MASTERED``.
    """
    raise NotImplementedError


def compute_level(
    score: float, attempts: Sequence[Attempt], as_of: datetime
) -> Level:
    """Traduce ``score`` a :class:`Level`. SPEC §2.2 pasos 2, 6 y 7.

    Umbrales cerrados por abajo (``>=``): ``0.85`` es ``COMPETENT``, ``0.60``
    es ``LEARNING``, por debajo ``WEAK``, y menos de ``MIN_ATTEMPTS`` intentos
    es ``UNASSESSED``.

    Un ``COMPETENT`` asciende a ``MASTERED`` solo si además cumple las tres
    condiciones de sostenimiento del paso 7: ``distinct_days >= 2``, span entre
    primer y último intento ``>= 7`` días, y ninguna falla en la ventana. No se
    domina algo en una tarde.

    Args:
        score: el valor de :func:`compute_score`.
        attempts: se necesitan para las condiciones de sostenimiento.
        as_of: fecha de corte.
    """
    raise NotImplementedError


def compute_state(
    objective_id: str, attempts: Sequence[Attempt], as_of: datetime
) -> ObjectiveState:
    """Construye el :class:`ObjectiveState` completo. SPEC §1.5 y §2.

    Es la función central del motor: todo lo demás la envuelve. Función pura,
    luego el mismo historial y el mismo ``as_of`` dan siempre el mismo estado,
    hoy y dentro de un año (SPEC I3, §5.1).

    Args:
        objective_id: identificador del objetivo.
        attempts: historial del objetivo, en cualquier orden. Puede estar vacío
            (caso C1: da ``UNASSESSED``, no un error).
        as_of: fecha de corte. Puede ser anterior al primer intento (C6) o
            futura (C7); ambas son legales.
    """
    raise NotImplementedError
