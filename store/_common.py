"""Reglas de contrato compartidas por todos los backends.

Orden (SPEC C4), corte por ``at`` (SPEC §5.1), duplicados (SPEC C9) y
validación mínima (solo lo que ``Attempt`` no valida por sí mismo). Que vivan en un único sitio garantiza que memoria y JSON se
comporten igual: un test que pasa contra uno pasa contra el otro.
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
    """Rechaza intentos con ``profile_id`` vacío o ``attempt_id`` repetido.

    ``existing`` es cualquier contenedor de ``attempt_id`` ya registrados
    (un ``dict``, un ``set``...): solo se consulta pertenencia.

    La forma del propio ``Attempt`` (ids no vacíos, ``at`` aware,
    ``confidence`` en [0, 1]) la garantiza ``Attempt.__post_init__`` en
    ``core/models.py``: un ``Attempt`` mal formado no llega a construirse.
    Aquí solo queda lo que el modelo no puede saber.

    Raises:
        InvalidAttemptError: ``profile_id`` vacío.
        DuplicateAttemptError: ya hay un intento con ese id (SPEC C9). Se
            comprueba **antes** de escribir nada: reintentar no duplica.
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
    """Fusiona ``objectives`` en el catálogo del perfil (añade o reemplaza).

    Es la mitad pura de ``ProfileStore.upsert_objectives``, compartida por
    los dos backends para que fusionen exactamente igual. El perfil es
    inmutable (``frozen``), así que se devuelve una copia con el catálogo
    actualizado junto con cuántos objetivos se escribieron. Los intentos no
    se tocan: viven en otro store y su ciclo de vida es independiente.

    Raises:
        ValueError: algún objetivo tiene ``objective_id`` vacío. Se valida
            **antes** de fusionar nada: un lote inválido no deja rastro.
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
