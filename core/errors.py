"""Excepciones del motor.

Todas heredan de :class:`TrackerError`, de modo que quien integra puede capturar
una sola clase. Existen para que los fallos sean **ruidosos**: el contrato
prohíbe devolver ``None`` o un valor neutro ante una operación que no se pudo
completar (SPEC §6, I8).
"""

from __future__ import annotations


class TrackerError(Exception):
    """Raíz de todos los errores del motor."""


class UnknownProfileError(TrackerError):
    """El ``profile_id`` no existe en el store."""


class UnknownObjectiveError(TrackerError):
    """El ``objective_id`` no existe en el perfil.

    Se lanza tanto al registrar un intento como al consultar estado. El motor
    **no** autocrea objetivos: un id mal escrito debe fallar, no fabricar un
    objetivo fantasma (SPEC §7, C8).
    """


class DuplicateAttemptError(TrackerError):
    """Ya existe un intento con ese ``attempt_id`` (SPEC §7, C9)."""


class StorageError(TrackerError):
    """La persistencia no pudo completar la operación.

    Nunca se traga: si el intento no quedó escrito, esto se propaga (SPEC I8).
    """


class InvalidAttemptError(TrackerError):
    """El intento está mal formado.

    Por ejemplo: ``at`` sin zona horaria, ``confidence`` fuera de [0, 1] o
    ``objective_id`` vacío.
    """


class InvalidRangeError(TrackerError):
    """Un rango temporal es incoherente, p. ej. ``start > end`` o ``step <= 0``."""
