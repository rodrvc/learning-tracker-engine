"""The generation interface. See SPEC.md section 1.2 for what an
``Objective`` is and section 2 for what the engine does with the attempts
the questions produced here go on to generate.

Same spirit as ``content/storage.py``: a single ``Protocol`` is the only
thing a caller needs to know. ``generate.stub.StubGenerator`` is the
reference implementation the test suite runs against (deterministic, no
network, no credential); ``generate.openai_backend.OpenAIGenerator`` is
the real one.

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
class UncoveredObjective:
    """An objective the run was aimed at and could not ground a question for.

    For an aimed run this is the more important half of the result: an objective
    whose material says nothing about it must come back named, with the reason,
    rather than answered with an invented question. A coverage number that went
    up because a gap was filled with fiction is worse than the gap, which at
    least is visible.
    """

    objective_id: str
    reason: str


@dataclass(frozen=True)
class GenerationResult:
    """What a generator proposes from one ``Material``.

    ``objectives`` are newly proposed objectives to create alongside the
    questions that reference them; empty when every question attaches to an
    objective the topic already has. Each question's ``objective_id`` is
    either one of ``existing_objectives`` passed in, or one of these
    ``objectives`` - never a dangling reference.

    ``uncovered`` is filled only by an aimed run (one given
    ``uncovered_objectives`` below) and holds every target this material could
    not support. Empty by default, so an ordinary per-page run says nothing
    about coverage rather than claiming everything is uncovered.
    """

    objectives: tuple[Objective, ...]
    questions: tuple[Question, ...]
    uncovered: tuple[UncoveredObjective, ...] = ()


def domains_of(objectives: Sequence[Objective]) -> tuple[str, ...]:
    """The units a goal already has, in first-seen order, deduplicated.

    How a caller builds the ``existing_domains`` argument below. It lives
    here, beside the contract, rather than in the caller, because every
    caller would otherwise write the same scrape - and one of them would
    write it differently (sorted, or keeping the ``None``s) and hand a
    generator a unit list that disagrees with the next caller's.
    """
    seen: dict[str, None] = {}
    for objective in objectives:
        domain = (objective.domain or "").strip()
        if domain:
            seen.setdefault(domain, None)
    return tuple(seen)


@runtime_checkable
class QuestionGenerator(Protocol):
    """Turns a ``Material`` into proposed objectives and questions.

    Implementations must not invent near-duplicates of an objective the
    topic already has - that is why ``existing_objectives`` is an input,
    not something the generator discovers on its own. ``existing_domains``
    is the same argument one level up: the units (``Objective.domain``,
    SPEC section 1.2) the goal is already divided into, so that a new
    objective lands in one of them instead of founding a unit of its own.
    ``uncovered_objectives`` is the same kind of argument once more, pointed
    the other way: not what must not be duplicated, but what is missing and
    worth aiming at.
    """

    def generate(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        existing_domains: Sequence[str] = (),
        *,
        uncovered_objectives: Sequence[Objective] = (),
        now: Clock,
    ) -> GenerationResult:
        """Proposes objectives and questions for ``material``.

        ``uncovered_objectives`` are objectives of this topic that no stored
        question assesses yet. Given them, the run is **aimed**: it produces
        questions only for those objectives, proposes no new ones, and reports in
        ``GenerationResult.uncovered`` every target this material does not
        actually support. Passing them turns "make questions from this page" into
        "close these gaps if this page can". A separate keyword argument because
        being uncovered is not a property of the material: it is what the caller
        found in storage a moment ago, and the same page yields a different aimed
        run tomorrow with nothing about the page having changed.

        An aimed run may legitimately return no questions at all. A page that
        supports none of its targets must say so; being asked for a question is
        never a reason to invent one, and that is the rule this argument exists
        to make enforceable rather than hoped for.

        ``existing_domains`` are the goal's units, typically
        ``domains_of(existing_objectives)``. Every proposed objective must
        take one of them; a new unit is for material no existing unit
        covers. An empty ``existing_domains`` - a goal not divided into
        units yet - leaves the generator free to propose them.

        It is a separate argument rather than something each implementation
        reads back off ``existing_objectives`` because it is a separate
        decision: the objectives are what must not be duplicated, the units
        are the shape the goal is kept in. A caller that knows a unit the
        objectives have not reached yet can name it here.

        ``now`` is the source of ``created_at`` for anything proposed -
        never read from the system clock directly (SPEC I2's discipline).

        Raises ``generate.errors.GenerationError`` when the response cannot
        be turned into valid objectives/questions, or (``OpenAIGenerator``
        only) when no credential is configured.
        """
        ...
