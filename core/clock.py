"""The time abstraction.

Hard rule of the contract (SPEC section 6, I2): **no module under ``core/``
calls ``datetime.now()``**. Time enters through a parameter (``as_of``) or
through an injected :class:`Clock`. It is verifiable from the outside with a
grep over ``core/``.

The real clock (``SystemClock``) deliberately lives in ``store/``, outside
``core/``, so that grep has no false positives and so that using the system
clock from the engine by accident is impossible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Source of "now".

    The only door to real time in the whole system. Implementations must return
    a **timezone-aware** ``datetime``; a naive datetime makes attempts
    incomparable and is forbidden by the contract.
    """

    def now(self) -> datetime:
        """The current instant, aware (with ``tzinfo``)."""
        ...


@dataclass(frozen=True)
class FixedClock:
    """A clock that always returns the same instant.

    The tool the tests use: pin the date and the engine's result stops depending
    on when the suite runs.

    Args:
        moment: aware instant that ``now()`` will return.
    """

    moment: datetime

    def now(self) -> datetime:
        """Returns :attr:`moment`, always the same."""
        return self.moment


@dataclass(frozen=True)
class OffsetClock:
    """A base clock shifted by a fixed amount of time.

    It makes it possible to simulate the calendar moving forward without
    waiting: wrapping a :class:`FixedClock` with ``offset=timedelta(days=30)``
    answers the question "what will this look like a month from now?".

    Args:
        base: clock the shift is applied to.
        offset: how far forward (positive) or backward (negative) it moves.
    """

    base: Clock
    offset: timedelta

    def now(self) -> datetime:
        """``base.now() + offset``."""
        return self.base.now() + self.offset

    def advanced(self, delta: timedelta) -> "OffsetClock":
        """A new clock with an additional ``delta`` of shift.

        Immutable: it does not modify this clock, it returns another one.
        """
        return OffsetClock(base=self.base, offset=self.offset + delta)
