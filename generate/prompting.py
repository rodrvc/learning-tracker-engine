"""Everything about question quality that does not depend on the provider.

The prompt, the response schema and the option shuffle live here rather than
beside a particular SDK, because they are the part worth keeping when the
provider changes - and it has changed once already.

The actual point of this module: a question whose wrong options are obviously
wrong measures nothing, because the engine (SPEC section 2) will faithfully
record a meaningless correct answer as evidence of mastery. So the prompt asks
for distractors that are plausible confusions drawn from the material's own
content; the schema requires a justification for every wrong option, so a
missing one is a validation error rather than a quality regression nobody
notices; and the correct option is moved to a random position rather than
trusting the model not to default to the first one. Structure where a
structural guarantee is available, instruction only where it is not.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Sequence

from pydantic import BaseModel, Field, model_validator

from content.errors import InvalidQuestionError
from content.models import Material, Question
from core.models import Objective

from .errors import GenerationError
from .generator import GenerationResult

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

Every objective belongs to a unit: a coarse division of the goal, a handful \
of them for the whole syllabus, not one per page of notes. You will also be \
given the units the goal already has. Put every objective you propose into \
one of those units, spelled exactly as given. Propose a new unit only for \
material that no existing unit covers, and never one that is a rewording of \
an existing unit. Leave an objective's unit empty only when the goal has no \
units at all.

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
    return "\n".join(
        f"- {obj.objective_id}: {obj.title}"
        + (f" [unit: {obj.domain}]" if obj.domain else "")
        for obj in objectives
    )


def _existing_domains_digest(domains: Sequence[str]) -> str:
    """The goal's units, for the prompt.

    Listed separately from the objectives above even though each objective
    already carries its own, because the rule is about the list: a model
    reading twenty objective lines has to infer how many distinct units
    there are, and inferring "these are all the units there are" from a
    sample is exactly the step that produced twenty-seven of them.
    """
    if not domains:
        return "(none yet - this goal has no units, so propose the ones this material needs)"
    return "\n".join(f"- {domain}" for domain in domains)


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


def _reconciled_domain(domain: str | None, existing_domains: Sequence[str]) -> str | None:
    """``domain`` snapped onto an existing unit it only differs from in case
    or surrounding space.

    The prompt asks for the unit spelled exactly as given, and a model that
    answers "cuotas" for the unit "Cuotas" has obeyed the rule it was given
    while still founding a second unit holding one objective - which is the
    failure this whole change is about. Whether an existing unit was meant
    is a judgement call in general; where the two strings match once cased
    and stripped it is not, so that much is settled here rather than asked
    for. Anything further apart is left alone: it is a new unit, and the
    prompt is what has to keep those rare.
    """
    stripped = (domain or "").strip()
    if not stripped:
        return None
    folded = stripped.casefold()
    for existing in existing_domains:
        if existing.strip().casefold() == folded:
            return existing
    return stripped


def build_result(
    random_source: random.Random,
    material: Material,
    existing_objectives: Sequence[Objective],
    existing_domains: Sequence[str],
    parsed: _GenerationSchema,
    created_at: datetime,
) -> GenerationResult:
    known_ids = {obj.objective_id for obj in existing_objectives}
    try:
        objectives = tuple(
            Objective(
                objective_id=obj.objective_id,
                title=obj.title,
                domain=_reconciled_domain(obj.domain, existing_domains),
            )
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
                random_source, proposed.options, proposed.correct_key
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
