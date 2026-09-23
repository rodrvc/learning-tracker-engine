"""A deterministic ``QuestionGenerator`` that needs no network and no key -
what the test suite runs against. Produces real, constructible ``Question``
values from the material's own sentences, matching ``OpenAIGenerator``'s
shape, but makes no claim to the distractor quality that is the actual
point of this package - that is ``OpenAIGenerator``'s prompt to deliver.
"""

from __future__ import annotations

import re
from typing import Sequence

from content.models import Material, Question
from core.clock import Clock
from core.models import Objective

from .generator import GenerationResult, UncoveredObjective
from .targeting import terms

_MAX_QUESTIONS = 3
_OPTION_KEYS = ("A", "B", "C", "D")
_FALLBACK_DISTRACTORS = (
    "This is not stated anywhere in the material.",
    "This contradicts what the material says.",
    "This confuses the topic with an unrelated one.",
)


def _sentences(body: str) -> list[str]:
    """Splits ``body`` into non-trivial sentences, in order, deduplicated."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n+", body):
        sentence = raw.strip()
        if len(sentence) < 15 or sentence in seen:
            continue
        seen.add(sentence)
        result.append(sentence)
    return result


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "objective"


class StubGenerator:
    """Deterministic ``QuestionGenerator``. See the module docstring."""

    def generate(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        existing_domains: Sequence[str] = (),
        *,
        uncovered_objectives: Sequence[Objective] = (),
        now: Clock,
    ) -> GenerationResult:
        """Builds up to :data:`_MAX_QUESTIONS` questions from ``material``.

        Given ``uncovered_objectives`` the run is aimed instead, and handled by
        :meth:`_aimed`, which is where the rule that matters lives: an
        objective this page says nothing about comes back reported, never
        answered.

        Attaches every question to ``existing_objectives[0]`` when there is
        one - never a near-duplicate objective for a topic that already has
        one; otherwise proposes exactly one new objective from the title.

        An objective it does propose goes into ``existing_domains[0]`` when
        the goal has units, and carries no unit when it has none. A real
        backend chooses which of the units the material belongs to; the
        choosing is what a stub cannot do. What it can do, and what the
        suite is here to hold it to, is the part that actually went wrong
        in the field: a proposed objective must land in a unit the goal
        already has rather than found one of its own.
        """
        if uncovered_objectives:
            return self._aimed(material, uncovered_objectives, now)

        created_at = now.now()
        sentences = _sentences(material.body)

        if existing_objectives:
            objective_id = existing_objectives[0].objective_id
            proposed_objectives: tuple[Objective, ...] = ()
        else:
            objective_id = f"{_slug(material.title)}-obj"
            proposed_objectives = (
                Objective(
                    objective_id=objective_id,
                    title=material.title,
                    domain=existing_domains[0] if existing_domains else None,
                ),
            )

        questions = []
        for index in range(min(_MAX_QUESTIONS, max(len(sentences), 1))):
            correct = sentences[index] if index < len(sentences) else (
                f"{material.title}: no distinguishing statement was extracted."
            )
            others = [s for s in sentences if s != correct]
            distractors = (others + list(_FALLBACK_DISTRACTORS))[:3]
            texts = [correct] + distractors
            # Rotate so the correct answer's position varies deterministically
            # by question index, rather than always sitting at the first slot
            # - the exact position bias this package exists to avoid handing
            # an incurious quiz-taker (see the module docstring).
            pos = index % len(texts)
            texts = texts[-pos:] + texts[:-pos] if pos else texts
            options = tuple(zip(_OPTION_KEYS[: len(texts)], texts))
            questions.append(
                Question(
                    question_id=f"{material.material_id}-q{index + 1}",
                    topic_id=material.topic_id,
                    objective_id=objective_id,
                    stem=f'According to "{material.title}", which statement is accurate?',
                    options=options,
                    correct_key=_OPTION_KEYS[pos],
                    explanation=(
                        f'"{correct}" is drawn directly from the material. The other '
                        "options are plausible only if the material is misread or "
                        "confused with an unrelated statement."
                    ),
                    material_id=material.material_id,
                    created_at=created_at,
                )
            )

        return GenerationResult(objectives=proposed_objectives, questions=tuple(questions))

    def _aimed(
        self, material: Material, targets: Sequence[Objective], now: Clock
    ) -> GenerationResult:
        """One question per target the material supports, a report for the rest.

        "Supports" is the crudest test that can still be called grounded: the
        page must contain a sentence sharing a meaningful word with the
        objective's title (``targeting.terms``, the notion the planner used to
        pick this page). A real backend reads the page and judges, and judging is
        what a stub cannot do; what it can do, and what the suite holds every
        generator to, is refuse to answer for a target the page says nothing
        about and give a reason instead. A stub that quietly invented a question
        per target would let the suite certify the very behaviour this feature
        exists to prevent.
        """
        created_at = now.now()
        sentences = _sentences(material.body)
        questions: list[Question] = []
        uncovered: list[UncoveredObjective] = []

        for target in targets:
            wanted = terms(f"{target.title} {target.domain or ''}")
            grounding = next((s for s in sentences if wanted & terms(s)), None)
            if grounding is None:
                uncovered.append(
                    UncoveredObjective(
                        objective_id=target.objective_id,
                        reason=f'"{material.title}" says nothing about {target.title!r}',
                    )
                )
                continue
            others = [s for s in sentences if s != grounding]
            texts = [grounding] + (others + list(_FALLBACK_DISTRACTORS))[:3]
            # Rotated so the correct answer does not always sit first, for the
            # same reason the per-page path above rotates.
            pos = len(questions) % len(texts)
            texts = texts[-pos:] + texts[:-pos] if pos else texts
            questions.append(
                Question(
                    # The id carries the objective: an aimed run adds questions
                    # rather than replacing the page's set, so a later run for a
                    # different gap on the same page must not collide with this.
                    question_id=f"{material.material_id}-{_slug(target.objective_id)}-q1",
                    topic_id=material.topic_id,
                    objective_id=target.objective_id,
                    stem=f'According to "{material.title}", which statement is accurate?',
                    options=tuple(zip(_OPTION_KEYS[: len(texts)], texts)),
                    correct_key=_OPTION_KEYS[pos],
                    explanation=(
                        f'"{grounding}" is drawn directly from the material, which is '
                        f"what makes it usable for {target.title!r}."
                    ),
                    material_id=material.material_id,
                    created_at=created_at,
                )
            )

        return GenerationResult(
            objectives=(), questions=tuple(questions), uncovered=tuple(uncovered)
        )
