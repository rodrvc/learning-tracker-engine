"""Tests of ``generate/`` against the ``QuestionGenerator`` contract.

Everything here runs against ``StubGenerator`` or a fake, injected client -
never the real Claude API. The ``anthropic`` package itself IS imported
(``generate/claude.py`` imports it at module level on purpose - see that
module's docstring), so CI installs the ``generate`` extra for this file.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from content.models import Material
from core.clock import FixedClock
from core.models import Objective
from generate import claude
from generate.claude import ClaudeGenerator
from generate.errors import GenerationError, MissingCredentialsError
from generate.stub import StubGenerator

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

MATERIAL = Material(
    material_id="mat-1",
    topic_id="ai-103",
    title="Storage accounts",
    source="notes.md",
    body=(
        "A storage account provides a unique namespace for your data.\n"
        "Blob storage is optimized for unstructured object data.\n"
        "Geo-redundant storage replicates data to a paired region.\n"
    ),
    created_at=T0,
)


class TestStubGenerator:
    """Shape and determinism of the generator the test suite runs against."""

    def test_proposes_a_new_objective_when_topic_has_none(self):
        result = StubGenerator().generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        assert len(result.objectives) == 1
        proposed = result.objectives[0]
        assert result.questions
        assert all(q.objective_id == proposed.objective_id for q in result.questions)

    def test_attaches_to_an_existing_objective_instead_of_duplicating(self):
        existing = Objective(objective_id="storage-basics", title="Storage basics")
        gen = StubGenerator()
        result = gen.generate(MATERIAL, existing_objectives=[existing], now=FixedClock(T0))
        assert result.objectives == ()
        assert all(q.objective_id == "storage-basics" for q in result.questions)

    def test_every_question_is_well_formed(self):
        result = StubGenerator().generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        for question in result.questions:
            assert question.material_id == MATERIAL.material_id
            assert question.topic_id == MATERIAL.topic_id
            assert len(question.options) >= 2
            assert question.correct_key in dict(question.options)
            assert question.created_at == T0

    def test_correct_answer_position_varies_across_questions(self):
        """Guards against the position bias the module docstring warns about:
        if the correct answer always sat at the first slot, an incurious
        quiz-taker would score full marks knowing nothing."""
        result = StubGenerator().generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        positions = {q.correct_key for q in result.questions}
        assert len(positions) > 1

    def test_deterministic_for_the_same_input(self):
        gen = StubGenerator()
        first = gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        second = gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        assert first == second

    def test_falls_back_when_material_has_no_usable_sentences(self):
        tiny = Material(
            material_id="mat-2",
            topic_id="ai-103",
            title="Empty",
            source="notes.md",
            body="ok",
            created_at=T0,
        )
        result = StubGenerator().generate(tiny, existing_objectives=[], now=FixedClock(T0))
        assert len(result.questions) == 1
        assert len(result.questions[0].options) >= 2


def _auth_error() -> anthropic.AuthenticationError:
    response = httpx2.Response(
        401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    return anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)


class _FakeMessages:
    def __init__(self, response: object = None, *, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises

    def parse(self, **kwargs: object) -> object:
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeClient:
    def __init__(self, response: object = None, *, raises: Exception | None = None) -> None:
        self.messages = _FakeMessages(response, raises=raises)


def _response(parsed_output: object, stop_reason: str = "end_turn", **extra: object) -> object:
    return SimpleNamespace(parsed_output=parsed_output, stop_reason=stop_reason, **extra)


def _question(**overrides: object) -> "claude._ProposedQuestion":
    fields = dict(
        objective_id="blob-basics",
        stem="What is blob storage optimized for?",
        options=[
            claude._ProposedOption(
                key="A", text="Unstructured object data", why_tempting="It is in fact correct."
            ),
            claude._ProposedOption(
                key="B", text="Relational tables", why_tempting="Storage accounts also offer tables."
            ),
            claude._ProposedOption(
                key="C", text="Block devices", why_tempting="Sounds like a storage primitive too."
            ),
            claude._ProposedOption(
                key="D", text="Message queues", why_tempting="Another Azure service, easily confused."
            ),
        ],
        correct_key="A",
        explanation="The material states blob storage is for unstructured object data.",
    )
    fields.update(overrides)
    return claude._ProposedQuestion(**fields)


def _parsed(
    objectives: list | None = None, questions: list | None = None
) -> "claude._GenerationSchema":
    return claude._GenerationSchema(
        objectives=(
            [claude._ProposedObjective(objective_id="blob-basics", title="Blob basics")]
            if objectives is None
            else objectives
        ),
        questions=[_question()] if questions is None else questions,
    )


class TestClaudeGenerator:
    """The conversion and failure-handling logic, via a fake client."""

    def test_converts_a_well_formed_response(self):
        gen = ClaudeGenerator(client=_FakeClient(_response(_parsed())))
        result = gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        assert len(result.objectives) == 1
        assert result.objectives[0].objective_id == "blob-basics"
        assert len(result.questions) == 1
        question = result.questions[0]
        assert question.correct_key in dict(question.options)
        assert question.material_id == MATERIAL.material_id
        assert question.created_at == T0

    def test_attaches_to_an_existing_objective_by_id(self):
        existing = Objective(objective_id="storage-basics", title="Storage basics")
        parsed = _parsed(objectives=[], questions=[_question(objective_id="storage-basics")])
        gen = ClaudeGenerator(client=_FakeClient(_response(parsed)))
        result = gen.generate(MATERIAL, existing_objectives=[existing], now=FixedClock(T0))
        assert result.objectives == ()
        assert result.questions[0].objective_id == "storage-basics"

    def test_shuffles_the_correct_answer_position(self):
        """Same fake response, different shuffle seeds: the position the
        model happened to answer in must not leak through unchanged."""
        positions = set()
        for seed in range(10):
            gen = ClaudeGenerator(
                client=_FakeClient(_response(_parsed())), random_source=random.Random(seed)
            )
            result = gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
            positions.add(result.questions[0].correct_key)
        assert len(positions) > 1

    @pytest.mark.parametrize(
        "questions",
        [
            # correct_key not among the options: unconstructable Question.
            [_question(correct_key="Z")],
            # objective_id neither existing nor among the proposed ones.
            [_question(objective_id="never-proposed-nor-existing")],
        ],
    )
    def test_malformed_response_raises_instead_of_persisting_rubbish(self, questions):
        gen = ClaudeGenerator(client=_FakeClient(_response(_parsed(questions=questions))))
        with pytest.raises(GenerationError):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_refusal_is_reported_as_a_refusal_not_a_malformed_response(self):
        response = _response(
            None, stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")
        )
        gen = ClaudeGenerator(client=_FakeClient(response))
        with pytest.raises(GenerationError, match="refus"):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_missing_parsed_output_without_refusal_raises(self):
        """``parsed_output`` is ``Optional`` and can be ``None`` on a
        response that carries no parsed text block (e.g. all thinking),
        distinct from a refusal."""
        response = _response(None, stop_reason="max_tokens")
        gen = ClaudeGenerator(client=_FakeClient(response))
        with pytest.raises(GenerationError, match="max_tokens"):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_authentication_error_is_reported_as_missing_credentials(self):
        gen = ClaudeGenerator(client=_FakeClient(raises=_auth_error()))
        with pytest.raises(MissingCredentialsError):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
