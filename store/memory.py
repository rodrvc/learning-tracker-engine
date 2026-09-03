"""Backend en memoria. La implementación de referencia de los ``Protocol``.

No persiste nada entre procesos: sirve para tests, para el bot de verificación
y como espejo contra el que se comprueba cualquier otro backend. Toda la lógica
de contrato (orden, corte, duplicados, aislamiento entre perfiles) vive en
:mod:`store._common` y se comparte con el backend JSON, de modo que ambos se
comportan exactamente igual.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from core.errors import UnknownObjectiveError, UnknownProfileError
from core.models import Attempt, Objective, Profile

from ._common import (
    filter_attempts,
    sort_attempts,
    validate_attempt,
    validate_objective,
    validate_profile,
)


class InMemoryAttemptStore:
    """``AttemptStore`` en memoria. Solo añade y lee (SPEC I1).

    Fíjese en lo que **no** hay: ningún ``update``, ``remove`` ni ``clear``.
    La ausencia es la garantía.
    """

    def __init__(self) -> None:
        # attempt_id -> (profile_id, attempt). Un solo índice global por id,
        # para que C9 (duplicado) se detecte entre perfiles.
        self._by_id: dict[str, tuple[str, Attempt]] = {}

    def append(self, profile_id: str, attempt: Attempt) -> Attempt:
        """Persiste un intento. Ver :meth:`core.storage.AttemptStore.append`."""
        validate_attempt(profile_id, attempt, self._by_id)
        self._by_id[attempt.attempt_id] = (profile_id, attempt)
        return attempt

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Intentos de un objetivo, ordenados por ``at`` y ``attempt_id``."""
        return sort_attempts(
            filter_attempts(self._by_id.values(), profile_id, objective_id, until)
        )

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Todos los intentos del perfil, ordenados, con corte opcional."""
        return sort_attempts(
            filter_attempts(self._by_id.values(), profile_id, None, until)
        )

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Número de intentos del perfil (o del objetivo, si se indica)."""
        return sum(
            1 for _ in filter_attempts(self._by_id.values(), profile_id, objective_id)
        )

    def exists(self, attempt_id: str) -> bool:
        """Si ya hay un intento con ese id, en cualquier perfil."""
        return attempt_id in self._by_id


class InMemoryProfileStore:
    """``ProfileStore`` en memoria."""

    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}

    def get_profile(self, profile_id: str) -> Profile:
        """Devuelve el perfil o lanza ``UnknownProfileError``."""
        try:
            return self._profiles[profile_id]
        except KeyError:
            raise UnknownProfileError(profile_id) from None

    def save_profile(self, profile: Profile) -> Profile:
        """Crea o reemplaza un perfil completo, objetivos incluidos."""
        validate_profile(profile)
        self._profiles[profile.profile_id] = profile
        return profile

    def list_profiles(self) -> list[Profile]:
        """Todos los perfiles, ordenados por ``profile_id``."""
        return [self._profiles[k] for k in sorted(self._profiles)]

    def get_objective(self, profile_id: str, objective_id: str) -> Objective:
        """Un objetivo del perfil. Falla ruidosamente si no existe (SPEC C8)."""
        profile = self.get_profile(profile_id)
        try:
            return profile.objectives[objective_id]
        except KeyError:
            raise UnknownObjectiveError(f"{profile_id}/{objective_id}") from None

    def list_objectives(self, profile_id: str) -> list[Objective]:
        """Objetivos del perfil, ordenados por ``objective_id``."""
        objectives = self.get_profile(profile_id).objectives
        return [objectives[k] for k in sorted(objectives)]

    def upsert_objectives(
        self, profile_id: str, objectives: Iterable[Objective]
    ) -> int:
        """Añade o reemplaza objetivos del perfil. Devuelve cuántos escribió.

        El perfil es inmutable (``frozen``), así que se reemplaza por una copia
        con el catálogo actualizado. Los intentos no se tocan: viven en otro
        store y su ciclo de vida es independiente.
        """
        profile = self.get_profile(profile_id)
        merged = dict(profile.objectives)
        written = 0
        for objective in objectives:
            validate_objective(objective)
            merged[objective.objective_id] = objective
            written += 1
        self._profiles[profile_id] = Profile(
            profile_id=profile.profile_id, name=profile.name, objectives=merged
        )
        return written
