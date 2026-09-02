"""Las interfaces de persistencia.

``core/`` no sabe si detrás hay un JSON, SQLite o memoria. Solo conoce estos
dos ``Protocol``. Las implementaciones concretas viven en ``store/``.

El detalle importante del contrato: :class:`AttemptStore` **no tiene métodos de
modificación ni de borrado**. No es una omisión, es la garantía I1 (historial
append-only) hecha estructura: no se puede corromper un intento con una API que
no ofrece manera de tocarlo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

from .models import Attempt, Objective, Profile


@runtime_checkable
class AttemptStore(Protocol):
    """Persistencia de intentos. Solo añade y lee.

    Toda implementación debe garantizar:

    * ``append`` es atómico: o el intento queda escrito y legible, o se lanza
      :class:`~core.errors.StorageError`. Nunca un éxito silencioso a medias
      (SPEC I8).
    * ``append`` rechaza un ``attempt_id`` ya existente con
      :class:`~core.errors.DuplicateAttemptError` (SPEC C9).
    * Los métodos de lectura devuelven los intentos **ordenados por ``at``
      ascendente, desempatando por ``attempt_id``**, de modo que el orden de
      escritura sea irrelevante (SPEC C4).
    """

    def append(self, attempt: Attempt) -> Attempt:
        """Persiste un intento y lo devuelve tal como quedó guardado.

        Raises:
            DuplicateAttemptError: si el ``attempt_id`` ya existe.
            StorageError: si la escritura no pudo completarse.
        """
        ...

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Intentos de un objetivo, ordenados, con ``at <= until`` si se indica.

        ``until`` es el corte temporal que hace posible la consulta histórica
        (SPEC §5.1). ``None`` significa "todos".
        """
        ...

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Todos los intentos del perfil, ordenados, con corte opcional."""
        ...

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Número de intentos.

        Existe como método propio para que el chequeo de consistencia pueda
        comparar **conteos** del store contra conteos recalculados, sin
        materializar listas ni comparar conjuntos (SPEC I9).
        """
        ...

    def exists(self, attempt_id: str) -> bool:
        """Si ya hay un intento con ese id."""
        ...


@runtime_checkable
class ProfileStore(Protocol):
    """Persistencia de perfiles y sus objetivos.

    Separado de :class:`AttemptStore` porque tienen ciclos de vida distintos:
    el catálogo de objetivos se edita, el historial de intentos jamás.
    """

    def get_profile(self, profile_id: str) -> Profile:
        """Devuelve el perfil.

        Raises:
            UnknownProfileError: si no existe.
        """
        ...

    def save_profile(self, profile: Profile) -> Profile:
        """Crea o reemplaza un perfil y devuelve el resultado persistido."""
        ...

    def list_profiles(self) -> list[Profile]:
        """Todos los perfiles conocidos."""
        ...

    def get_objective(self, profile_id: str, objective_id: str) -> Objective:
        """Devuelve un objetivo del perfil.

        Raises:
            UnknownProfileError: si el perfil no existe.
            UnknownObjectiveError: si el objetivo no existe en él.
        """
        ...

    def list_objectives(self, profile_id: str) -> list[Objective]:
        """Objetivos del perfil, ordenados por ``objective_id``."""
        ...

    def upsert_objectives(
        self, profile_id: str, objectives: Iterable[Objective]
    ) -> int:
        """Añade o actualiza objetivos. Devuelve cuántos se escribieron."""
        ...
