"""In-memory backend. The reference implementation of the ``Protocol`` types.

It persists nothing across processes: it serves the tests, the verification bot,
and acts as the mirror any other backend is checked against. All the contract
logic (order, cut, duplicates, isolation between profiles) lives in
:mod:`store._common` and is shared with the JSON backend, so both behave exactly
the same.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from core.errors import UnknownObjectiveError, UnknownProfileError
from core.models import Attempt, Objective, Profile

from ._common import (
    filter_attempts,
    merge_objectives,
    sort_attempts,
    validate_attempt,
    validate_profile,
)


class InMemoryAttemptStore:
    """In-memory ``AttemptStore``. It only appends and reads (SPEC I1).

    Note what is **not** here: no ``update``, no ``remove``, no ``clear``. The
    absence is the guarantee.
    """

    def __init__(self) -> None:
        # attempt_id -> (profile_id, attempt). A single global index by id, so
        # that C9 (duplicate) is detected across profiles.
        self._by_id: dict[str, tuple[str, Attempt]] = {}

    def append(self, profile_id: str, attempt: Attempt) -> Attempt:
        """Persists an attempt. See :meth:`core.storage.AttemptStore.append`."""
        validate_attempt(profile_id, attempt, self._by_id)
        self._by_id[attempt.attempt_id] = (profile_id, attempt)
        return attempt

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Attempts of an objective, sorted by ``at`` and ``attempt_id``."""
        return sort_attempts(
            filter_attempts(self._by_id.values(), profile_id, objective_id, until)
        )

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Every attempt of the profile, sorted, with an optional cut."""
        return sort_attempts(
            filter_attempts(self._by_id.values(), profile_id, None, until)
        )

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Number of attempts of the profile (or of the objective, when given)."""
        return sum(
            1 for _ in filter_attempts(self._by_id.values(), profile_id, objective_id)
        )

    def exists(self, attempt_id: str) -> bool:
        """Whether an attempt with that id already exists, in any profile."""
        return attempt_id in self._by_id


class InMemoryProfileStore:
    """In-memory ``ProfileStore``."""

    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}

    def get_profile(self, profile_id: str) -> Profile:
        """Returns the profile or raises ``UnknownProfileError``."""
        try:
            return self._profiles[profile_id]
        except KeyError:
            raise UnknownProfileError(profile_id) from None

    def save_profile(self, profile: Profile) -> Profile:
        """Creates or replaces a whole profile, objectives included."""
        validate_profile(profile)
        self._profiles[profile.profile_id] = profile
        return profile

    def list_profiles(self) -> list[Profile]:
        """Every profile, sorted by ``profile_id``."""
        return [self._profiles[k] for k in sorted(self._profiles)]

    def get_objective(self, profile_id: str, objective_id: str) -> Objective:
        """One objective of the profile. It fails loudly when missing (SPEC C8)."""
        profile = self.get_profile(profile_id)
        try:
            return profile.objectives[objective_id]
        except KeyError:
            raise UnknownObjectiveError(f"{profile_id}/{objective_id}") from None

    def list_objectives(self, profile_id: str) -> list[Objective]:
        """Objectives of the profile, sorted by ``objective_id``."""
        objectives = self.get_profile(profile_id).objectives
        return [objectives[k] for k in sorted(objectives)]

    def upsert_objectives(
        self, profile_id: str, objectives: Iterable[Objective]
    ) -> int:
        """Adds or replaces objectives of the profile. Returns how many it wrote.

        The merge lives in :func:`store._common.merge_objectives`, shared with
        the JSON backend.
        """
        profile = self.get_profile(profile_id)
        self._profiles[profile_id], written = merge_objectives(profile, objectives)
        return written
