"""Teacher view: a read-only picture of an organization's progress (issue #75).

Two routes, both read-only:

* ``GET /me`` - who the session is and whether it may open the teacher view,
  so the front end can decide whether to offer it. Authorization is still
  enforced by the server on every route; this is only a hint for the UI.
* ``GET /org/progress`` - for each member of the caller's *active*
  organization, one row per topic: the typical level, how many objectives are
  due and how many were never practised. Allowed for ``org:admin`` only (403
  for anyone else, including a session with no active organization).

**Nothing is recomputed here.** Each member's numbers come from the same
``LearningTracker.get_summary`` the member's own progress screen uses, run
over that member's own scoped stores (``Resources.for_user``). The one thing
this module derives is the "typical level" of a topic, the median of its
objectives' levels, because the engine's summary counts objectives per level
and a table wants one chip per topic.

The organization comes from the verified token (``web/auth.py``), never from
the path or the query, so an admin cannot ask about another organization.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.models import Level

from ..auth import Identity, require_session
from ..deps import Resources, get_resources

router = APIRouter(tags=["org"])


class MeOut(BaseModel):
    user_id: str
    org_id: str | None
    org_role: str | None
    is_teacher: bool


class TopicProgressOut(BaseModel):
    topic_id: str
    name: str
    level: str
    total_objectives: int
    due_objectives: int
    unstarted_objectives: int
    total_attempts: int
    mean_score: float


class MemberProgressOut(BaseModel):
    user_id: str
    display_name: str
    role: str
    last_seen: datetime
    topics: list[TopicProgressOut]


class OrgProgressOut(BaseModel):
    org_id: str
    as_of: datetime
    members: list[MemberProgressOut]


def typical_level(by_level: dict[Level, int]) -> Level:
    """The median level across a topic's objectives (the lower median on an
    even count). ``UNASSESSED`` for a topic with no objectives."""
    ordered = [level for level in sorted(by_level) for _ in range(by_level[level])]
    if not ordered:
        return Level.UNASSESSED
    return ordered[(len(ordered) - 1) // 2]


@router.get("/me", response_model=MeOut)
def me(identity: Identity = Depends(require_session)) -> MeOut:
    return MeOut(
        user_id=identity.user_id,
        org_id=identity.org_id,
        org_role=identity.org_role,
        is_teacher=identity.is_org_admin,
    )


def require_org_admin(identity: Identity = Depends(require_session)) -> Identity:
    """403 unless the verified session is an admin of its active organization.

    A separate dependency, declared before ``get_resources`` on the route, so
    a non-admin is refused before anything touches storage."""
    if not identity.is_org_admin:
        raise HTTPException(status_code=403, detail="only organization admins can see this")
    return identity


@router.get("/org/progress", response_model=OrgProgressOut)
def org_progress(
    identity: Identity = Depends(require_org_admin),
    resources: Resources = Depends(get_resources),
) -> OrgProgressOut:
    """Per member, per topic: typical level, due, never practised."""
    now = resources.clock.now()
    members = []
    for member in resources.members.list_members(identity.org_id):
        # The teacher's own learning lives on their own screen.
        if member.user_id == identity.user_id:
            continue
        scoped = resources.for_user(member.user_id)
        topics = []
        for profile in scoped.profiles.list_profiles():
            if profile.archived:
                continue
            summary = scoped.tracker_for(profile.profile_id).get_summary(now)
            topics.append(
                TopicProgressOut(
                    topic_id=profile.profile_id,
                    name=profile.name,
                    level=typical_level(summary.by_level).name,
                    total_objectives=summary.total_objectives,
                    due_objectives=summary.due_objectives,
                    unstarted_objectives=summary.unstarted_objectives,
                    total_attempts=summary.total_attempts,
                    mean_score=summary.mean_score,
                )
            )
        members.append(
            MemberProgressOut(
                user_id=member.user_id,
                display_name=member.display_name or member.email or member.user_id,
                role=member.role,
                last_seen=member.last_seen,
                topics=topics,
            )
        )
    return OrgProgressOut(org_id=identity.org_id, as_of=now, members=members)
