"""Material router: upload a page of notes, and turn it into practice.

**Vocabulary**, the same rule the other routers keep: the product says
"topic", the engine says "profile". This module keeps to "topic" in every
request and response model, and translates only where it addresses the
engine's stores.

**Material is append-only**, exactly as attempts are. ``MaterialStore`` offers
no update and no delete, and that absence is the guarantee rather than an
omission (see ``content.storage``). So there is no endpoint here that edits or
removes a page; a corrected page is a new upload.

**Regenerating replaces questions and never touches attempts.** Questions are
derived and disposable: regenerating from the same material swaps that
material's whole question set atomically. Attempts are evidence of what
somebody knew at a moment, they are append-only by contract, and the engine
exposes no way to delete one. A learner who regenerates keeps every recorded
answer (SPEC I1).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from content.errors import UnknownMaterialError
from content.models import Material
from core.errors import UnknownProfileError
from generate.errors import GenerationError, MissingCredentialsError
from generate.generator import domains_of

from ..deps import Resources, get_resources

router = APIRouter(prefix="/topics/{topic_id}/material", tags=["material"])

#: Largest page of notes accepted, in characters.
#:
#: A page of study notes is prose. A megabyte of it is around 200,000 words,
#: far past anything one page of notes contains and well past what the
#: generator can read in a single request, so a body above this is a mistake
#: (a pasted binary, a whole book, a runaway export) rather than an unusually
#: thorough page. Refusing it is kinder than accepting it and failing later
#: inside the model call, where the reason would be much less clear.
MAX_BODY_CHARS = 200_000


class MaterialIn(BaseModel):
    """A page of study notes being uploaded.

    Every field is rejected when it is only whitespace, and that is not
    decoration. ``Material`` considers a blank field empty and refuses to be
    built from one, so without this check a title of three spaces passed
    validation here, failed inside the domain model, and reached the caller as
    an unhandled 500: a client mistake reported as a server fault. The two
    layers have to agree on what "not empty" means.
    """

    title: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)

    @field_validator("title", "source", "body")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class MaterialSummaryOut(BaseModel):
    """One material without its body, for listings."""

    material_id: str
    topic_id: str
    title: str
    source: str
    created_at: datetime


class MaterialOut(MaterialSummaryOut):
    """One material including its body."""

    body: str


class GenerationOut(BaseModel):
    """What one generation run produced."""

    material_id: str
    objectives_written: int
    questions_written: int


def _to_summary(material: Material) -> MaterialSummaryOut:
    return MaterialSummaryOut(
        material_id=material.material_id,
        topic_id=material.topic_id,
        title=material.title,
        source=material.source,
        created_at=material.created_at,
    )


def _to_out(material: Material) -> MaterialOut:
    return MaterialOut(**_to_summary(material).model_dump(), body=material.body)


def _require_topic(resources: Resources, topic_id: str) -> None:
    """Fails with a named 404 when the topic does not exist.

    Checked before writing anything: material carrying a topic id that names
    no topic would be unreachable from every listing, which is the same shape
    of orphan the content package already forbids between questions and their
    material.
    """
    try:
        resources.profiles.get_profile(topic_id)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=f"unknown topic: {topic_id}") from exc


def _owned_material(resources: Resources, topic_id: str, material_id: str) -> Material:
    """One material, verified to belong to this topic.

    Material ids are unique across topics, so fetching by id alone would let
    ``/topics/other/material/{id}`` return a page belonging to somebody else's
    topic. The ownership check is what keeps the URL honest.
    """
    try:
        material = resources.materials.get(material_id)
    except UnknownMaterialError as exc:
        raise HTTPException(
            status_code=404, detail=f"unknown material: {material_id}"
        ) from exc
    if material.topic_id != topic_id:
        raise HTTPException(
            status_code=404,
            detail=f"material {material_id} does not belong to topic {topic_id}",
        )
    return material


@router.post("", response_model=MaterialOut, status_code=201)
def upload_material(
    topic_id: str, payload: MaterialIn, resources: Resources = Depends(get_resources)
) -> MaterialOut:
    """Stores a page of notes under a topic.

    The upload does not generate anything. Generation is a separate, explicitly
    requested step because it costs money and takes seconds, and because a page
    is worth keeping whether or not questions are wanted from it yet.
    """
    if len(payload.body) > MAX_BODY_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"material body is {len(payload.body)} characters, over the "
                f"{MAX_BODY_CHARS} limit"
            ),
        )
    _require_topic(resources, topic_id)
    material = Material(
        material_id=uuid4().hex,
        topic_id=topic_id,
        title=payload.title,
        source=payload.source,
        body=payload.body,
        created_at=resources.clock.now(),
    )
    return _to_out(resources.materials.add(material))


@router.get("", response_model=list[MaterialSummaryOut])
def list_material(
    topic_id: str, resources: Resources = Depends(get_resources)
) -> list[MaterialSummaryOut]:
    """The topic's material, newest first, without bodies.

    Bodies are whole pages of notes; sending every one of them to render a
    list would make the list slower the more material a topic has, which is
    backwards.
    """
    _require_topic(resources, topic_id)
    materials = resources.materials.list_for_topic(topic_id)
    return [_to_summary(m) for m in reversed(materials)]


@router.get("/{material_id}", response_model=MaterialOut)
def get_material(
    topic_id: str, material_id: str, resources: Resources = Depends(get_resources)
) -> MaterialOut:
    """One page of notes, body included."""
    _require_topic(resources, topic_id)
    return _to_out(_owned_material(resources, topic_id, material_id))


@router.post("/{material_id}/generate", response_model=GenerationOut)
def generate_from_material(
    topic_id: str, material_id: str, resources: Resources = Depends(get_resources)
) -> GenerationOut:
    """Turns one page of notes into objectives and questions.

    The generator is told which objectives the topic already has, so it
    attaches questions to them rather than proposing near-duplicates, and
    which units (``Objective.domain``) the goal is divided into, so that an
    objective it does propose joins one of them. Without that second list a
    page of notes founds its own units, and a goal ends up with as many
    units as it has uploads instead of the handful its syllabus has.

    Objectives are written with ``upsert_objectives``, which adds or overwrites
    and never deletes one that did not come back: a second page of notes about
    a different part of the syllabus must not remove the first page's
    objectives.

    Questions are written with ``replace_for_material``, atomically, so
    regenerating swaps that material's set rather than accumulating duplicates
    of it. **Attempts are untouched.** Nothing here can reach them, and nothing
    should: they are the record of what somebody knew, and regenerating the
    questions does not un-know it.
    """
    _require_topic(resources, topic_id)
    material = _owned_material(resources, topic_id, material_id)
    existing = resources.profiles.list_objectives(topic_id)

    try:
        result = resources.generator.generate(
            material, existing, domains_of(existing), now=resources.clock
        )
    except MissingCredentialsError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"question generation is not configured: {exc}",
        ) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=f"generation failed: {exc}") from exc

    objectives_written = (
        resources.profiles.upsert_objectives(topic_id, result.objectives)
        if result.objectives
        else 0
    )
    questions_written = resources.questions.replace_for_material(
        material_id, result.questions
    )
    return GenerationOut(
        material_id=material_id,
        objectives_written=objectives_written,
        questions_written=questions_written,
    )


__all__ = ["router", "MAX_BODY_CHARS"]
