"""Contract rules shared by every backend.

Order (SPEC C4), cut by ``at`` (SPEC section 5.1), duplicates (SPEC C9) and
minimal validation (only what ``Attempt`` does not validate by itself). Keeping
them in a single place guarantees that memory and JSON behave the same: a test
that passes against one passes against the other.

Exception message texts stay in Spanish: they can reach the user through the
CLI.
"""

from __future__ import annotations

from collections.abc import Container
from datetime import datetime
from typing import Iterable

from core.errors import DuplicateAttemptError, InvalidAttemptError
from core.models import Attempt, Objective, Profile


def validate_attempt(
    profile_id: str, attempt: Attempt, existing: Container[str]
) -> None:
    """Rejects attempts with an empty ``profile_id`` or a repeated ``attempt_id``.

    ``existing`` is any container of already registered ``attempt_id`` values (a
    ``dict``, a ``set``...): only membership is queried.

    The shape of the ``Attempt`` itself (non-empty ids, aware ``at``,
    ``confidence`` in [0, 1]) is guaranteed by ``Attempt.__post_init__`` in
    ``core/models.py``: a malformed ``Attempt`` never gets constructed. Only what
    the model cannot know is left here.

    Raises:
        InvalidAttemptError: empty ``profile_id``.
        DuplicateAttemptError: an attempt with that id already exists (SPEC C9).
            It is checked **before** writing anything: retrying does not
            duplicate.
    """
    if not profile_id:
        raise InvalidAttemptError("profile_id vacío")
    if attempt.attempt_id in existing:
        raise DuplicateAttemptError(attempt.attempt_id)


def validate_profile(profile: Profile) -> None:
    if not profile.profile_id:
        raise ValueError("profile_id vacío")
    for key, objective in profile.objectives.items():
        validate_objective(objective)
        if key != objective.objective_id:
            raise ValueError(
                f"clave {key!r} no coincide con objective_id {objective.objective_id!r}"
            )


def validate_objective(objective: Objective) -> None:
    if not objective.objective_id:
        raise ValueError("objective_id vacío")


def merge_objectives(
    profile: Profile, objectives: Iterable[Objective]
) -> tuple[Profile, int]:
    """Merges ``objectives`` into the profile catalog (adds or replaces).

    It is the pure half of ``ProfileStore.upsert_objectives``, shared by both
    backends so that they merge exactly alike. The profile is immutable
    (``frozen``), so a copy with the updated catalog is returned together with
    how many objectives were written. Attempts are not touched: they live in
    another store and their life cycle is independent.

    Raises:
        ValueError: some objective has an empty ``objective_id``. It is
            validated **before** merging anything: an invalid batch leaves no
            trace.
    """
    incoming = list(objectives)
    for objective in incoming:
        validate_objective(objective)
    merged = dict(profile.objectives)
    for objective in incoming:
        merged[objective.objective_id] = objective
    return (
        Profile(profile_id=profile.profile_id, name=profile.name, objectives=merged),
        len(incoming),
    )


def sort_attempts(attempts: Iterable[Attempt]) -> list[Attempt]:
    """Canonical order: ascending ``at``, tie broken by ``attempt_id`` (C4).

    Never by ``recorded_at``: inserting late does not change the result.
    """
    return sorted(attempts, key=lambda a: (a.at, a.attempt_id))


def filter_attempts(
    rows: Iterable[tuple[str, Attempt]],
    profile_id: str,
    objective_id: str | None = None,
    until: datetime | None = None,
) -> list[Attempt]:
    """Filters ``(profile_id, attempt)`` pairs by profile, objective and cut.

    The cut is ``at <= until`` (inclusive), always over ``at``.
    """
    out: list[Attempt] = []
    for row_profile, attempt in rows:
        if row_profile != profile_id:
            continue
        if objective_id is not None and attempt.objective_id != objective_id:
            continue
        if until is not None and attempt.at > until:
            continue
        out.append(attempt)
    return out
