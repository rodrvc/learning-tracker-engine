"""The real ``QuestionGenerator``, backed by the Claude API.

Uses the official ``anthropic`` SDK (the ``generate`` extra in
``pyproject.toml``) - no raw HTTP, no OpenAI-compatible shim. ``core/``
keeps zero runtime dependencies; this package is where the network-facing
seam lives, in the same spirit as ``store/postgres.py``: a thin adapter
behind a ``Protocol``, constructed with an injectable client so it can be
tested without ever reaching the network (see ``tests/test_generate.py``).

The actual point of this module: a question whose wrong options are
obviously wrong measures nothing, because the engine (SPEC section 2) will
faithfully record a meaningless correct answer as evidence of mastery.
``_SYSTEM_PROMPT`` below asks for distractors that are plausible confusions
drawn from the material's own content, and for an explanation of why each
wrong option is tempting, not merely that it is wrong.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Sequence

from pydantic import BaseModel, Field

from content.errors import InvalidQuestionError
from content.models import Material, Question
from core.clock import Clock
from core.models import Objective

from .errors import GenerationError, MissingCredentialsError
from .generator import GenerationResult

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

_SYSTEM_PROMPT = """\
You turn a page of study notes into multiple-choice practice questions that \
actually measure understanding.

You will be given the material's text and the list of learning objectives \
the topic already has. Prefer attaching new questions to an existing \
objective over inventing a near-duplicate of one; propose a new objective \
only for material that no existing objective covers.

For every question, produce 4 options. Exactly one is correct, drawn from \
the material. The other three must be plausible distractors: real \
confusions someone could have from THIS material - a similar term, a \
swapped number or condition, a step performed in the wrong order, a \
concept from elsewhere in the material misapplied here. Never write a \
distractor that is obviously wrong, off-topic, or absurd; a question whose \
wrong answers are transparently wrong tests nothing.

The explanation must justify the correct answer AND say, for each wrong \
option, why it is tempting - what in the material someone would have to \
misread or half-remember to pick it - not merely that it is wrong.

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


class _ProposedQuestion(BaseModel):
    objective_id: str
    stem: str
    options: list[_ProposedOption] = Field(min_length=2)
    correct_key: str
    explanation: str


class _GenerationSchema(BaseModel):
    objectives: list[_ProposedObjective]
    questions: list[_ProposedQuestion]


def _has_credentials() -> bool:
    """An explicit key or token is set. Only gates the clear error message
    below - it never blocks a client that would in fact authenticate
    through some other means (e.g. an ``ant auth`` profile)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _existing_objectives_digest(objectives: Sequence[Objective]) -> str:
    if not objectives:
        return "(none yet - this is the first material for this topic)"
    return "\n".join(f"- {obj.objective_id}: {obj.title}" for obj in objectives)


class ClaudeGenerator:
    """``QuestionGenerator`` backed by the Claude API.

    Args:
        client: an ``anthropic.Anthropic``-shaped object. Built lazily with
            no arguments (it resolves the key from the environment itself)
            when not supplied - never in ``__init__``, so constructing a
            ``ClaudeGenerator`` never fails for lack of a credential; only
            calling :meth:`generate` does. Tests inject a fake here so no
            network call is ever made.
    """

    def __init__(self, client: object | None = None) -> None:
        self._client = client

    def generate(
        self,
        material: Material,
        existing_objectives: Sequence[Objective],
        *,
        now: Clock,
    ) -> GenerationResult:
        """See ``generate.generator.QuestionGenerator.generate``."""
        client = self._client
        if client is None:
            if not _has_credentials():
                raise MissingCredentialsError(
                    "ANTHROPIC_API_KEY is not set; question generation is unavailable "
                    "until it is configured. Everything else keeps working."
                )
            # Imported here, not at module level: ``anthropic`` is an
            # optional extra, and tests inject a fake client so they never
            # reach this line - the suite does not need the extra installed.
            import anthropic

            client = anthropic.Anthropic()

        try:
            response = client.messages.parse(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Existing objectives for this topic:\n"
                            f"{_existing_objectives_digest(existing_objectives)}\n\n"
                            f"Material title: {material.title}\n"
                            f"Material:\n{material.body}"
                        ),
                    }
                ],
                output_format=_GenerationSchema,
            )
            parsed = response.parsed_output
        except GenerationError:
            raise
        except Exception as exc:  # SDK errors, network errors, schema mismatches
            raise GenerationError(f"could not generate questions: {exc}") from exc

        return self._to_result(material, existing_objectives, parsed, now.now())

    @staticmethod
    def _to_result(
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
                questions.append(
                    Question(
                        question_id=f"q-{uuid.uuid4().hex}",
                        topic_id=material.topic_id,
                        objective_id=proposed.objective_id,
                        stem=proposed.stem,
                        options=tuple((o.key, o.text) for o in proposed.options),
                        correct_key=proposed.correct_key,
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
