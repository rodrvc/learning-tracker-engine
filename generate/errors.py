"""Exceptions of the ``generate`` package.

Mirrors ``content/errors.py``: one root so an integrator can catch a single
class, and failures are loud rather than silently repaired.
"""

from __future__ import annotations


class GenerationError(Exception):
    """Root of every ``generate``-package error.

    Raised whenever a generator cannot turn a ``Material`` into valid
    ``Objective``/``Question`` proposals - a malformed model response, an
    unparsable schema, or a domain-model rejection (e.g. ``correct_key`` not
    among ``options``) - so the caller never receives a half-built result.
    """


class MissingCredentialsError(GenerationError):
    """``ANTHROPIC_API_KEY`` (or another supported credential) is not set.

    Raised only when generation is actually attempted, never at
    construction time: the rest of the application must keep serving
    material and questions that already exist even when no key is
    configured (SPEC-style graceful degradation, not a hard startup
    dependency).
    """
