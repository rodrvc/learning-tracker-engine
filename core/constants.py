"""Contract constants. See SPEC.md sections 2.1 and 4.1.

They live here, named and in a single place, so that neither the implementation
nor the tests repeat them as magic numbers. Changing a value here changes the
contract: SPEC.md must be updated in the same commit.
"""

from __future__ import annotations

from typing import Final

#: How many recent attempts make up the weighted window (SPEC section 2.2, step 3).
#: 8 and not 5: the user answers isolated questions, not full exams, and with a
#: short window a single answer moved the level too much.
WINDOW: Final[int] = 8

#: Minimum attempts required to leave UNASSESSED (SPEC section 2.2, step 2).
MIN_ATTEMPTS: Final[int] = 2

#: Days after which the weight of what was learned is halved
#: (SPEC section 2.2, step 5). 90 and not 30: study spreads over months and a
#: short half-life sank a topic for a single month without touching it.
DECAY_HALF_LIFE_DAYS: Final[float] = 90.0

#: Floor of the retention factor (SPEC section 2.2, step 5). It applies ONLY to
#: ``retention``, NEVER to ``raw``. That is what lets the score tell
#: "I abandoned it" (high raw x 0.40) apart from "I don't know it" (low raw).
RETENTION_FLOOR: Final[float] = 0.40

#: Lower threshold of COMPETENT (SPEC section 2.2, step 6). Compared with >=.
THRESHOLD_COMPETENT: Final[float] = 0.85

#: Lower threshold of LEARNING (SPEC section 2.2, step 6). Compared with >=.
THRESHOLD_LEARNING: Final[float] = 0.60

#: Distinct calendar days with attempts required for MASTERED (SPEC section 2.2, step 7).
MASTERY_MIN_DAYS: Final[int] = 2

#: Minimum ``raw`` to be promoted to MASTERED (SPEC section 2.2, step 7). It is
#: 0.95 and not 1.0 because with a window of 8, demanding perfection would force
#: 8 consecutive hits and purging any miss would take 8 more attempts. See SPEC
#: section 2.4.
MASTERY_MIN_RAW: Final[float] = 0.95

#: Days between first and last attempt required for MASTERED (SPEC section 2.2, step 7).
MASTERY_MIN_SPAN_DAYS: Final[int] = 7

#: Spaced repetition ladder, in days (SPEC section 4.1).
SCHEDULE_DAYS: Final[tuple[int, ...]] = (1, 3, 7, 14, 30)

#: Interval multiplier when the objective is MASTERED (SPEC section 4.2.5).
MASTERY_INTERVAL_MULTIPLIER: Final[int] = 2

#: Ceiling of the review interval, in days (SPEC section 4.2.5).
MAX_INTERVAL_DAYS: Final[int] = 60

#: Decimals the score is rounded to before applying thresholds, so that floating
#: point does not decide a level (SPEC section 7, C10).
SCORE_PRECISION: Final[int] = 6

#: Default days without activity before an objective counts as "stale"
#: (SPEC section 9.4, defense against failure 4).
DEFAULT_STALE_DAYS: Final[int] = 14
