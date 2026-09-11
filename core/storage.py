"""The persistence interfaces.

``core/`` does not know whether a JSON file, SQLite or memory sits behind them.
It only knows these two ``Protocol`` types. The concrete implementations live in
``store/``.

The important detail of the contract: :class:`AttemptStore` **has no update or
delete methods**. That is not an omission, it is guarantee I1 (append-only
history) turned into structure: an attempt cannot be corrupted through an API
that offers no way to touch it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

from .models import Attempt, Objective, Profile


@runtime_checkable
class AttemptStore(Protocol):
    """Persistence of attempts. It only appends and reads.

    Every implementation must guarantee:

    * ``append`` is atomic: either the attempt is written and readable, or
      :class:`~core.errors.StorageError` is raised. Never a silent half success
      (SPEC I8).
    * ``append`` rejects an already existing ``attempt_id`` with
      :class:`~core.errors.DuplicateAttemptError` (SPEC C9).
    * Read methods return attempts **sorted by ascending ``at``, breaking ties
      by ``attempt_id``**, so that the write order is irrelevant (SPEC C4).
    """

    def append(self, profile_id: str, attempt: Attempt) -> Attempt:
        """Persists an attempt under a profile and returns it as stored.

        ``profile_id`` travels in the call and not inside
        :class:`~core.models.Attempt` (SPEC section 1.3 does not include it):
        the store is what indexes by profile, exactly as in
        ``list_for_objective``, ``list_all`` and ``count``.

        Raises:
            DuplicateAttemptError: if the ``attempt_id`` already exists, in
                **any** profile (SPEC C9).
            StorageError: if the write could not be completed.
        """
        ...

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Attempts of an objective, sorted, with ``at <= until`` when given.

        ``until`` is the time cut that makes the historical query possible
        (SPEC section 5.1). ``None`` means "all of them".
        """
        ...

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Every attempt of the profile, sorted, with an optional cut."""
        ...

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Number of attempts.

        It exists as a method of its own so that the consistency check can
        compare **counts** from the store against recomputed counts, without
        materializing lists or comparing sets (SPEC I9).
        """
        ...

    def exists(self, attempt_id: str) -> bool:
        """Whether an attempt with that id already exists."""
        ...


@runtime_checkable
class ProfileStore(Protocol):
    """Persistence of profiles and their objectives.

    Kept apart from :class:`AttemptStore` because their life cycles differ: the
    objective catalog gets edited, the attempt history never does.
    """

    def get_profile(self, profile_id: str) -> Profile:
        """Returns the profile.

        Raises:
            UnknownProfileError: if it does not exist.
        """
        ...

    def save_profile(self, profile: Profile) -> Profile:
        """Creates or replaces a profile and returns the persisted result."""
        ...

    def list_profiles(self) -> list[Profile]:
        """Every known profile."""
        ...

    def get_objective(self, profile_id: str, objective_id: str) -> Objective:
        """Returns one objective of the profile.

        Raises:
            UnknownProfileError: if the profile does not exist.
            UnknownObjectiveError: if the objective does not exist in it.
        """
        ...

    def list_objectives(self, profile_id: str) -> list[Objective]:
        """Objectives of the profile, sorted by ``objective_id``."""
        ...

    def upsert_objectives(
        self, profile_id: str, objectives: Iterable[Objective]
    ) -> int:
        """Adds or updates objectives. Returns how many were written."""
        ...
