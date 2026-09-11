"""Topics router: list, create and fetch one topic with its objectives.

**Vocabulary translation, contained here and nowhere else:** the product
calls the thing being studied a "topic"; the engine calls the exact same
object a "profile" (``core.models.Profile``, ``core.storage.ProfileStore``).
Every request/response model in this module says "topic"; every call into
``resources.profiles`` says "profile", matching the engine's own words. No
other module in ``web/`` should need to translate again.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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


class TopicCreate(BaseModel):
    """Body to create a topic. It starts with no objectives."""

    topic_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ObjectiveOut(BaseModel):
    """One objective of a topic, as returned to clients."""

    objective_id: str
    title: str
    domain: str | None
    weight: float
    tags: tuple[str, ...]


class TopicDetail(BaseModel):
    """A topic with its objectives."""

    topic_id: str
    name: str
    objectives: list[ObjectiveOut]


def _to_summary(profile: Profile) -> TopicSummary:
    return TopicSummary(
        topic_id=profile.profile_id,
        name=profile.name,
        objective_count=len(profile.objectives),
    )


def _to_objective_out(objective: Objective) -> ObjectiveOut:
    return ObjectiveOut(
        objective_id=objective.objective_id,
        title=objective.title,
        domain=objective.domain,
        weight=objective.weight,
        tags=objective.tags,
    )


@router.get("", response_model=list[TopicSummary])
def list_topics(resources: Resources = Depends(get_resources)) -> list[TopicSummary]:
    """Every topic, sorted by id (SPEC's ``list_profiles``)."""
    return [_to_summary(profile) for profile in resources.profiles.list_profiles()]


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
    """
    try:
        profile = resources.profiles.get_profile(topic_id)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc
    objectives = [
        _to_objective_out(profile.objectives[key]) for key in sorted(profile.objectives)
    ]
    return TopicDetail(topic_id=profile.profile_id, name=profile.name, objectives=objectives)


__all__ = ["router"]
