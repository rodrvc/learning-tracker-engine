"""Turns uploaded study material into proposed objectives and questions.

See ``generator.py`` for the ``QuestionGenerator`` contract, ``stub.py`` for
the deterministic implementation the test suite runs against,
``openai_backend.py`` for the OpenAI API backed one, and ``targeting.py`` for
the pure "does this page say anything about that objective?" test a run aimed
at the objectives without questions needs before any model is called.
"""

from __future__ import annotations

from .errors import GenerationError, MissingCredentialsError
from .generator import (
    GenerationResult,
    QuestionGenerator,
    UncoveredObjective,
    domains_of,
)

__all__ = [
    "GenerationError",
    "MissingCredentialsError",
    "GenerationResult",
    "QuestionGenerator",
    "UncoveredObjective",
    "domains_of",
]
