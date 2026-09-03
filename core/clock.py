"""La abstracción del tiempo.

Regla dura del contrato (SPEC §6, I2): **ningún módulo de ``core/`` llama a
``datetime.now()``**. El tiempo entra por parámetro (``as_of``) o por un
:class:`Clock` inyectado. Es verificable desde fuera con un grep sobre ``core/``.

El reloj real (``SystemClock``) vive deliberadamente en ``store/``, fuera de
``core/``, para que ese grep no tenga falsos positivos y para que sea imposible
usar el reloj de sistema por accidente desde el motor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Fuente de "ahora".

    Única puerta al tiempo real en todo el sistema. Las implementaciones deben
    devolver un ``datetime`` **con zona horaria** (aware); un datetime naive
    hace incomparables los intentos y está prohibido por el contrato.
    """

    def now(self) -> datetime:
        """El instante actual, aware (con ``tzinfo``)."""
        ...


@dataclass(frozen=True)
class FixedClock:
    """Reloj que siempre devuelve el mismo instante.

    La herramienta de los tests: fija la fecha y el resultado del motor deja de
    depender de cuándo se ejecute la suite.

    Args:
        moment: instante aware que devolverá ``now()``.
    """

    moment: datetime

    def now(self) -> datetime:
        """Devuelve :attr:`moment`, siempre el mismo."""
        return self.moment


@dataclass(frozen=True)
class OffsetClock:
    """Un reloj base desplazado por una cantidad fija de tiempo.

    Permite simular el avance del calendario sin esperar: envolver un
    :class:`FixedClock` con ``offset=timedelta(days=30)`` responde la pregunta
    "¿cómo estará esto dentro de un mes?".

    Args:
        base: reloj sobre el que se aplica el desplazamiento.
        offset: cuánto se adelanta (positivo) o atrasa (negativo).
    """

    base: Clock
    offset: timedelta

    def now(self) -> datetime:
        """``base.now() + offset``."""
        return self.base.now() + self.offset

    def advanced(self, delta: timedelta) -> "OffsetClock":
        """Un nuevo reloj con ``delta`` adicional de desplazamiento.

        Inmutable: no modifica este reloj, devuelve otro.
        """
        return OffsetClock(base=self.base, offset=self.offset + delta)
