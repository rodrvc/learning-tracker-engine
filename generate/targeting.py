"""Which objectives still have no question, and which page to aim at them.

Two questions a run aimed at the uncovered objectives answers before any model
is called. Both are pure functions of what is already stored, so both live here
rather than in the router: the router is where they are used, not where they can
be tested.

The page is chosen by plain lexical overlap, not by a model, and the modesty of
that tool is the point: it never decides that a question exists, only which page
is worth reading first. A bad guess costs a page read for nothing, or an
objective reported as uncovered that a cleverer search would have matched - a
visible gap, which is what this feature exists to produce, and never an invented
question, which is what it must not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from content.models import Material, Question
from core.models import Objective

#: Words too common to be evidence that a page is about an objective. Short and
#: bilingual on purpose: the material is Spanish, a certification syllabus often
#: is not, and a stopword list long enough to be interesting is one that starts
#: throwing away real terms.
_STOPWORDS = frozenset(
    "about and for from into that the their them then there these this using "
    "with when which como cuando para por que sobre una uno los las del desde "
    "entre esta este esto".split()
)

#: Shortest word taken as a term. Below this almost everything is an article or
#: a bare number, and a match on one of those is evidence of nothing.
_MIN_TERM_LENGTH = 4

#: Most objectives aimed at a single page. One word of overlap is enough to make
#: a page a candidate, so a broad page of notes matches dozens of objectives at
#: once - and asking one call to cover dozens gets most of them reported
#: uncovered by a page that was never really about them, with no second page
#: ever tried. Aiming the best-matching handful instead leaves the rest to the
#: page that matches them better. Eight is what a single call can answer for
#: (``prompting._MAX_QUESTIONS_PER_MATERIAL``).
MAX_TARGETS_PER_PAGE = 8


def terms(text: str) -> frozenset[str]:
    """The meaningful words of ``text``, lowercased and stripped of plurals.

    Stripping plurals is the one piece of morphology worth having: without it
    "Search skillsets" shares nothing with a page writing "a skillset enriches
    documents", and the gap is reported as "no material covers this" while the
    notes sit right there. Shared with ``StubGenerator``'s notion of "this page
    supports that objective", so the generator the suite runs against and the
    planner that picked the page agree on what a match is.
    """
    words = re.findall(r"[^\W_]+", text.lower())
    return frozenset(
        word[:-1] if len(word) > _MIN_TERM_LENGTH and word.endswith("s") else word
        for word in words
        if len(word) >= _MIN_TERM_LENGTH and word not in _STOPWORDS
    )


def objectives_without_questions(
    objectives: Sequence[Objective], questions: Iterable[Question]
) -> tuple[Objective, ...]:
    """The objectives of a topic that no stored question assesses.

    Counted from the questions themselves, not from a per-objective counter, for
    the reason SPEC's decision 1 gives about the attempt history: a counter can
    disagree with the facts. Keeps the order of ``objectives`` (sorted by
    ``objective_id``), so a run's report reads in syllabus order.
    """
    assessed = {question.objective_id for question in questions}
    return tuple(obj for obj in objectives if obj.objective_id not in assessed)


def overlap(material: Material, objective: Objective) -> int:
    """How many meaningful words the objective shares with the page."""
    page = terms(f"{material.title} {material.body}")
    return len(terms(f"{objective.title} {objective.domain or ''}") & page)


@dataclass(frozen=True)
class CoverageStep:
    """One page to generate from, and the objectives to aim at it."""

    material: Material
    targets: tuple[Objective, ...]


def plan_coverage_run(
    materials: Sequence[Material],
    targets: Sequence[Objective],
    *,
    max_pages: int,
) -> tuple[CoverageStep, ...]:
    """Which pages to read, in which order, and what to aim at each.

    Greedy set cover: the page plausibly supporting the most still-unassigned
    targets goes first, its targets are struck off, the rest are ranked again.
    Greedy rather than exhaustive because each page costs one model call, so the
    ordering only has to be good enough to spend the ``max_pages`` budget on the
    pages that can pay it back. Ties break on total overlap and then on
    ``material_id``, so two runs over the same data plan alike.

    A page sharing no meaningful word with any remaining target is never
    scheduled: nothing there could ground a question, so the call would spend
    money to be told what the ranking knows. An objective no page matches is
    never assigned at all, and the caller reports it as uncovered - the honest
    answer for a unit whose notes were never uploaded.
    """
    remaining = list(targets)
    plan: list[CoverageStep] = []

    while remaining and len(plan) < max_pages:
        read = {step.material.material_id for step in plan}
        ranked = []
        for material in (m for m in materials if m.material_id not in read):
            scored = sorted(
                ((overlap(material, obj), obj) for obj in remaining),
                key=lambda pair: (-pair[0], pair[1].objective_id),
            )[:MAX_TARGETS_PER_PAGE]
            matched = tuple(obj for score, obj in scored if score > 0)
            if matched:
                total = sum(score for score, obj in scored if score > 0)
                ranked.append((-len(matched), -total, material.material_id, matched, material))
        if not ranked:
            break
        *_, matched, material = min(ranked)
        plan.append(CoverageStep(material=material, targets=matched))
        assigned = {obj.objective_id for obj in matched}
        remaining = [obj for obj in remaining if obj.objective_id not in assigned]

    return tuple(plan)


__all__ = [
    "CoverageStep",
    "objectives_without_questions",
    "overlap",
    "plan_coverage_run",
    "terms",
]
