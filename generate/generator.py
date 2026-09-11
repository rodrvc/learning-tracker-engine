"""The generation interface. See SPEC.md section 1.2 for what an
``Objective`` is and section 2 for what the engine does with the attempts
the questions produced here go on to generate.

Same spirit as ``content/storage.py``: a single ``Protocol`` is the only
thing a caller needs to know. ``generate.stub.StubGenerator`` is the
reference implementation the test suite runs against (deterministic, no
network, no credential); ``generate.claude.ClaudeGenerator`` is the real
one.

**A generator persists nothing.** It returns proposed ``Objective`` and
``Question`` values; the caller decides what to store, and through what
``content.storage`` / ``core.storage`` backend. That boundary is what lets
this package be tested without a database and without a network call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from content.models import Material, Question
from core.clock import Clock
from core.models import Objective


@dataclass(frozen=True)
class GenerationResult:
    """What a generator proposes from one ``Material``.

    ``objectives`` are newly proposed objectives to create alongside the
    questions that reference them; empty when every question attaches to an
    objective the topic already has. Each question's ``objective_id`` is
    either one of ``existing_objectives`` passed in, or one of these
    ``objectives`` - never a dangling reference.
    """

    objectives: tuple[Objective, ...]
    questions: tuple[Question, ...]


@runtime_checkable
class QuestionGenerator(Protocol):
    """Turns a ``Material`` into proposed objectives and questions.

    Implementations must not invent near-duplicates of an objective the
    topic already has - that is why ``existing_objectives`` is an input,
    not something the generator discovers on its own.
    """

    def generate(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        *,
        now: Clock,
    ) -> GenerationResult:
        """Proposes objectives and questions for ``material``.

        ``now`` is the source of ``created_at`` for anything proposed -
        never read from the system clock directly (SPEC I2's discipline).

        Raises ``generate.errors.GenerationError`` when the response cannot
        be turned into valid objectives/questions, or (``ClaudeGenerator``
        only) when no credential is configured.
        """
        ...
