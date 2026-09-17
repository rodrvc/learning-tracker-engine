"""JSON backend on disk. Same interface and same rules as the in-memory one.

One file per store. Every operation reads the whole file and, when it writes,
replaces it atomically (temporary file in the same directory + ``os.replace``):
either the attempt ends up written and readable, or
:class:`~core.errors.StorageError` is raised and the previous file is left
intact (SPEC I8). There is no in-memory cache: the file **is** the state, which
makes the rebuild argument trivial (SPEC I6).

Attempts are stored as a flat list in arrival order; the canonical order is
imposed on read (SPEC C4), never on write.

Concurrency between processes
-----------------------------

Every write is a read-modify-rewrite sequence over the whole file. Without
exclusion, two processes writing at the same time (two CLIs, a bot and a CLI)
can read the same state and the second ``os.replace`` overwrites the first: an
attempt is lost with no exception, a silent violation of I8. That is why every
write takes an **exclusive** ``fcntl.flock`` over an empty sidecar file
``<name>.lock`` next to the JSON, for the whole sequence.

* Guarantee: a single writer at a time per file, within the same host. The
  second writer **waits** (it does not fail) until the first one releases the
  lock. If the lock cannot be acquired (permissions, closed descriptor...)
  :class:`~core.errors.StorageError` is raised, never silence.
* Pure reads do not take the lock: ``os.replace`` is atomic, so a reader sees
  either the previous file or the new one, never a mixture.
* Limitation: ``flock`` is not reliable on network file systems (NFS, SMB) nor
  across different hosts. There is no exclusion guarantee there.
* The ``.lock`` is an extra, empty file; the JSON format does not change and
  deleting it is harmless (it is recreated on the next write).

Exception message texts stay in Spanish: they can reach the user through the
CLI.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from core.errors import (
    StorageError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.models import Attempt, AttemptKind, Objective, Profile

from ._common import (
    filter_attempts,
    merge_objectives,
    sort_attempts,
    validate_attempt,
    validate_profile,
)

_FORMAT_VERSION = 1


# --------------------------------------------------------------- (de)serialization


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
        "archived": profile.archived,
    }


def _profile_from_json(data: dict[str, Any]) -> Profile:
    objectives = [_objective_from_json(o) for o in data.get("objectives", [])]
    return Profile(
        profile_id=data["profile_id"],
        name=data["name"],
        objectives={o.objective_id: o for o in objectives},
        # ``.get`` and not ``[...]``: a file written before this field existed
        # is a valid file, and every profile in it was being studied. Reading
        # it must not fail, and the absence of the key means exactly "not
        # archived", the same default the model states.
        archived=data.get("archived", False),
    )


# ------------------------------------------------------------------------- file


def lock_path_for(path: Path) -> Path:
    """Path of the lock sidecar: ``<name>.lock`` next to the JSON."""
    return path.with_name(path.name + ".lock")


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Exclusive lock between processes to write ``path``.

    It wraps the complete read-modify-rewrite sequence. It blocks (waits) when
    another process already holds it. Any failure opening the sidecar or taking
    the lock is turned into :class:`StorageError` (SPEC I8).
    """
    lock_path = lock_path_for(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        raise StorageError(f"no se pudo abrir el lock {lock_path}: {exc}") from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            raise StorageError(
                f"no se pudo obtener el lock {lock_path}: {exc}"
            ) from exc
        yield
    finally:
        # Closing the descriptor releases the flock even if LOCK_UN failed.
        os.close(fd)


def _read_document(path: Path, root_key: str) -> list[dict[str, Any]]:
    """Reads the file. If it does not exist, the store is empty (not an error)."""
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
    """Atomic write: a temporary in the same directory plus ``os.replace``."""
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


# ----------------------------------------------------------------------- stores


class JsonAttemptStore:
    """``AttemptStore`` over a JSON file. It only appends and reads (SPEC I1).

    Args:
        path: file the attempts live in. It is created on the first ``append``.
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
        """Persists an attempt. See :meth:`core.storage.AttemptStore.append`."""
        with _exclusive_lock(self._path):
            raw_rows = _read_document(self._path, self.ROOT_KEY)
            existing = {d["attempt_id"] for d in raw_rows}
            validate_attempt(profile_id, attempt, existing)
            raw_rows.append(_attempt_to_json(profile_id, attempt))
            _write_document(self._path, self.ROOT_KEY, raw_rows)
        return attempt

    def list_for_objective(
        self, profile_id: str, objective_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Attempts of an objective, sorted by ``at`` and ``attempt_id``."""
        return sort_attempts(
            filter_attempts(self._rows(), profile_id, objective_id, until)
        )

    def list_all(
        self, profile_id: str, until: datetime | None = None
    ) -> list[Attempt]:
        """Every attempt of the profile, sorted, with an optional cut."""
        return sort_attempts(filter_attempts(self._rows(), profile_id, None, until))

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        """Number of attempts of the profile (or of the objective, when given)."""
        return len(filter_attempts(self._rows(), profile_id, objective_id))

    def exists(self, attempt_id: str) -> bool:
        """Whether an attempt with that id already exists, in any profile."""
        return any(
            d["attempt_id"] == attempt_id
            for d in _read_document(self._path, self.ROOT_KEY)
        )


class JsonProfileStore:
    """``ProfileStore`` over a JSON file.

    Args:
        path: file the profiles and their objectives live in.
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
        """Returns the profile or raises ``UnknownProfileError``."""
        try:
            return self._load()[profile_id]
        except KeyError:
            raise UnknownProfileError(profile_id) from None

    def save_profile(self, profile: Profile) -> Profile:
        """Creates or replaces a whole profile, objectives included."""
        validate_profile(profile)
        with _exclusive_lock(self._path):
            profiles = self._load()
            profiles[profile.profile_id] = profile
            self._save(profiles)
        return profile

    def list_profiles(self) -> list[Profile]:
        """Every profile, archived ones included, sorted by ``profile_id``."""
        profiles = self._load()
        return [profiles[k] for k in sorted(profiles)]

    def set_archived(self, profile_id: str, archived: bool) -> Profile:
        """Flips the archived flag and nothing else.

        Under the same exclusive lock every other write takes: the flag lives
        in the same file as the catalog, so a read-modify-rewrite of it can
        lose a concurrent objective upload exactly as any other write can.
        """
        with _exclusive_lock(self._path):
            profiles = self._load()
            try:
                profile = profiles[profile_id]
            except KeyError:
                raise UnknownProfileError(profile_id) from None
            updated = replace(profile, archived=archived)
            profiles[profile_id] = updated
            self._save(profiles)
        return updated

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
        the in-memory backend.
        """
        with _exclusive_lock(self._path):
            profiles = self._load()
            try:
                profile = profiles[profile_id]
            except KeyError:
                raise UnknownProfileError(profile_id) from None
            profiles[profile_id], written = merge_objectives(profile, objectives)
            self._save(profiles)
        return written


__all__ = ["JsonAttemptStore", "JsonProfileStore", "lock_path_for"]
