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
from generate import prompting, targeting
from generate.openai_backend import OpenAIGenerator
from generate.errors import GenerationError, MissingCredentialsError
from generate.generator import UncoveredObjective, domains_of
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

        #: Every call's keyword arguments, so a test can assert on what was
        #: actually sent to the model rather than on the helper that builds
        #: it - a prompt rule nothing forwards is a rule that does nothing.
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
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
    objectives: list | None = None,
    questions: list | None = None,
    uncovered: list | None = None,
) -> "prompting._GenerationSchema":
    return prompting._GenerationSchema(
        objectives=(
            [prompting._ProposedObjective(objective_id="blob-basics", title="Blob basics")]
            if objectives is None
            else objectives
        ),
        questions=[_question()] if questions is None else questions,
        uncovered=uncovered or [],
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

    def test_a_plain_run_with_no_questions_is_rejected(self):
        """An empty run is a failure to report, not a result to store.

        The rule now lives in ``build_result`` rather than in the schema,
        because an aimed run (LEARN #63) may legitimately come back with no
        questions and a page of reported gaps: a schema requiring one question
        would have made "invent something" the only valid answer there. The
        rule itself did not move - a page asked for practice and yielding none
        is still an error.
        """
        gen = OpenAIGenerator(client=_FakeClient(_response(_parsed(questions=[]))))
        with pytest.raises(GenerationError, match="no questions"):
            gen.generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))

    def test_a_response_of_more_than_eight_questions_is_rejected(self):
        with pytest.raises(ValidationError):
            _parsed(questions=[_question() for _ in range(9)])


class TestUnitsOfAnExistingGoal:
    """A proposed objective joins a unit the goal already has.

    The rule this exercises is the one that was missing in the field: told
    nothing about the goal's units, generation read a unit off each page of
    notes, and one goal ended up with eighty-four objectives across
    twenty-seven invented units - most of them holding one or two - next to a
    hand-made version of the same syllabus with five (LEARN #50). The units
    are the middle level of the Goal > Unit > Topic tree, so a unit per
    upload does not merely look untidy: it empties that level of meaning.
    """

    def test_domains_of_keeps_first_seen_order_without_duplicates(self):
        objectives = [
            Objective(objective_id="a", title="A", domain="D2"),
            Objective(objective_id="b", title="B", domain="D1"),
            Objective(objective_id="c", title="C", domain="D2"),
        ]
        assert domains_of(objectives) == ("D2", "D1")

    @pytest.mark.parametrize("domain", [None, "", "   "])
    def test_domains_of_ignores_objectives_with_no_unit(self, domain):
        """A goal is not divided into a unit called "" (LEARN #50)."""
        objectives = [Objective(objective_id="a", title="A", domain=domain)]
        assert domains_of(objectives) == ()

    def test_stub_puts_a_proposed_objective_in_an_existing_unit(self):
        result = StubGenerator().generate(
            MATERIAL, existing_objectives=[], existing_domains=["D1", "D2"], now=FixedClock(T0)
        )
        assert [obj.domain for obj in result.objectives] == ["D1"]

    def test_stub_leaves_the_unit_empty_when_the_goal_has_none(self):
        """A goal with no units keeps today's behaviour."""
        result = StubGenerator().generate(MATERIAL, existing_objectives=[], now=FixedClock(T0))
        assert [obj.domain for obj in result.objectives] == [None]

    def test_the_prompt_lists_the_goals_units(self):
        client = _FakeClient(_response(_parsed()))
        OpenAIGenerator(client=client).generate(
            MATERIAL,
            existing_objectives=[Objective(objective_id="s", title="S", domain="D1")],
            existing_domains=["D1", "D2"],
            now=FixedClock(T0),
        )
        sent = str(client.responses.calls[0]["input"])
        assert "Existing units for this goal:" in sent
        assert "- D1\n- D2" in sent
        # The unit each existing objective sits in travels with it too, so
        # the model can see which unit covers what rather than guessing from
        # the unit names alone.
        assert "[unit: D1]" in sent

    def test_the_prompt_says_a_goal_without_units_has_none_yet(self):
        client = _FakeClient(_response(_parsed()))
        OpenAIGenerator(client=client).generate(
            MATERIAL, existing_objectives=[], now=FixedClock(T0)
        )
        assert "no units" in str(client.responses.calls[0]["input"])

    def test_the_instructions_carry_the_unit_rule(self):
        """The rule mirrors the one that keeps objectives from duplicating."""
        client = _FakeClient(_response(_parsed()))
        OpenAIGenerator(client=client).generate(
            MATERIAL, existing_objectives=[], existing_domains=["D1"], now=FixedClock(T0)
        )
        instructions = str(client.responses.calls[0]["instructions"])
        assert "unit" in instructions
        assert "Propose a new unit only for material that no existing unit covers" in instructions

    @pytest.mark.parametrize("proposed", ["  D1  ", "d1", "D1"])
    def test_a_unit_that_differs_only_in_case_or_space_is_snapped_back(self, proposed):
        """Obeying the prompt loosely must not still split the unit in two."""
        parsed = _parsed(
            objectives=[
                prompting._ProposedObjective(
                    objective_id="blob-basics", title="Blob basics", domain=proposed
                )
            ]
        )
        gen = OpenAIGenerator(client=_FakeClient(_response(parsed)))
        result = gen.generate(
            MATERIAL, existing_objectives=[], existing_domains=["D1"], now=FixedClock(T0)
        )
        assert result.objectives[0].domain == "D1"

    def test_a_genuinely_new_unit_is_kept(self):
        """Material no existing unit covers may still found one."""
        parsed = _parsed(
            objectives=[
                prompting._ProposedObjective(
                    objective_id="blob-basics", title="Blob basics", domain="D7"
                )
            ]
        )
        gen = OpenAIGenerator(client=_FakeClient(_response(parsed)))
        result = gen.generate(
            MATERIAL, existing_objectives=[], existing_domains=["D1"], now=FixedClock(T0)
        )
        assert result.objectives[0].domain == "D7"

    def test_a_blank_unit_becomes_no_unit(self):
        """Whitespace is not a unit; stored, it becomes one the tree shows."""
        parsed = _parsed(
            objectives=[
                prompting._ProposedObjective(
                    objective_id="blob-basics", title="Blob basics", domain="   "
                )
            ]
        )
        gen = OpenAIGenerator(client=_FakeClient(_response(parsed)))
        result = gen.generate(
            MATERIAL, existing_objectives=[], existing_domains=["D1"], now=FixedClock(T0)
        )
        assert result.objectives[0].domain is None


class TestAimedAtUncoveredObjectives:
    """A run aimed at the objectives with no question (LEARN #63).

    One rule, asserted several ways because it is enforced in several places:
    **an objective the material does not cover comes back reported, never
    answered.** The counter-example is not hypothetical, it is the easiest way
    to make this feature look successful: twenty-four of the owner's objectives
    have no notes uploaded at all, and a generator willing to write a question
    from general knowledge would close every one of them, raise the coverage
    number, and leave him practising invented material while the missing notes
    stayed missing.
    """

    SEARCH = Material(
        material_id="mat-search",
        topic_id="ai-103",
        title="Azure AI Search",
        source="notes.md",
        body="A skillset enriches the documents of an index during indexing.\n",
        created_at=T0,
    )
    BLOB = Objective(objective_id="D1.1", title="Blob storage", domain="D1")
    SKILLSET = Objective(objective_id="D2.1", title="Search skillsets", domain="D2")
    ABSENT = Objective(objective_id="D3.1", title="Conversational intents", domain="D3")

    def _aimed(self, targets, existing=None):
        return StubGenerator().generate(
            MATERIAL,
            existing_objectives=list(targets) if existing is None else existing,
            uncovered_objectives=targets,
            now=FixedClock(T0),
        )

    def test_the_gap_is_read_off_the_questions(self):
        """Not off a per-objective counter, for the reason SPEC's decision 1
        gives about the attempt history: a counter can disagree with the facts."""
        remaining = targeting.objectives_without_questions(
            [self.BLOB, self.SKILLSET], self._aimed([self.BLOB]).questions
        )
        assert [obj.objective_id for obj in remaining] == ["D2.1"]

    def test_the_plan_aims_each_page_at_the_objectives_it_talks_about(self):
        plan = targeting.plan_coverage_run(
            [MATERIAL, self.SEARCH], [self.BLOB, self.SKILLSET], max_pages=5
        )
        assert {
            step.material.material_id: [obj.objective_id for obj in step.targets]
            for step in plan
        } == {"mat-1": ["D1.1"], "mat-search": ["D2.1"]}

    def test_a_page_sharing_nothing_with_a_target_is_never_scheduled(self):
        """An objective no page mentions costs no model call: the call would
        spend money to be told what the ranking knows, and the gap is reported
        either way. ``max_pages`` bounds the rest."""
        assert (
            targeting.plan_coverage_run([MATERIAL], [self.ABSENT], max_pages=5) == ()
        )
        assert len(
            targeting.plan_coverage_run(
                [MATERIAL, self.SEARCH], [self.BLOB, self.SKILLSET], max_pages=1
            )
        ) == 1

    def test_no_page_is_aimed_at_more_targets_than_one_call_can_answer(self):
        """One word of overlap makes a page a candidate, so a broad page matches
        dozens of objectives; aiming all of them at one call gets most reported
        uncovered by a page that was never about them, with no second page ever
        tried (seen on the owner's real data: 33 of 37 on one page)."""
        targets = [
            Objective(objective_id=f"D1.{i}", title="Blob storage", domain="D1")
            for i in range(12)
        ]
        plan = targeting.plan_coverage_run([MATERIAL], targets, max_pages=1)
        assert len(plan[0].targets) == targeting.MAX_TARGETS_PER_PAGE

    def test_stub_covers_an_objective_the_material_supports(self):
        result = self._aimed([self.BLOB])
        assert [q.objective_id for q in result.questions] == ["D1.1"]
        assert result.uncovered == ()
        # Grounded: the correct option is a sentence of the page itself, not
        # prose written to fill the slot.
        question = result.questions[0]
        assert dict(question.options)[question.correct_key] in MATERIAL.body

    def test_stub_reports_an_objective_the_material_does_not_cover(self):
        """The line this feature must not cross, in the generator the suite runs
        against: asked about something the page never mentions, it answers with
        the gap and a reason instead of with a question. It proposes no
        objective either - one invented beside a target is coverage of
        nothing."""
        result = self._aimed([self.BLOB, self.ABSENT])
        assert [q.objective_id for q in result.questions] == ["D1.1"]
        assert [entry.objective_id for entry in result.uncovered] == ["D3.1"]
        assert result.uncovered[0].reason
        assert result.objectives == ()

    def test_the_prompt_names_the_uncovered_objectives_and_the_rule(self):
        client = _FakeClient(_response(_parsed()))
        OpenAIGenerator(client=client).generate(
            MATERIAL,
            existing_objectives=[self.ABSENT],
            uncovered_objectives=[self.ABSENT],
            now=FixedClock(T0),
        )
        sent = str(client.responses.calls[0]["input"])
        assert "aimed at" in sent
        assert "D3.1: Conversational intents" in sent
        assert "report the rest as uncovered" in sent
        # A fixed question count would be an instruction to reach it, which in
        # an aimed run means inventing what the page does not hold.
        assert "Produce" not in sent
        assert "uncovered" in str(client.responses.calls[0]["instructions"])

    def test_the_model_cannot_claim_coverage_it_did_not_produce(self):
        """It writes no question for the target and says nothing about it.
        Coverage is derived from the questions that were built, so silence is
        read as a gap - with a stated reason - and never as success."""
        gen = OpenAIGenerator(client=_FakeClient(_response(_parsed(questions=[]))))
        result = gen.generate(
            MATERIAL,
            existing_objectives=[self.ABSENT],
            uncovered_objectives=[self.ABSENT],
            now=FixedClock(T0),
        )
        assert result.questions == ()
        assert result.uncovered == (
            UncoveredObjective(
                objective_id="D3.1", reason=prompting.DEFAULT_UNCOVERED_REASON
            ),
        )

    def test_an_aimed_run_reports_the_models_reason_and_drops_its_asides(self):
        """The reason travels; a question written for a well-served objective
        does not, because it is not evidence about the target."""
        parsed = _parsed(
            questions=[_question(objective_id="blob-basics")],
            uncovered=[
                prompting._UncoveredObjective(
                    objective_id="D3.1", reason="the page never mentions intents"
                )
            ],
        )
        gen = OpenAIGenerator(client=_FakeClient(_response(parsed)))
        result = gen.generate(
            MATERIAL,
            existing_objectives=[
                Objective(objective_id="blob-basics", title="Blob basics"),
                self.ABSENT,
            ],
            uncovered_objectives=[self.ABSENT],
            now=FixedClock(T0),
        )
        assert result.questions == ()
        assert result.objectives == ()
        assert result.uncovered[0].reason == "the page never mentions intents"
