"""Tests of ``generate/`` against the ``QuestionGenerator`` contract.

Everything here runs against ``StubGenerator`` or a fake, injected client -
never the real Claude API and never the ``anthropic`` package itself, so
the suite needs neither a credential nor the ``generate`` extra installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

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


class _FakeMessages:
    def __init__(self, parsed_output: object) -> None:
        self._parsed_output = parsed_output

    def parse(self, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(parsed_output=self._parsed_output)


class _FakeClient:
    def __init__(self, parsed_output: object) -> None:
        self.messages = _FakeMessages(parsed_output)


def _question(**overrides: object) -> "claude._ProposedQuestion":
    fields = dict(
        objective_id="blob-basics",
        stem="What is blob storage optimized for?",
        options=[
            claude._ProposedOption(key="A", text="Unstructured object data"),
            claude._ProposedOption(key="B", text="Relational tables"),
        ],
        correct_key="A",
        explanation=(
            "The material states blob storage is for unstructured object data. "
            "'Relational tables' is tempting because storage accounts also offer a "
            "table service, easily confused with blob storage."
        ),
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
        gen = ClaudeGenerator(client=_FakeClient(_parsed()))
        result = gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        assert len(result.objectives) == 1
        assert result.objectives[0].objective_id == "blob-basics"
        assert len(result.questions) == 1
        question = result.questions[0]
        assert question.correct_key == "A"
        assert question.material_id == MATERIAL.material_id
        assert question.created_at == T0

    def test_attaches_to_an_existing_objective_by_id(self):
        existing = Objective(objective_id="storage-basics", title="Storage basics")
        parsed = _parsed(objectives=[], questions=[_question(objective_id="storage-basics")])
        gen = ClaudeGenerator(client=_FakeClient(parsed))
        result = gen.generate(MATERIAL, existing_objectives=[existing], now=FixedClock(T0))
        assert result.objectives == ()
        assert result.questions[0].objective_id == "storage-basics"

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
        gen = ClaudeGenerator(client=_FakeClient(_parsed(questions=questions)))
        with pytest.raises(GenerationError):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_missing_credentials_raises_a_clear_error_without_touching_the_network(
        self, monkeypatch
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        gen = ClaudeGenerator()  # no injected client: would build a real one
        with pytest.raises(MissingCredentialsError):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
