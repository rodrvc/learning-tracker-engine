"""Exceptions of the content package.

Mirrors ``core/errors.py``: every exception inherits from a single root so an
integrator can catch one class, and failures are loud rather than silent.
"""

from __future__ import annotations

class ContentError(Exception):
    """Root of every content-package error."""

class UnknownMaterialError(ContentError):
    """The ``material_id`` does not exist in the store."""

class UnknownQuestionError(ContentError):
    """The ``question_id`` does not exist in the store."""

class DuplicateMaterialError(ContentError):
    """A material with that ``material_id`` already exists."""

class DuplicateQuestionError(ContentError):
    """A question with that ``question_id`` already exists."""

class InvalidMaterialError(ContentError):
    """The material is malformed."""

class InvalidQuestionError(ContentError):
    """The question is malformed, e.g. ``correct_key`` is not one of ``options``."""

class StorageError(ContentError):
    """Persistence could not complete the operation. Never swallowed."""
