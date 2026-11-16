"""The daily digest: what is due today, per topic, with a link to practise.

Rules this module defends (from issue #68):

* **Nothing due means nothing sent.** :func:`build_digest` returns a digest
  with no topics when nothing is due, and :attr:`Digest.is_empty` is how the
  caller knows to stay silent. A reminder that arrives every day regardless
  teaches people to ignore it.
* **Name the thing, not just a count.** Each topic lists its most overdue
  objectives by title, in the engine's own urgency order (SPEC section 5.2),
  and how many days the oldest one has been waiting.
* **Injected time.** ``as_of`` is a required parameter. Choosing "now" is the
  caller's job (the cron script), never this module's (SPEC I2).

The rendered text is user-facing copy, so it is in Spanish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from core.clock import FixedClock
from core.storage import AttemptStore, ProfileStore
from core.tracker import LearningTracker

#: How many objective titles are named per topic. The rest are counted.
DEFAULT_NAMED_PER_TOPIC = 3


@dataclass(frozen=True)
class DueItem:
    """One objective due for review, as the digest names it."""

    objective_id: str
    title: str
    days_overdue: int


@dataclass(frozen=True)
class TopicDigest:
    """What is due in one topic (one engine profile)."""

    topic_id: str
    topic_name: str
    due_count: int
    named: tuple[DueItem, ...]
    practice_url: str


@dataclass(frozen=True)
class Digest:
    """The whole message for one recipient at one date."""

    as_of: datetime
    topics: tuple[TopicDigest, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        """True when nothing is due: the caller must send nothing."""
        return not self.topics

    @property
    def total_due(self) -> int:
        return sum(topic.due_count for topic in self.topics)


def practice_url(base_url: str, topic_id: str) -> str:
    """Deep link into the web UI for one topic.

    ``#/learning/<id>`` opens that goal in the learning tree, where practising
    starts (see ``webui/js/router.js``).
    """
    return f"{base_url.rstrip('/')}/#/learning/{topic_id}"


def build_digest(
    profiles: ProfileStore,
    attempts: AttemptStore,
    as_of: datetime,
    base_url: str,
    topic_ids: Iterable[str] | None = None,
    named_per_topic: int = DEFAULT_NAMED_PER_TOPIC,
) -> Digest:
    """Computes the digest at ``as_of`` from the engine.

    Args:
        profiles: store of profiles (topics) and objectives.
        attempts: store of attempts.
        as_of: the date the digest is computed at. Required: there is no
            "timeless" digest, and this module never reads the clock.
        base_url: public URL of the web app, used for the practice links.
        topic_ids: restrict to these topics; ``None`` means every
            non-archived topic. Unknown or archived ids are skipped.
        named_per_topic: how many objectives to name per topic.

    Returns:
        A :class:`Digest` with one entry per topic that has something due,
        in topic-name order. Topics with nothing due are left out.
    """
    wanted = None if topic_ids is None else set(topic_ids)
    clock = FixedClock(as_of)
    topics: list[TopicDigest] = []
    for profile in profiles.list_profiles():
        if profile.archived:
            continue
        if wanted is not None and profile.profile_id not in wanted:
            continue
        tracker = LearningTracker(profile.profile_id, profiles, attempts, clock)
        due = tracker.get_due(as_of)
        if not due:
            continue
        named = tuple(
            DueItem(
                objective_id=state.objective_id,
                title=_title(profile.objectives, state.objective_id),
                days_overdue=max(0, (as_of - state.next_review_at).days),  # type: ignore[operator]
            )
            for state in due[:named_per_topic]
        )
        topics.append(
            TopicDigest(
                topic_id=profile.profile_id,
                topic_name=profile.name,
                due_count=len(due),
                named=named,
                practice_url=practice_url(base_url, profile.profile_id),
            )
        )
    topics.sort(key=lambda t: (t.topic_name.lower(), t.topic_id))
    return Digest(as_of=as_of, topics=tuple(topics))


def _title(objectives: dict, objective_id: str) -> str:
    objective = objectives.get(objective_id)
    return objective.title if objective is not None and objective.title else objective_id


# ------------------------------------------------------------------ rendering
# User-facing copy below: Spanish (Chile, neutral).


def render_subject(digest: Digest) -> str:
    """Email subject line."""
    total = digest.total_due
    noun = "repaso pendiente" if total == 1 else "repasos pendientes"
    return f"Hoy tienes {total} {noun}"


def render_text(digest: Digest) -> str:
    """Plain-text body. Raises ``ValueError`` on an empty digest.

    Rendering an empty digest is a bug in the caller: nothing due must mean
    nothing sent, so there is no "nothing to do today" message to render.
    """
    if digest.is_empty:
        raise ValueError("refusing to render an empty digest: nothing due means nothing sent")
    lines = ["Esto es lo que te toca repasar hoy:", ""]
    for topic in digest.topics:
        lines.append(f"{topic.topic_name} - {topic.due_count} por repasar")
        for item in topic.named:
            lines.append(f"  - {item.title}{_overdue_suffix(item.days_overdue)}")
        rest = topic.due_count - len(topic.named)
        if rest > 0:
            lines.append(f"  - y {rest} más")
        lines.append(f"  Practicar: {topic.practice_url}")
        lines.append("")
    lines.append("Repasar a tiempo es lo que hace que lo aprendido se quede.")
    return "\n".join(lines) + "\n"


def _overdue_suffix(days: int) -> str:
    if days <= 0:
        return " (vence hoy)"
    if days == 1:
        return " (atrasado 1 día)"
    return f" (atrasado {days} días)"
