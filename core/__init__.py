"""Learning tracking engine. The full contract lives in ``SPEC.md``.

Principles that govern this package:

1. **The attempt history is the only persisted data.** Level, score and next
   review are recalculable projections, never stored state.
2. **Time is injected.** No module under ``core/`` reads the system clock; it
   receives ``as_of`` or a :class:`~core.clock.Clock`.
3. **``core/`` does no I/O.** It only knows the ``Protocol`` types of
   :mod:`core.storage`; the implementations live in ``store/``.

Usual entry point::

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
    # clock
    "Clock",
    "FixedClock",
    "OffsetClock",
    # persistence (interfaces)
    "AttemptStore",
    "ProfileStore",
    # model
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
    # engine
    "LearningTracker",
    "SessionRecorder",
    # errors
    "TrackerError",
    "UnknownProfileError",
    "UnknownObjectiveError",
    "DuplicateAttemptError",
    "InvalidAttemptError",
    "InvalidRangeError",
    "StorageError",
    # contract constants
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
