"""The real ``QuestionGenerator``, backed by the Claude API.

Uses the official ``anthropic`` SDK (the ``generate`` extra in
``pyproject.toml``, installed in CI so this module's one untested branch -
building a real client - still gets a static check) - no raw HTTP, no
OpenAI-compatible shim. ``core/`` keeps zero runtime dependencies; this
package is where the network-facing seam lives, in the same spirit as
``store/postgres.py``: a thin adapter behind a ``Protocol``, constructed
with an injectable client so it can be tested without ever reaching the
network (see ``tests/test_generate.py``).

The actual point of this module: a question whose wrong options are
obviously wrong measures nothing, because the engine (SPEC section 2) will
faithfully record a meaningless correct answer as evidence of mastery.
``_SYSTEM_PROMPT`` asks for distractors that are plausible confusions drawn
from the material's own content, requires a schema-level justification for
every wrong option (so a missing one is a validation error, not a quality
regression nobody notices), and every proposed question has its correct
option placed at a randomized position rather than trusting the model not
to default to "the first one" (SPEC-style: don't rely on discipline where a
structural guarantee is available).
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Sequence

import anthropic
from pydantic import BaseModel, Field, model_validator

from content.errors import InvalidQuestionError
from content.models import Material, Question
from core.clock import Clock
from core.models import Objective

from .errors import GenerationError, MissingCredentialsError
from .generator import GenerationResult

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000
_OPTIONS_PER_QUESTION = 4
_MAX_QUESTIONS_PER_MATERIAL = 8
_OPTION_KEYS = tuple("ABCDEFGH")

_SYSTEM_PROMPT = """\
You turn a page of study notes into multiple-choice practice questions that \
actually measure understanding.

You will be given the material's text and the list of learning objectives \
the topic already has. Prefer attaching new questions to an existing \
objective over inventing a near-duplicate of one; propose a new objective \
only for material that no existing objective covers.

For every question, produce exactly 4 options. Exactly one is correct, \
drawn from the material. The other three must be plausible distractors: \
real confusions someone could have from THIS material - a similar term, a \
swapped number or condition, a step performed in the wrong order, a \
concept from elsewhere in the material misapplied here. Never write a \
distractor that is obviously wrong, off-topic, or absurd; a question whose \
wrong answers are transparently wrong tests nothing. For every option \
other than the correct one, fill in why it is tempting: what in the \
material someone would have to misread or half-remember to pick it.

The explanation field justifies the correct answer.

Write the stem, options and explanations in the same language as the \
material - do not translate it.

Ground every stem, option and explanation in the material's own content. \
Do not invent facts the material does not contain.\
"""


class _ProposedObjective(BaseModel):
    objective_id: str
    title: str
    domain: str | None = None


class _ProposedOption(BaseModel):
    key: str
    text: str
    #: Why this option is tempting though wrong. Required for every option
    #: except the correct one - enforced below, not merely requested, so a
    #: model that skips it fails the schema instead of shipping a silent
    #: quality regression.
    why_tempting: str | None = None


class _ProposedQuestion(BaseModel):
    objective_id: str
    stem: str
    options: list[_ProposedOption] = Field(
        min_length=_OPTIONS_PER_QUESTION, max_length=_OPTIONS_PER_QUESTION
    )
    correct_key: str
    explanation: str

    @model_validator(mode="after")
    def _wrong_options_explain_themselves(self) -> "_ProposedQuestion":
        for option in self.options:
            if option.key != self.correct_key and not (option.why_tempting or "").strip():
                raise ValueError(
                    f"option {option.key!r} is a wrong answer with no why_tempting"
                )
        return self


class _GenerationSchema(BaseModel):
    objectives: list[_ProposedObjective]
    questions: list[_ProposedQuestion] = Field(
        min_length=1, max_length=_MAX_QUESTIONS_PER_MATERIAL
    )


def _target_question_count(material: Material) -> int:
    """A concrete number to ask for, derived from the material's length.

    An open-ended "as many as you see fit" invites a long page to keep
    generating until it truncates mid-JSON, which then surfaces as an
    opaque parse error instead of the truncation it actually was.
    """
    words = len(material.body.split())
    return max(3, min(_MAX_QUESTIONS_PER_MATERIAL, words // 120 + 2))


def _existing_objectives_digest(objectives: Sequence[Objective]) -> str:
    if not objectives:
        return "(none yet - this is the first material for this topic)"
    return "\n".join(f"- {obj.objective_id}: {obj.title}" for obj in objectives)


def _shuffle_options(
    rng: random.Random, options: list[_ProposedOption], correct_key: str
) -> tuple[tuple[tuple[str, str], ...], str]:
    """Re-keys ``options`` in a random order.

    The model is asked to place the correct answer wherever it naturally
    falls, but nothing stops it from defaulting to "the first option" every
    time - the exact position bias this package exists to avoid handing
    an incurious quiz-taker (see the module docstring). Re-keying here is a
    structural guarantee, not an instruction the model could ignore.
    """
    order = list(range(len(options)))
    rng.shuffle(order)
    keys = _OPTION_KEYS[: len(options)]
    shuffled = tuple((keys[position], options[i].text) for position, i in enumerate(order))
    new_correct_key = next(
        keys[position] for position, i in enumerate(order) if options[i].key == correct_key
    )
    return shuffled, new_correct_key


class ClaudeGenerator:
    """``QuestionGenerator`` backed by the Claude API.

    Args:
        client: an ``anthropic.Anthropic``-shaped object. Built with no
            arguments (it resolves the key from the environment itself)
            when not supplied. Tests inject a fake here so no network call
            is ever made.
        model: overridable so a caller isn't stuck patching a module
            constant to test or tune it.
        max_tokens: same reasoning as ``model``.
        random_source: source of the option-shuffle randomness. Injectable
            for determinism in tests, exactly like ``now: Clock`` above.
    """

    def __init__(
        self,
        client: object | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        random_source: random.Random | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._random = random_source or random.Random()

    def generate(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        *,
        now: Clock,
    ) -> GenerationResult:
        """See ``generate.generator.QuestionGenerator.generate``."""
        client = self._client or anthropic.Anthropic()

        try:
            response = client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                thinking={"type": "adaptive"},
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Existing objectives for this topic:\n"
                            f"{_existing_objectives_digest(existing_objectives)}\n\n"
                            f"Produce {_target_question_count(material)} questions.\n\n"
                            f"Material title: {material.title}\n"
                            f"Material:\n{material.body}"
                        ),
                    }
                ],
                output_format=_GenerationSchema,
            )

            # A refusal is HTTP 200 with stop_reason "refusal" (this model
            # runs safety classifiers) - it is a distinct event, not a
            # malformed response, and reporting it as the latter sends
            # whoever debugs it looking for a schema bug that isn't there.
            if response.stop_reason == "refusal":
                category = getattr(response.stop_details, "category", None)
                raise GenerationError(
                    f"the model refused to generate questions for this material "
                    f"(category={category!r})"
                )

            # ``parsed_output`` is Optional: it is None on a refusal (caught
            # above) and on any other response with no parsed text block
            # (e.g. one that is all thinking). Guard it explicitly instead
            # of letting a bare AttributeError stand in for "malformed".
            parsed = response.parsed_output
            if parsed is None:
                raise GenerationError(
                    "the model produced no structured output "
                    f"(stop_reason={response.stop_reason!r})"
                )

            return self._to_result(material, existing_objectives, parsed, now.now())
        except anthropic.AuthenticationError as exc:
            raise MissingCredentialsError(
                "Anthropic rejected the configured credential (or none is "
                "configured); question generation is unavailable until a valid "
                "one is set up. Everything else keeps working."
            ) from exc
        except GenerationError:
            raise
        except Exception as exc:  # SDK errors, network errors, schema mismatches
            raise GenerationError(f"could not generate questions: {exc}") from exc

    def _to_result(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        parsed: _GenerationSchema,
        created_at: datetime,
    ) -> GenerationResult:
        known_ids = {obj.objective_id for obj in existing_objectives}
        try:
            objectives = tuple(
                Objective(objective_id=obj.objective_id, title=obj.title, domain=obj.domain)
                for obj in parsed.objectives
            )
            known_ids |= {obj.objective_id for obj in objectives}

            questions = []
            for proposed in parsed.questions:
                if proposed.objective_id not in known_ids:
                    raise InvalidQuestionError(
                        f"objective_id {proposed.objective_id!r} is neither an existing "
                        "objective nor one of the objectives just proposed"
                    )
                options, correct_key = _shuffle_options(
                    self._random, proposed.options, proposed.correct_key
                )
                questions.append(
                    Question(
                        question_id=f"q-{uuid.uuid4().hex}",
                        topic_id=material.topic_id,
                        objective_id=proposed.objective_id,
                        stem=proposed.stem,
                        options=options,
                        correct_key=correct_key,
                        explanation=proposed.explanation,
                        material_id=material.material_id,
                        created_at=created_at,
                    )
                )
        except InvalidQuestionError as exc:
            # The model layer already makes an inconsistent question
            # unconstructable (e.g. correct_key not among options) - fail
            # loudly instead of repairing or dropping it silently.
            raise GenerationError(f"model produced an invalid question: {exc}") from exc

        return GenerationResult(objectives=objectives, questions=tuple(questions))
