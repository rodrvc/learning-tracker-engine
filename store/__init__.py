"""Implementaciones concretas de persistencia y del reloj real.

Está separado de ``core/`` a propósito: aquí vive todo lo que toca el mundo
exterior (disco, reloj de sistema), de modo que la garantía I2 —``core/`` no
consulta el reloj— sea verificable con un grep sobre ``core/`` sin falsos
positivos.

Las implementaciones concretas (``InMemoryAttemptStore``, ``JsonAttemptStore``,
etc.) las escribirá quien implemente, contra los ``Protocol`` de
:mod:`core.storage`.
"""

from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    """El reloj real. La **única** puerta al tiempo del sistema.

    Vive aquí y no en ``core/`` para que sea imposible usarlo por accidente
    desde el motor. En producción se inyecta esta clase; en tests, un
    :class:`~core.clock.FixedClock`.

    Args:
        tz: zona horaria de los instantes devueltos. UTC por defecto.
    """

    def __init__(self, tz: timezone = timezone.utc) -> None:
        raise NotImplementedError

    def now(self) -> datetime:
        """El instante actual, aware."""
        raise NotImplementedError


__all__ = ["SystemClock"]
