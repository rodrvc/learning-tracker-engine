"""Concrete persistence implementations and the real clock.

It is kept apart from ``core/`` on purpose: everything that touches the outside
world (disk, system clock) lives here, so that guarantee I2 — ``core/`` does not
read the clock — is verifiable with a grep over ``core/`` and no false
positives.

Concrete implementations, against the ``Protocol`` types of
:mod:`core.storage`:

* :class:`InMemoryAttemptStore` / :class:`InMemoryProfileStore` (memory).
* :class:`JsonAttemptStore` / :class:`JsonProfileStore` (JSON file).

Both backends share the contract rules in :mod:`store._common`, so they behave
the same: the test suite runs against both.

A third backend, :class:`~store.postgres.PostgresAttemptStore` /
:class:`~store.postgres.PostgresProfileStore`, lives in :mod:`store.postgres`.
It requires the ``psycopg`` driver (the ``postgres`` extra in
``pyproject.toml``), so importing it is best-effort here: environments that
did not install that extra can still use the memory and JSON backends.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo

from .json_store import JsonAttemptStore, JsonProfileStore
from .memory import InMemoryAttemptStore, InMemoryProfileStore

_POSTGRES_NAMES = ("PostgresAttemptStore", "PostgresProfileStore")


def __getattr__(name: str):
    """Imports the Postgres backend on demand, and says so when it cannot.

    Binding these names to ``None`` when the driver is missing would hand back
    a ``None`` that fails much later as ``'NoneType' object is not callable``,
    far from the cause. That is the silent half-success this codebase exists to
    avoid (SPEC I8), so the failure is raised here, naming the fix.
    """
    if name in _POSTGRES_NAMES:
        try:
            from . import postgres
        except ImportError as exc:  # pragma: no cover - needs psycopg absent
            raise ImportError(
                f"{name} necesita el driver psycopg: instala el extra "
                "'postgres' (pip install -e '.[postgres]')"
            ) from exc
        return getattr(postgres, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class SystemClock:
    """The real clock. The **only** door to system time.

    It lives here and not in ``core/`` so that using it from the engine by
    accident is impossible. In production this class is injected; in tests, a
    :class:`~core.clock.FixedClock`.

    Args:
        tz: timezone of the instants returned. UTC by default.
    """

    def __init__(self, tz: tzinfo = timezone.utc) -> None:
        if tz is None:
            raise ValueError("SystemClock exige una zona horaria: un reloj naive está prohibido")
        self._tz = tz

    @property
    def tz(self) -> tzinfo:
        return self._tz

    def now(self) -> datetime:
        """The current instant, aware, in the configured timezone."""
        return datetime.now(self._tz)

    def __repr__(self) -> str:
        return f"SystemClock(tz={self._tz!r})"


__all__ = [
    "SystemClock",
    "InMemoryAttemptStore",
    "InMemoryProfileStore",
    "JsonAttemptStore",
    "JsonProfileStore",
    "PostgresAttemptStore",
    "PostgresProfileStore",
]
