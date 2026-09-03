"""Reglas de contrato compartidas por todos los backends.

Orden (SPEC C4), corte por ``at`` (SPEC §5.1), duplicados (SPEC C9) y
validación mínima. Que vivan en un único sitio garantiza que memoria y JSON se
comporten igual: un test que pasa contra uno pasa contra el otro.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from core.errors import DuplicateAttemptError, InvalidAttemptError
from core.models import Attempt, Objective, Profile


def _is_aware(moment: datetime) -> bool:
    return moment.tzinfo is not None and moment.tzinfo.utcoffset(moment) is not None


def validate_attempt(
    profile_id: str, attempt: Attempt, existing: Mapping[str, object]
) -> None:
    """Rechaza intentos mal formados o con ``attempt_id`` repetido.

    Raises:
        InvalidAttemptError: ``profile_id``/``attempt_id``/``objective_id``
            vacíos, ``at`` naive o ``confidence`` fuera de [0, 1].
        DuplicateAttemptError: ya hay un intento con ese id (SPEC C9). Se
            comprueba **antes** de escribir nada: reintentar no duplica.
    """
    if not profile_id:
        raise InvalidAttemptError("profile_id vacío")
    if not attempt.attempt_id:
        raise InvalidAttemptError("attempt_id vacío")
    if not attempt.objective_id:
        raise InvalidAttemptError("objective_id vacío")
    if not isinstance(attempt.at, datetime) or not _is_aware(attempt.at):
        raise InvalidAttemptError(
            f"at debe ser un datetime aware: {attempt.at!r}"
        )
    if attempt.recorded_at is not None and not _is_aware(attempt.recorded_at):
        raise InvalidAttemptError(
            f"recorded_at debe ser aware si se indica: {attempt.recorded_at!r}"
        )
    if attempt.confidence is not None and not 0.0 <= attempt.confidence <= 1.0:
        raise InvalidAttemptError(
            f"confidence fuera de [0, 1]: {attempt.confidence!r}"
        )
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


def sort_attempts(attempts: Iterable[Attempt]) -> list[Attempt]:
    """Orden canónico: ``at`` ascendente, desempate por ``attempt_id`` (C4).

    Nunca por ``recorded_at``: insertar tarde no cambia el resultado.
    """
    return sorted(attempts, key=lambda a: (a.at, a.attempt_id))


def filter_attempts(
    rows: Iterable[tuple[str, Attempt]],
    profile_id: str,
    objective_id: str | None = None,
    until: datetime | None = None,
) -> list[Attempt]:
    """Filtra pares ``(profile_id, attempt)`` por perfil, objetivo y corte.

    El corte es ``at <= until`` (inclusivo), siempre sobre ``at``.
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
