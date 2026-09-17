"""Topics router: list, create and fetch one topic with its objectives.

**Vocabulary translation, contained here and nowhere else:** the product
calls the thing being studied a "topic"; the engine calls the exact same
object a "profile" (``core.models.Profile``, ``core.storage.ProfileStore``).
Every request/response model in this module says "topic"; every call into
``resources.profiles`` says "profile", matching the engine's own words. No
other module in ``web/`` should need to translate again.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.errors import UnknownProfileError
from core.models import Objective, Profile

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics", tags=["topics"])


class TopicSummary(BaseModel):
    """A topic as listed, without its objectives."""

    topic_id: str
    name: str
    objective_count: int
    archived: bool


class TopicCreate(BaseModel):
    """Body to create a topic. It starts with no objectives."""

    topic_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ObjectiveOut(BaseModel):
    """One objective of a topic, as returned to clients.

    ``has_questions`` is the one field here that is not the objective's own
    data: it says whether the question store holds at least one question for
    this objective in this topic. It lives here, on the listing the practice
    tree is already built from, because the alternative is a client that
    offers every row and discovers which ones are practisable by 404ing on
    them one at a time (this repo has questions for only a fraction of its
    objectives).

    A boolean and not a count, deliberately. The count of stored questions
    is not a measure of anything a person should act on -- it is content
    inventory, and a UI given the number will end up showing it as if it
    were coverage or progress, which the engine computes from attempts and
    from nothing else (SPEC section 0, decision 1). The only honest question
    at this boundary is the one the UI actually asks: can this row be
    practised at all.
    """

    objective_id: str
    title: str
    domain: str | None
    weight: float
    tags: tuple[str, ...]
    has_questions: bool


class TopicDetail(BaseModel):
    """A topic with its objectives."""

    topic_id: str
    name: str
    objectives: list[ObjectiveOut]
    archived: bool


class TopicArchiveUpdate(BaseModel):
    """Body of the archive endpoint: where the topic should end up.

    The desired state, not a verb, so the call is idempotent: archiving an
    already archived topic is a success that changes nothing, and a client
    that retries after a timeout cannot toggle the flag back by accident.
    """

    archived: bool


def _to_summary(profile: Profile) -> TopicSummary:
    return TopicSummary(
        topic_id=profile.profile_id,
        name=profile.name,
        objective_count=len(profile.objectives),
        archived=profile.archived,
    )


def _to_objective_out(objective: Objective, has_questions: bool) -> ObjectiveOut:
    return ObjectiveOut(
        objective_id=objective.objective_id,
        title=objective.title,
        domain=objective.domain,
        weight=objective.weight,
        tags=objective.tags,
        has_questions=has_questions,
    )


@router.get("", response_model=list[TopicSummary])
def list_topics(
    archived: bool = Query(
        False, description="List the archived topics instead of the active ones."
    ),
    resources: Resources = Depends(get_resources),
) -> list[TopicSummary]:
    """The topics being studied, sorted by id (SPEC's ``list_profiles``).

    Archived ones are left out **by default**, because this listing is the
    home screen: a topic is archived precisely to stop appearing here. They
    are not unreachable, they are one query parameter away — ``?archived=true``
    lists them, and the archive is a listing of its own rather than a subset
    nobody can name.

    The filter runs here and not in the store on purpose: the store's job is
    to answer what exists (see ``ProfileStore.list_profiles``), and which half
    of it a screen wants to show is a product decision that belongs in the
    layer that knows about screens.
    """
    return [
        _to_summary(profile)
        for profile in resources.profiles.list_profiles()
        if profile.archived == archived
    ]


@router.post("", response_model=TopicSummary, status_code=201)
def create_topic(
    body: TopicCreate, resources: Resources = Depends(get_resources)
) -> TopicSummary:
    """Creates a topic with no objectives yet.

    409 when a topic with that id already exists: ``ProfileStore.save_profile``
    would silently overwrite it (it is an upsert, SPEC section 9.1), which is
    not what "create" should do at this layer.
    """
    try:
        resources.profiles.get_profile(body.topic_id)
    except UnknownProfileError:
        pass
    else:
        raise HTTPException(
            status_code=409, detail=f"topic already exists: {body.topic_id}"
        )
    profile = Profile(profile_id=body.topic_id, name=body.name, objectives={})
    saved = resources.profiles.save_profile(profile)
    return _to_summary(saved)


@router.get("/{topic_id}", response_model=TopicDetail)
def get_topic(topic_id: str, resources: Resources = Depends(get_resources)) -> TopicDetail:
    """One topic with its objectives.

    404, naming the missing topic, when it does not exist: the engine's
    ``UnknownProfileError`` translated to HTTP rather than swallowed into an
    empty success (SPEC I8 — a failed lookup is never confused with one that
    found nothing).

    Each objective carries ``has_questions`` so a client can tell which rows
    are practisable before offering them (see ``ObjectiveOut``). It costs one
    read of the topic's questions, not one per objective: the ids are
    collected from a single ``list_for_topic`` call, and an objective with no
    question simply does not appear in it.
    """
    try:
        profile = resources.profiles.get_profile(topic_id)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc
    with_questions = {
        question.objective_id for question in resources.questions.list_for_topic(topic_id)
    }
    objectives = [
        _to_objective_out(profile.objectives[key], key in with_questions)
        for key in sorted(profile.objectives)
    ]
    return TopicDetail(
        topic_id=profile.profile_id,
        name=profile.name,
        objectives=objectives,
        archived=profile.archived,
    )


@router.put("/{topic_id}/archived", response_model=TopicSummary)
def set_topic_archived(
    topic_id: str,
    body: TopicArchiveUpdate,
    resources: Resources = Depends(get_resources),
) -> TopicSummary:
    """Archives a topic, or brings it back. The one door to the flag.

    ``PUT`` and not ``DELETE``: nothing is deleted. The topic keeps every
    attempt and every objective it had, which is the whole reason this exists
    instead of a delete endpoint — attempts are append-only evidence of what
    somebody knew (SPEC I1), and a topic that stopped being studied is not a
    topic that was never studied.

    404, naming the missing topic, when it does not exist: archiving a
    misspelled id is a mistake worth hearing about, not a silent no-op.
    """
    try:
        profile = resources.profiles.set_archived(topic_id, body.archived)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc
    return _to_summary(profile)


__all__ = ["router"]
