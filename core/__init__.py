"""Motor de tracking de aprendizaje. El contrato completo está en ``SPEC.md``.

Principios que gobiernan este paquete:

1. **El historial de intentos es el único dato persistido.** Nivel, score y
   próximo repaso son proyecciones recalculables, nunca estado guardado.
2. **El tiempo se inyecta.** Ningún módulo de ``core/`` consulta el reloj del
   sistema; recibe ``as_of`` o un :class:`~core.clock.Clock`.
3. **``core/`` no hace I/O.** Solo conoce los ``Protocol`` de
   :mod:`core.storage`; las implementaciones viven en ``store/``.

Punto de entrada habitual::

    from core import LearningTracker, FixedClock, AttemptKind
"""

from __future__ import annotations

from .clock import Clock, FixedClock, OffsetClock
from .constants import (
    DECAY_HALF_LIFE_DAYS,
    MASTERY_MIN_DAYS,
    MASTERY_MIN_RAW,
    MASTERY_MIN_SPAN_DAYS,
    MIN_ATTEMPTS,
    RETENTION_FLOOR,
    SCHEDULE_DAYS,
    THRESHOLD_COMPETENT,
    THRESHOLD_LEARNING,
    WINDOW,
)
from .errors import (
    DuplicateAttemptError,
    InvalidAttemptError,
    InvalidRangeError,
    StorageError,
    TrackerError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from .models import (
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
from .session import SessionRecorder
from .storage import AttemptStore, ProfileStore
from .tracker import LearningTracker

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # reloj
    "Clock",
    "FixedClock",
    "OffsetClock",
    # persistencia (interfaces)
    "AttemptStore",
    "ProfileStore",
    # modelo
    "Attempt",
    "AttemptKind",
    "Level",
    "Objective",
    "ObjectiveState",
    "Profile",
    "ProfileSummary",
    "StateComparison",
    "ConsistencyCheck",
    "ConsistencyReport",
    "SessionReport",
    "SessionStatus",
    # motor
    "LearningTracker",
    "SessionRecorder",
    # errores
    "TrackerError",
    "UnknownProfileError",
    "UnknownObjectiveError",
    "DuplicateAttemptError",
    "InvalidAttemptError",
    "InvalidRangeError",
    "StorageError",
    # constantes del contrato
    "WINDOW",
    "MIN_ATTEMPTS",
    "DECAY_HALF_LIFE_DAYS",
    "RETENTION_FLOOR",
    "THRESHOLD_COMPETENT",
    "THRESHOLD_LEARNING",
    "MASTERY_MIN_DAYS",
    "MASTERY_MIN_SPAN_DAYS",
    "MASTERY_MIN_RAW",
    "SCHEDULE_DAYS",
]
