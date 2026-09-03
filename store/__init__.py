"""Implementaciones concretas de persistencia y del reloj real.

Está separado de ``core/`` a propósito: aquí vive todo lo que toca el mundo
exterior (disco, reloj de sistema), de modo que la garantía I2 —``core/`` no
consulta el reloj— sea verificable con un grep sobre ``core/`` sin falsos
positivos.

Implementaciones concretas, contra los ``Protocol`` de :mod:`core.storage`:

* :class:`InMemoryAttemptStore` / :class:`InMemoryProfileStore` (memoria).
* :class:`JsonAttemptStore` / :class:`JsonProfileStore` (archivo JSON).

Ambos backends comparten las reglas de contrato en :mod:`store._common`, así
que se comportan igual: la suite de tests corre contra los dos.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo

from .json_store import JsonAttemptStore, JsonProfileStore
from .memory import InMemoryAttemptStore, InMemoryProfileStore


class SystemClock:
    """El reloj real. La **única** puerta al tiempo del sistema.

    Vive aquí y no en ``core/`` para que sea imposible usarlo por accidente
    desde el motor. En producción se inyecta esta clase; en tests, un
    :class:`~core.clock.FixedClock`.

    Args:
        tz: zona horaria de los instantes devueltos. UTC por defecto.
    """

    def __init__(self, tz: tzinfo = timezone.utc) -> None:
        if tz is None:
            raise ValueError("SystemClock exige una zona horaria: un reloj naive está prohibido")
        self._tz = tz

    @property
    def tz(self) -> tzinfo:
        return self._tz

    def now(self) -> datetime:
        """El instante actual, aware, en la zona configurada."""
        return datetime.now(self._tz)

    def __repr__(self) -> str:
        return f"SystemClock(tz={self._tz!r})"


__all__ = [
    "SystemClock",
    "InMemoryAttemptStore",
    "InMemoryProfileStore",
    "JsonAttemptStore",
    "JsonProfileStore",
]
