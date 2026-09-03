"""Backend JSON en disco. Misma interfaz y mismas reglas que el de memoria.

Un archivo por store. Cada operación lee el archivo entero y, si escribe, lo
reemplaza de forma atómica (archivo temporal en el mismo directorio +
``os.replace``): o el intento queda escrito y legible, o se lanza
:class:`~core.errors.StorageError` y el archivo anterior queda intacto
(SPEC I8). No hay caché en memoria: el archivo **es** el estado, lo que hace
trivial el argumento de reconstrucción (SPEC I6).

Los intentos se guardan como una lista plana en orden de llegada; el orden
canónico se impone al leer (SPEC C4), nunca al escribir.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.errors import (
    StorageError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.models import Attempt, AttemptKind, Objective, Profile

from ._common import (
    filter_attempts,
    sort_attempts,
    validate_attempt,
    validate_objective,
    validate_profile,
)

_FORMAT_VERSION = 1


# ------------------------------------------------------------------ (de)serialización


def _dt_to_json(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _dt_from_json(raw: str | None) -> datetime | None:
    return None if raw is None else datetime.fromisoformat(raw)


def _attempt_to_json(profile_id: str, attempt: Attempt) -> dict[str, Any]:
    data = asdict(attempt)
    data["at"] = _dt_to_json(attempt.at)
    data["recorded_at"] = _dt_to_json(attempt.recorded_at)
    data["kind"] = attempt.kind.value
    data["profile_id"] = profile_id
    return data


def _attempt_from_json(data: dict[str, Any]) -> tuple[str, Attempt]:
    data = dict(data)
    profile_id = data.pop("profile_id")
    data["at"] = _dt_from_json(data["at"])
    data["recorded_at"] = _dt_from_json(data.get("recorded_at"))
    data["kind"] = AttemptKind(data.get("kind", AttemptKind.QUIZ.value))
    return profile_id, Attempt(**data)


def _objective_to_json(objective: Objective) -> dict[str, Any]:
    data = asdict(objective)
    data["tags"] = list(objective.tags)
    return data


def _objective_from_json(data: dict[str, Any]) -> Objective:
    data = dict(data)
    data["tags"] = tuple(data.get("tags", ()))
    return Objective(**data)


def _profile_to_json(profile: Profile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "name": profile.name,
        "objectives": [
            _objective_to_json(o) for _, o in sorted(profile.objectives.items())
        ],
    }


def _profile_from_json(data: dict[str, Any]) -> Profile:
    objectives = [_objective_from_json(o) for o in data.get("objectives", [])]
    return Profile(
        profile_id=data["profile_id"],
        name=data["name"],
        objectives={o.objective_id: o for o in objectives},
    )


# ------------------------------------------------------------------ archivo


def _read_document(path: Path, root_key: str) -> list[dict[str, Any]]:
    """Lee el archivo. Si no existe, el store está vacío (no es un error)."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, ValueError) as exc:
        raise StorageError(f"no se pudo leer {path}: {exc}") from exc
    if not isinstance(document, dict) or root_key not in document:
        raise StorageError(f"{path} no tiene la estructura esperada ({root_key!r})")
    return list(document[root_key])


def _write_document(path: Path, root_key: str, rows: list[dict[str, Any]]) -> None:
    """Escritura atómica: temporal en el mismo directorio y ``os.replace``."""
    document = {"version": _FORMAT_VERSION, root_key: rows}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(document, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise StorageError(f"no se pudo escribir {path}: {exc}") from exc


# ------------------------------------------------------------------ stores


class JsonAttemptStore:
    """``AttemptStore`` sobre un archivo JSON. Solo añade y lee (SPEC I1).

    Args:
        path: archivo donde viven los intentos. Se crea al primer ``append``.
    """

    ROOT_KEY = "attempts"

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _rows(self) -> list[tuple[str, Attempt]]:
        return [_attempt_from_json(d) for d in _read_document(self._path, self.ROOT_KEY)]

    def append(self, profile_id: str, attempt: Attempt) -> Attempt:
        """Persiste un intento. Ver :meth:`core.storage.AttemptStore.append`."""
        raw_rows = _read_document(self._path, self.ROOT_KEY)
        existing = {d["attempt_id"] for d in raw_rows}
        validate_attempt(profile_id, attempt, existing)
        raw_rows.append(_attempt_to_json(profile_id, attempt))
        _write_document(self._path, self.ROOT_KEY, raw_rows)
        return attempt

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Intentos de un objetivo, ordenados por ``at`` y ``attempt_id``."""
        return sort_attempts(
            filter_attempts(self._rows(), profile_id, objective_id, until)
        )

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Todos los intentos del perfil, ordenados, con corte opcional."""
        return sort_attempts(filter_attempts(self._rows(), profile_id, None, until))

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Número de intentos del perfil (o del objetivo, si se indica)."""
        return len(filter_attempts(self._rows(), profile_id, objective_id))

    def exists(self, attempt_id: str) -> bool:
        """Si ya hay un intento con ese id, en cualquier perfil."""
        return any(
            d["attempt_id"] == attempt_id
            for d in _read_document(self._path, self.ROOT_KEY)
        )


class JsonProfileStore:
    """``ProfileStore`` sobre un archivo JSON.

    Args:
        path: archivo donde viven los perfiles y sus objetivos.
    """

    ROOT_KEY = "profiles"

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Profile]:
        profiles = [
            _profile_from_json(d) for d in _read_document(self._path, self.ROOT_KEY)
        ]
        return {p.profile_id: p for p in profiles}

    def _save(self, profiles: dict[str, Profile]) -> None:
        _write_document(
            self._path,
            self.ROOT_KEY,
            [_profile_to_json(profiles[k]) for k in sorted(profiles)],
        )

    def get_profile(self, profile_id: str) -> Profile:
        """Devuelve el perfil o lanza ``UnknownProfileError``."""
        try:
            return self._load()[profile_id]
        except KeyError:
            raise UnknownProfileError(profile_id) from None

    def save_profile(self, profile: Profile) -> Profile:
        """Crea o reemplaza un perfil completo, objetivos incluidos."""
        validate_profile(profile)
        profiles = self._load()
        profiles[profile.profile_id] = profile
        self._save(profiles)
        return profile

    def list_profiles(self) -> list[Profile]:
        """Todos los perfiles, ordenados por ``profile_id``."""
        profiles = self._load()
        return [profiles[k] for k in sorted(profiles)]

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
        """Añade o reemplaza objetivos del perfil. Devuelve cuántos escribió."""
        profiles = self._load()
        try:
            profile = profiles[profile_id]
        except KeyError:
            raise UnknownProfileError(profile_id) from None
        merged = dict(profile.objectives)
        written = 0
        for objective in objectives:
            validate_objective(objective)
            merged[objective.objective_id] = objective
            written += 1
        profiles[profile_id] = Profile(
            profile_id=profile.profile_id, name=profile.name, objectives=merged
        )
        self._save(profiles)
        return written


__all__ = ["JsonAttemptStore", "JsonProfileStore"]
