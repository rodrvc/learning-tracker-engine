"""A deterministic ``QuestionGenerator`` that needs no network and no key -
what the test suite runs against. Produces real, constructible ``Question``
values from the material's own sentences, matching ``ClaudeGenerator``'s
shape, but makes no claim to the distractor quality that is the actual
point of this package - that is ``ClaudeGenerator``'s prompt to deliver.
"""

from __future__ import annotations

import re
from typing import Sequence

from content.models import Material, Question
from core.clock import Clock
from core.models import Objective

from .generator import GenerationResult

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
        *,
        now: Clock,
    ) -> GenerationResult:
        """Builds up to :data:`_MAX_QUESTIONS` questions from ``material``.

        Attaches every question to ``existing_objectives[0]`` when there is
        one - never a near-duplicate objective for a topic that already has
        one; otherwise proposes exactly one new objective from the title.
        """
        created_at = now.now()
        sentences = _sentences(material.body)

        if existing_objectives:
            objective_id = existing_objectives[0].objective_id
            proposed_objectives: tuple[Objective, ...] = ()
        else:
            objective_id = f"{_slug(material.title)}-obj"
            proposed_objectives = (
                Objective(objective_id=objective_id, title=material.title),
            )

        questions = []
        for index in range(min(_MAX_QUESTIONS, max(len(sentences), 1))):
            correct = sentences[index] if index < len(sentences) else (
                f"{material.title}: no distinguishing statement was extracted."
            )
            others = [s for s in sentences if s != correct]
            distractors = (others + list(_FALLBACK_DISTRACTORS))[:3]
            texts = [correct] + distractors
            options = tuple(zip(_OPTION_KEYS[: len(texts)], texts))
            questions.append(
                Question(
                    question_id=f"{material.material_id}-q{index + 1}",
                    topic_id=material.topic_id,
                    objective_id=objective_id,
                    stem=f'According to "{material.title}", which statement is accurate?',
                    options=options,
                    correct_key=_OPTION_KEYS[0],
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
