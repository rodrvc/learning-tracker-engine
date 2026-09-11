"""Tests of ``generate/`` against the ``QuestionGenerator`` contract.

Everything here runs against ``StubGenerator`` or a fake, injected client -
never the real OpenAI API. The ``openai`` package itself IS imported
(``generate/openai_backend.py`` imports it at module level on purpose - see
that module's docstring), so CI installs the ``generate`` extra for this file.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import ValidationError

from content.models import Material
from core.clock import FixedClock
from core.models import Objective
from generate import prompting
from generate.openai_backend import OpenAIGenerator
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


def _auth_error() -> openai.AuthenticationError:
    response = httpx.Response(
        401, request=httpx.Request("POST", "https://api.openai.com/v1/responses")
    )
    return openai.AuthenticationError("invalid api key", response=response, body=None)


class _FakeResponses:
    def __init__(self, response: object = None, *, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises

    def parse(self, **kwargs: object) -> object:
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeClient:
    def __init__(self, response: object = None, *, raises: Exception | None = None) -> None:
        self.responses = _FakeResponses(response, raises=raises)


def _response(output_parsed: object, status: str = "completed", refusal: str | None = None):
    """A response shaped like the SDK's.

    A refusal arrives on an output content item rather than at the top level,
    so the fake nests it the same way: a test that asserted on a flat field
    would pass while the real shape went unhandled.
    """
    content = [SimpleNamespace(refusal=refusal)] if refusal else []
    return SimpleNamespace(
        output_parsed=output_parsed,
        status=status,
        output=[SimpleNamespace(content=content)],
    )


def _question(**overrides: object) -> "prompting._ProposedQuestion":
    fields = dict(
        objective_id="blob-basics",
        stem="What is blob storage optimized for?",
        options=[
            prompting._ProposedOption(
                key="A", text="Unstructured object data", why_tempting="It is in fact correct."
            ),
            prompting._ProposedOption(
                key="B", text="Relational tables", why_tempting="Storage accounts also offer tables."
            ),
            prompting._ProposedOption(
                key="C", text="Block devices", why_tempting="Sounds like a storage primitive too."
            ),
            prompting._ProposedOption(
                key="D", text="Message queues", why_tempting="Another Azure service, easily confused."
            ),
        ],
        correct_key="A",
        explanation="The material states blob storage is for unstructured object data.",
    )
    fields.update(overrides)
    return prompting._ProposedQuestion(**fields)


def _parsed(
    objectives: list | None = None, questions: list | None = None
) -> "prompting._GenerationSchema":
    return prompting._GenerationSchema(
        objectives=(
            [prompting._ProposedObjective(objective_id="blob-basics", title="Blob basics")]
            if objectives is None
            else objectives
        ),
        questions=[_question()] if questions is None else questions,
    )


class TestOpenAIGenerator:
    """The conversion and failure-handling logic, via a fake client."""

    def test_converts_a_well_formed_response(self):
        gen = OpenAIGenerator(client=_FakeClient(_response(_parsed())))
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
        gen = OpenAIGenerator(client=_FakeClient(_response(parsed)))
        result = gen.generate(MATERIAL, existing_objectives=[existing], now=FixedClock(T0))
        assert result.objectives == ()
        assert result.questions[0].objective_id == "storage-basics"

    def test_shuffles_the_correct_answer_position(self):
        """Same fake response, different shuffle seeds: the position the
        model happened to answer in must not leak through unchanged."""
        positions = set()
        for seed in range(10):
            gen = OpenAIGenerator(
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
        gen = OpenAIGenerator(client=_FakeClient(_response(_parsed(questions=questions))))
        with pytest.raises(GenerationError):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_refusal_is_reported_as_a_refusal_not_a_malformed_response(self):
        response = _response(None, refusal="I can't help with that.")
        gen = OpenAIGenerator(client=_FakeClient(response))
        with pytest.raises(GenerationError, match="refus"):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_missing_output_parsed_without_refusal_raises(self):
        """``output_parsed`` is ``Optional`` and can be ``None`` on a
        response that carries no parsed text block (e.g. all thinking),
        distinct from a refusal."""
        response = _response(None, status="incomplete")
        gen = OpenAIGenerator(client=_FakeClient(response))
        with pytest.raises(GenerationError, match="incomplete"):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_authentication_error_is_reported_as_missing_credentials(self):
        gen = OpenAIGenerator(client=_FakeClient(raises=_auth_error()))
        with pytest.raises(MissingCredentialsError):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))


@pytest.mark.spec
def test_no_credential_configured_raises_missing_credentials_not_a_crash(monkeypatch):
    """The unconfigured case, reached for real rather than hand-raised.

    The suite's other credential test injects a fake that raises the exception
    it then asserts on, which proves the router's handler works and nothing
    about whether that exception is ever reachable. It is not, unless the
    client is built inside the guard: with no key resolvable the SDK raises
    from its own constructor, and building it outside let that escape as an
    unhandled error and surface as a 500 (ACU-249 review).
    """
    for var in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(MissingCredentialsError):
        OpenAIGenerator().generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))


class TestResponseSchemaEnforcement:
    """The schema's own guarantees, asserted rather than assumed.

    ``prompting`` exists to enforce what the prompt asks for, so a model that
    ignores an instruction fails loudly instead of shipping a silent quality
    regression. Every constraint below was reachable only through a correct
    model response until these tests existed: the validator and the two
    cardinality bounds could each be deleted with the whole suite still green
    (ACU-249 review). The counts are written as literals on purpose - derived
    from the module's constants they would assert the comparison and never the
    value.
    """

    @pytest.mark.parametrize("missing", ["", "   ", None])
    def test_a_wrong_option_without_why_tempting_is_rejected(self, missing):
        options = [
            prompting._ProposedOption(key="A", text="Correct", why_tempting=None),
            prompting._ProposedOption(key="B", text="Wrong", why_tempting=missing),
            prompting._ProposedOption(key="C", text="Wrong", why_tempting="Plausible."),
            prompting._ProposedOption(key="D", text="Wrong", why_tempting="Plausible."),
        ]
        with pytest.raises(ValidationError, match="why_tempting"):
            _question(options=options, correct_key="A")

    def test_the_correct_option_needs_no_why_tempting(self):
        """Only the distractors owe an explanation; the right answer does not."""
        options = [
            prompting._ProposedOption(key="A", text="Correct", why_tempting=None),
            prompting._ProposedOption(key="B", text="Wrong", why_tempting="Plausible."),
            prompting._ProposedOption(key="C", text="Wrong", why_tempting="Plausible."),
            prompting._ProposedOption(key="D", text="Wrong", why_tempting="Plausible."),
        ]
        assert _question(options=options, correct_key="A").correct_key == "A"

    @pytest.mark.parametrize("count", [2, 3, 5])
    def test_a_question_takes_exactly_four_options(self, count):
        options = [
            prompting._ProposedOption(
                key=key, text=f"Option {key}", why_tempting="Plausible."
            )
            for key in "ABCDE"[:count]
        ]
        with pytest.raises(ValidationError):
            _question(options=options, correct_key="A")

    def test_a_response_with_no_questions_is_rejected(self):
        """An empty run is a failure to report, not a result to store."""
        with pytest.raises(ValidationError):
            _parsed(questions=[])

    def test_a_response_of_more_than_eight_questions_is_rejected(self):
        with pytest.raises(ValidationError):
            _parsed(questions=[_question() for _ in range(9)])
