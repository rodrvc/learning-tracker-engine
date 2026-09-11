"""Turns uploaded study material into proposed objectives and questions.

See ``generator.py`` for the ``QuestionGenerator`` contract, ``stub.py`` for
the deterministic implementation the test suite runs against, and
``claude.py`` for the Claude API backed one.
"""

from __future__ import annotations

from .errors import GenerationError, MissingCredentialsError
from .generator import GenerationResult, QuestionGenerator

__all__ = [
    "GenerationError",
    "MissingCredentialsError",
    "GenerationResult",
    "QuestionGenerator",
]
