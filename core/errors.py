"""Engine exceptions.

Every one of them inherits from :class:`TrackerError`, so an integrator can
catch a single class. They exist to make failures **loud**: the contract forbids
returning ``None`` or a neutral value for an operation that could not be
completed (SPEC section 6, I8).
"""

from __future__ import annotations


class TrackerError(Exception):
    """Root of every engine error."""


class UnknownProfileError(TrackerError):
    """The ``profile_id`` does not exist in the store."""


class UnknownObjectiveError(TrackerError):
    """The ``objective_id`` does not exist in the profile.

    Raised both when recording an attempt and when querying state. The engine
    does **not** auto-create objectives: a misspelled id must fail rather than
    conjure a phantom objective (SPEC section 7, C8).
    """


class DuplicateAttemptError(TrackerError):
    """An attempt with that ``attempt_id`` already exists (SPEC section 7, C9)."""


class StorageError(TrackerError):
    """Persistence could not complete the operation.

    Never swallowed: if the attempt was not written, this propagates (SPEC I8).
    """


class InvalidAttemptError(TrackerError):
    """The attempt is malformed.

    For example: ``at`` without a timezone, ``confidence`` outside [0, 1] or an
    empty ``objective_id``.
    """


class InvalidRangeError(TrackerError):
    """A time range is incoherent, e.g. ``start > end`` or ``step <= 0``."""
