"""The data model. See SPEC.md section 1.

Every structure is a ``dataclass(frozen=True)``: immutable by construction. An
``Attempt`` that cannot be mutated cannot be corrupted, and the append-only
history (SPEC I1) stops depending on the discipline of whoever is coding.

Key distinction that runs through the whole module:

* :class:`Attempt` is a **persisted fact**. It is written once and never
  changes.
* :class:`ObjectiveState` is a **computed projection**. It is never persisted;
  it is recomputed from the attempts every time it is asked for (SPEC I4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum

from .errors import InvalidAttemptError


class AttemptKind(str, Enum):
    """What kind of evidence an attempt comes from.

    It does not affect the level computation in v1 (SPEC section 10); it is
    there to filter and to audit where a claim about progress came from.
    """

    QUIZ = "quiz"
    EXERCISE = "exercise"
    LAB = "lab"
    EXAM_SIM = "exam_sim"
    SELF_REPORT = "self_report"


class Level(IntEnum):
    """Mastery level of an objective. See SPEC section 1.4.

    It is an **ordered** ``IntEnum`` on purpose: comparing two levels with ``<``
    has to work, because the user's central question ("was I better two weeks
    ago?") is literally a comparison.
    """

    UNASSESSED = 0
    WEAK = 1
    LEARNING = 2
    COMPETENT = 3
    MASTERED = 4


class SessionStatus(str, Enum):
    """How a recording session ended (SPEC section 9.6)."""

    #: At least one attempt was recorded.
    RECORDED = "recorded"
    #: The session was closed without recording anything. Visible on purpose:
    #: it is the signal that someone forgot to record (SPEC section 8,
    #: failure 4).
    EMPTY = "empty"


@dataclass(frozen=True)
class Objective:
    """An assessable unit of knowledge. See SPEC section 1.2.

    Note what it does **not** have: no level, no streak, no counters, no review
    date. All of that consists of projections of the history and lives in
    :class:`ObjectiveState`. The day a mutable progress field shows up here,
    failure 3 (corrupt, irreversible counters) becomes possible again.

    Attributes:
        objective_id: unique within the profile. E.g. ``"D3.2-content-understanding"``.
        title: human readable description.
        domain: optional grouping. E.g. ``"D3"``.
        weight: relative weight in the exam. Informational; it does not affect
            the level.
        tags: free-form labels used to filter.
    """

    objective_id: str
    title: str
    domain: str | None = None
    weight: float = 1.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    """A study subject with its objectives. See SPEC section 1.1.

    Profiles are isolated from each other (SPEC I7): no attempt in one profile
    influences the state of another. Multi-profile is not a requirement today,
    but that isolation means adding it will not force a redesign.

    ``archived`` is the one field here that is neither an identifier nor a
    catalog, and it is deliberately **not** progress: nothing in ``core/``
    reads it, so no computation can change because a profile was archived. It
    exists because a topic that is no longer being studied still has to keep
    its history — deleting it would destroy attempts, which the append-only
    guarantee (SPEC I1) forbids — while disappearing from the list of what is
    being studied. Note also SPEC C5: the engine never archives anything on
    its own, however long a topic goes untouched. Archiving is always an
    explicit human act, recorded here as a fact like any other.

    Attributes:
        profile_id: stable identifier. E.g. ``"ai-103"``.
        name: human readable name.
        objectives: objectives indexed by ``objective_id``.
        archived: whether the topic is put away. It hides the profile from the
            default listing and nothing else: attempts, objectives and every
            computed state stay exactly as they were.
    """

    profile_id: str
    name: str
    objectives: dict[str, Objective] = field(default_factory=dict)
    archived: bool = False


@dataclass(frozen=True)
class Attempt:
    """A fact that happened: on this date the answer was right or wrong. See
    SPEC section 1.3.

    **Immutable and append-only.** There is no API to modify or delete it (SPEC
    I1). It is the only data persisted as truth; everything else is derived from
    a collection of these.

    ``at`` is supplied by whoever records, never by the engine: that is what
    lets a bot simulate "wrong, wrong, wrong, right, wrong" on arbitrary dates
    and what made failure 5 impossible.

    Attributes:
        attempt_id: unique, immutable identifier. A duplicate is an error.
        objective_id: objective it belongs to.
        at: **when it happened**, aware (with ``tzinfo``). It is the axis for
            sorting and for every time cut.
        correct: ``True`` hit, ``False`` miss. The only binary axis.
        kind: nature of the evidence.
        confidence: self assessment 0.0-1.0. It does not affect the level in v1.
        note: free text (the question, why it failed...).
        recorded_at: when it was written to the store, if it differs from
            ``at``. Audit only; it is **never** used to sort or to cut, so that
            inserting out of order does not alter results (SPEC C4).
    """

    attempt_id: str
    objective_id: str
    at: datetime
    correct: bool
    kind: AttemptKind = AttemptKind.QUIZ
    confidence: float | None = None
    note: str | None = None
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validates the attempt at construction time. See SPEC section 1.3.

        A malformed ``Attempt`` must never reach the store: since it is
        immutable, persisted invalid data would be invalid forever. Every
        violation raises :class:`InvalidAttemptError`.

        The message text stays in Spanish on purpose: it reaches the user
        through the CLI as ``error: ...``.
        """
        if not isinstance(self.attempt_id, str) or not self.attempt_id.strip():
            raise InvalidAttemptError("attempt_id no puede estar vacío")
        if not isinstance(self.objective_id, str) or not self.objective_id.strip():
            raise InvalidAttemptError("objective_id no puede estar vacío")
        _require_aware(self.at, "at")
        if self.recorded_at is not None:
            _require_aware(self.recorded_at, "recorded_at")
        if not isinstance(self.correct, bool):
            raise InvalidAttemptError("correct debe ser bool")
        if not isinstance(self.kind, AttemptKind):
            raise InvalidAttemptError(f"kind inválido: {self.kind!r}")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(
                self.confidence, (int, float)
            ):
                raise InvalidAttemptError("confidence debe ser un número o None")
            if not 0.0 <= self.confidence <= 1.0:
                raise InvalidAttemptError(
                    f"confidence fuera de [0, 1]: {self.confidence!r}"
                )


def _require_aware(value: datetime, name: str) -> None:
    """Demands an aware ``datetime`` (SPEC section 1.3): no timezone, no order."""
    if not isinstance(value, datetime):
        raise InvalidAttemptError(f"{name} debe ser datetime, no {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidAttemptError(f"{name} debe llevar zona horaria (aware)")


@dataclass(frozen=True)
class ObjectiveState:
    """The derived state of an objective at a date. See SPEC section 1.5.

    **It is never persisted.** It is always the result of recomputing from the
    attempts with ``at <= as_of`` (SPEC I4, I6). That is why corruption of
    aggregated data is irrelevant: delete it and compute it again.

    There is no ``streak`` field and there never will be (SPEC I10). Progress is
    read from ``score`` (continuous, weighted by recency), from the accumulated
    counters and from ``recent_window`` (the literal sequence). An objective
    with 5 mixed answers shows all 5 attempts here and an intermediate score,
    not a "1" that looks like nothing was saved.

    Attributes:
        objective_id: which objective this belongs to.
        as_of: cut date it was computed with. Without this the state means
            nothing: every state is state *at a date*.
        level: level according to SPEC section 2.
        score: continuous score 0.0-1.0 that produced the level. It tells two
            objectives of the same level apart and makes visible an improvement
            that has not crossed a threshold yet.
        total_attempts: attempts with ``at <= as_of``. It only grows.
        correct_attempts: how many of them were hits.
        recent_window: the last ``WINDOW`` results, **from oldest to most
            recent**. The order matters: the weights are positional.
        first_attempt_at: first attempt up to ``as_of``, or ``None``.
        last_attempt_at: last attempt up to ``as_of``, or ``None``.
        distinct_days: distinct calendar days with at least one attempt. Two
            attempts on the same day count as one (SPEC C3).
        days_since_last: fractional days between the last attempt and ``as_of``.
            It is the ``gap`` that feeds the decay.
        retention: decay factor applied, in [``RETENTION_FLOOR``, 1.0].
        next_review_at: next review according to SPEC section 4, or ``None``
            when there are no attempts.
        is_due: ``next_review_at is not None and next_review_at <= as_of``.
    """

    objective_id: str
    as_of: datetime
    level: Level
    score: float
    total_attempts: int
    correct_attempts: int
    recent_window: tuple[bool, ...]
    first_attempt_at: datetime | None
    last_attempt_at: datetime | None
    distinct_days: int
    days_since_last: float | None
    retention: float
    next_review_at: datetime | None
    is_due: bool


@dataclass(frozen=True)
class StateComparison:
    """Two states of the same objective at two dates. See SPEC section 5.1.

    It exists to answer directly the question the user set as a requirement:
    *"was I better two weeks ago than this week?"*.

    Attributes:
        objective_id: objective compared.
        earlier: state at the earlier date.
        later: state at the later date.
        level_delta: ``later.level - earlier.level``. Positive = improved.
        score_delta: ``later.score - earlier.score``.
        improved: ``score_delta > 0``.
        regressed: ``score_delta < 0``.
    """

    objective_id: str
    earlier: ObjectiveState
    later: ObjectiveState
    level_delta: int
    score_delta: float
    improved: bool
    regressed: bool


@dataclass(frozen=True)
class ProfileSummary:
    """Profile aggregate at a date. See SPEC section 9.4.

    Attributes:
        profile_id: profile summarized.
        as_of: cut date.
        total_objectives: objectives defined in the profile.
        by_level: how many objectives sit at each level. It covers all five
            levels, with 0 where there is none.
        assessed_objectives: objectives whose level is not ``UNASSESSED``.
        unstarted_objectives: objectives without a single attempt.
        due_objectives: objectives due for review.
        total_attempts: attempts recorded across the whole profile up to
            ``as_of``.
        mean_score: arithmetic mean of the ``score`` of every objective.
        coverage: ``assessed_objectives / total_objectives``, in [0.0, 1.0].
    """

    profile_id: str
    as_of: datetime
    total_objectives: int
    by_level: dict[Level, int]
    assessed_objectives: int
    unstarted_objectives: int
    due_objectives: int
    total_attempts: int
    mean_score: float
    coverage: float


@dataclass(frozen=True)
class ConsistencyCheck:
    """A single consistency comparison. See SPEC section 9.5.

    ``expected`` and ``actual`` are **numbers** (counts or sums), not sets. That
    is the fix for failure 2: comparing membership lets duplicates and
    cardinality mismatches through; comparing counts does not.

    Attributes:
        name: what was checked. E.g. ``"attempt_count"``.
        expected: expected value, recomputed from the history.
        actual: value observed in the store.
        passed: ``expected == actual``. No tolerance for integers.
        detail: readable context when it fails.
    """

    name: str
    expected: float
    actual: float
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class ConsistencyReport:
    """Result of the consistency check. See SPEC section 8, failure 2.

    It is neither a boolean nor an "OK" string: it carries the numbers from both
    sides of every comparison, so that a mismatch is impossible to print as
    correct.

    ``ok`` is defined **positively**: every check passed *and* at least one
    objective was checked. Having found no errors because nothing was checked is
    **not** ``ok``.

    Attributes:
        ok: see above.
        checks: every comparison performed, with its numbers.
        objectives_checked: how many objectives were walked.
        as_of: cut date of the check.
    """

    ok: bool
    checks: tuple[ConsistencyCheck, ...]
    objectives_checked: int
    as_of: datetime

    @property
    def failures(self) -> tuple[ConsistencyCheck, ...]:
        """Only the checks that did not pass."""
        return tuple(check for check in self.checks if not check.passed)


@dataclass(frozen=True)
class SessionReport:
    """What happened during a recording session. See SPEC section 9.6.

    Its reason to exist is failure 4: closing a session without having recorded
    anything produces ``status=EMPTY``, an explicit and visible result, instead
    of a silence indistinguishable from "all good".

    Attributes:
        session_id: identifier of the session.
        started_at: opening instant (injected).
        ended_at: closing instant (injected).
        attempts_recorded: how many attempts were written.
        objectives_touched: ids of the objectives with at least one attempt.
        status: ``RECORDED`` or ``EMPTY``.
    """

    session_id: str
    started_at: datetime
    ended_at: datetime | None
    attempts_recorded: int
    objectives_touched: tuple[str, ...]
    status: SessionStatus
