"""Constantes del contrato. Ver SPEC.md §2.1 y §4.1.

Están aquí, con nombre y en un solo sitio, para que ni la implementación ni los
tests las repitan como números mágicos. Cambiar un valor aquí cambia el
contrato: hay que actualizar SPEC.md en el mismo commit.
"""

from __future__ import annotations

from typing import Final

#: Cuántos intentos recientes forman la ventana ponderada (SPEC §2.2 paso 3).
WINDOW: Final[int] = 5

#: Intentos mínimos para salir de UNASSESSED (SPEC §2.2 paso 2).
MIN_ATTEMPTS: Final[int] = 2

#: Días tras los cuales el peso de lo aprendido se reduce a la mitad
#: (SPEC §2.2 paso 5).
DECAY_HALF_LIFE_DAYS: Final[float] = 30.0

#: Umbral inferior de COMPETENT (SPEC §2.2 paso 6). Comparación con >=.
THRESHOLD_COMPETENT: Final[float] = 0.85

#: Umbral inferior de LEARNING (SPEC §2.2 paso 6). Comparación con >=.
THRESHOLD_LEARNING: Final[float] = 0.60

#: Días naturales distintos con intentos exigidos para MASTERED (SPEC §2.2 paso 7).
MASTERY_MIN_DAYS: Final[int] = 2

#: Días entre primer y último intento exigidos para MASTERED (SPEC §2.2 paso 7).
MASTERY_MIN_SPAN_DAYS: Final[int] = 7

#: Escalera de repetición espaciada, en días (SPEC §4.1).
SCHEDULE_DAYS: Final[tuple[int, ...]] = (1, 3, 7, 14, 30)

#: Multiplicador del intervalo cuando el objetivo está MASTERED (SPEC §4.2.5).
MASTERY_INTERVAL_MULTIPLIER: Final[int] = 2

#: Techo del intervalo de repaso en días (SPEC §4.2.5).
MAX_INTERVAL_DAYS: Final[int] = 60

#: Decimales a los que se redondea el score antes de aplicar umbrales,
#: para que la coma flotante no decida un nivel (SPEC §7 C10).
SCORE_PRECISION: Final[int] = 6

#: Días por defecto sin actividad para considerar un objetivo "stale"
#: (SPEC §9.4, defensa del fallo 4).
DEFAULT_STALE_DAYS: Final[int] = 14
