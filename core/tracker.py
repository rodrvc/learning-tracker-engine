"""The engine. See SPEC.md section 9.4.

:class:`LearningTracker` is the facade: it orchestrates store + clock + pure
computation. It holds no business rules of its own — the rules live in
``leveling`` and ``scheduling``, and their specification in SPEC sections 2
and 4.

Two design traits worth keeping in mind while implementing:

* **Every query accepts ``as_of``.** There is no "timeless" query.
  ``as_of=None`` means "use ``clock.now()``", and the ``Clock`` was chosen by
  whoever built the tracker: it is still injected time (SPEC I2).
* **Nothing is cached as truth.** If a cache is added for performance, it must
  satisfy I6: deleting it and recomputing produces an identical state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence
from uuid import uuid4

from .clock import Clock
from .constants import DEFAULT_STALE_DAYS
from .errors import DuplicateAttemptError, InvalidRangeError
from .leveling import compute_state
from .models import (
    Attempt,
    AttemptKind,
    ConsistencyCheck,
    ConsistencyReport,
    Level,
    ObjectiveState,
    Profile,
    ProfileSummary,
    StateComparison,
)
from .session import SessionRecorder
from .storage import AttemptStore, ProfileStore


class LearningTracker:
    """Tracking engine over **one** profile.

    Multi-profile is achieved by instantiating several trackers over the same
    stores: profiles are isolated (SPEC I7), so they do not interfere with each
    other.

    Args:
        profile_id: profile this instance operates on.
        profiles: store of profiles and objectives.
        attempts: store of attempts (append-only).
        clock: source of "now" for when no explicit ``as_of`` is given. In
            tests, a :class:`~core.clock.FixedClock`.
    """

    def __init__(
        self,
        profile_id: str,
        profiles: ProfileStore,
        attempts: AttemptStore,
        clock: Clock,
    ) -> None:
        self._profile_id = profile_id
        self._profiles = profiles
        self._attempts = attempts
        self._clock = clock

    @property
    def profile_id(self) -> str:
        """Profile this tracker operates on."""
        return self._profile_id

    @property
    def clock(self) -> Clock:
        """The injected clock, exposed for collaborators like ``SessionRecorder``.

        Read only. It is still I2: the ``Clock`` was chosen by whoever built the
        tracker; exposing it opens no door to the system clock.
        """
        return self._clock

    def _resolve(self, as_of: datetime | None) -> datetime:
        """Explicit ``as_of``, or ``clock.now()`` when ``None`` (SPEC section 9.4)."""
        return self._clock.now() if as_of is None else as_of

    def _state(self, objective_id: str, as_of: datetime) -> ObjectiveState:
        """Wraps :func:`compute_state` over what the store returns (I4).

        The cut is by ``at`` (``until=as_of``) and the store applies it; the
        tracker recomputes nothing on its own.
        """
        history = self._attempts.list_for_objective(
            self._profile_id, objective_id, until=as_of
        )
        return compute_state(objective_id, history, as_of)

    def _all_states(
        self, as_of: datetime, listed: Sequence[Attempt] | None = None
    ) -> list[ObjectiveState]:
        """Every state of the profile from **one** global read.

        It performs a single ``list_all(profile_id, until=as_of)`` and groups by
        ``objective_id`` before calling :func:`compute_state` per objective.
        This is performance only: reading ``list_for_objective`` N times or
        ``list_all`` once produces the same histories (the store guarantees the
        same order and the same cut in both methods), and ``compute_state``
        remains the only source of state (I4). Objectives without attempts are
        computed with an empty history (C1).

        Args:
            as_of: cut date, already resolved.
            listed: the global read when the caller already did it; ``None``
                does it here. It avoids a re-read in ``get_summary``.
        """
        if listed is None:
            listed = self._attempts.list_all(self._profile_id, until=as_of)
        by_objective: dict[str, list[Attempt]] = {}
        for attempt in listed:
            by_objective.setdefault(attempt.objective_id, []).append(attempt)
        return [
            compute_state(
                objective.objective_id,
                by_objective.get(objective.objective_id, ()),
                as_of,
            )
            for objective in self._profiles.list_objectives(self._profile_id)
        ]

    # ------------------------------------------------------------------- write

    def record_attempt(
        self,
        objective_id: str,
        correct: bool,
        at: datetime,
        kind: AttemptKind = AttemptKind.QUIZ,
        confidence: float | None = None,
        note: str | None = None,
        attempt_id: str | None = None,
    ) -> Attempt:
        """Records an attempt with an **injected date**.

        ``at`` is mandatory and supplied by the caller: the engine never reads
        the clock to fabricate it (SPEC I2). That is what lets a bot write the
        series "wrong, wrong, wrong, right, wrong" on arbitrary dates and verify
        the evolution without waiting five days.

        The history is append-only: this method is the **only** way data comes
        in, and there is no counterpart to modify or delete (SPEC I1).

        Args:
            objective_id: objective assessed. It must exist in the profile.
            correct: hit or miss.
            at: when it happened, aware. It may precede already recorded
                attempts: inserting out of order is legal (SPEC C4).
            kind: nature of the evidence.
            confidence: self assessment 0.0-1.0. It does not affect the level in
                v1.
            note: free text.
            attempt_id: explicit id; when ``None`` a unique one is generated.

        Returns:
            The :class:`Attempt` exactly as persisted, with its id. Returning
            the written object (and not ``None``) is what makes a failed record
            impossible to confuse with a successful one (SPEC I8).

        Raises:
            UnknownObjectiveError: the objective does not exist. It is **not
                auto-created** (SPEC C8).
            DuplicateAttemptError: that ``attempt_id`` already exists (SPEC C9).
            InvalidAttemptError: naive ``at``, or ``confidence`` out of range.
            StorageError: the write could not be completed.
        """
        # C8: the objective must exist. get_objective raises when it does not;
        # it is never auto-created.
        self._profiles.get_objective(self._profile_id, objective_id)
        if attempt_id is None:
            attempt_id = uuid4().hex
        elif self._attempts.exists(attempt_id):
            # C9: the store rejects it too, but it is checked here so that the
            # contract does not depend on the backend.
            raise DuplicateAttemptError(attempt_id)
        attempt = Attempt(
            attempt_id=attempt_id,
            objective_id=objective_id,
            at=at,
            correct=correct,
            kind=kind,
            confidence=confidence,
            note=note,
            recorded_at=self._clock.now(),
        )
        # I8: if append fails, the exception propagates. None is never returned.
        return self._attempts.append(self._profile_id, attempt)

    def record_series(
        self,
        objective_id: str,
        results: Sequence[bool],
        start: datetime,
        step: timedelta = timedelta(days=1),
        kind: AttemptKind = AttemptKind.QUIZ,
    ) -> list[Attempt]:
        """Records a deliberate series of results on spaced dates.

        A shortcut meant for the verification bot and for the tests: the series
        ``[False, False, False, True, False]`` from a given date reproduces
        exactly the example walked through in SPEC section 3.

        Args:
            objective_id: objective assessed.
            results: hits/misses in chronological order.
            start: date of the first attempt, aware.
            step: separation between consecutive attempts.
            kind: nature of the evidence for all of them.

        Returns:
            The attempts created, in order.
        """
        return [
            self.record_attempt(
                objective_id, correct=result, at=start + step * index, kind=kind
            )
            for index, result in enumerate(results)
        ]

    def session(
        self,
        session_id: str | None = None,
        started_at: datetime | None = None,
    ) -> SessionRecorder:
        """Opens a recording session (SPEC section 9.6).

        Use it as a context manager. On close it produces a
        :class:`~core.models.SessionReport`; if nothing was recorded, the status
        is ``EMPTY`` and there is visible evidence that the session went blank
        (defense against failure 4).

        Args:
            session_id: identifier; ``None`` generates one.
            started_at: opening instant, injected (SPEC I2). ``None`` uses the
                tracker's clock.
        """
        return SessionRecorder(self, session_id=session_id, started_at=started_at)

    # ------------------------------------------------------------------- query

    def get_level(
        self, objective_id: str, as_of: datetime | None = None
    ) -> Level:
        """The level of an objective at a date. SPEC section 2.

        Args:
            objective_id: objective queried.
            as_of: cut date; ``None`` uses ``clock.now()``.

        Raises:
            UnknownObjectiveError: if the objective does not exist in the
                profile. An objective that exists but has no attempts is **not**
                an error: it returns ``UNASSESSED`` (SPEC C1).
        """
        return self.get_state(objective_id, as_of).level

    def get_state(
        self, objective_id: str, as_of: datetime | None = None
    ) -> ObjectiveState:
        """The complete state of an objective at a date. SPEC section 1.5."""
        self._profiles.get_objective(self._profile_id, objective_id)
        return self._state(objective_id, self._resolve(as_of))

    def get_state_at(
        self, objective_id: str, as_of: datetime
    ) -> ObjectiveState:
        """The state **as it was** at a past date. SPEC section 5.1.

        Identical to :meth:`get_state` except that ``as_of`` is mandatory: it
        exists as a method of its own so that the historical query is explicit
        in the code that uses it, rather than a parameter someone forgets.

        Guarantees (SPEC section 5.1):

        * It completely ignores attempts with ``at > as_of``.
        * The result does not change by recording later attempts: the past is
          not rewritten.
        * It is insensitive to the order in which the attempts were written.

        It is possible only because the history is append-only and the level is
        recomputed on every query; a system with a stored level cannot answer
        this question.
        """
        return self.get_state(objective_id, as_of)

    def get_all_states(
        self, as_of: datetime | None = None
    ) -> list[ObjectiveState]:
        """The state of every objective of the profile, by ``objective_id``."""
        return self._all_states(self._resolve(as_of))

    def get_due(
        self, as_of: datetime | None = None, limit: int | None = None
    ) -> list[ObjectiveState]:
        """What is due for review at a date. SPEC section 5.2.

        Sorted by urgency: the most overdue first; on a tie, the lowest
        ``score``; on a tie, ascending ``objective_id``. The third criterion
        exists so that the order is fully deterministic.

        Objectives **without attempts do not appear here**: use
        :meth:`get_unstarted`. Mixing "I have never seen it" with "it is due for
        review" hides the uncovered material.
        """
        moment = self._resolve(as_of)
        due = [s for s in self.get_all_states(moment) if s.is_due]
        # is_due guarantees a non-null next_review_at. More overdue = larger
        # (as_of - next_review_at); it is sorted by its negative ascending.
        due.sort(
            key=lambda s: (
                -(moment - s.next_review_at),  # type: ignore[operator]
                s.score,
                s.objective_id,
            )
        )
        return due if limit is None else due[:limit]

    def get_unstarted(
        self, as_of: datetime | None = None
    ) -> list[ObjectiveState]:
        """Objectives without a single attempt up to ``as_of``.

        It makes uncovered material visible, which is otherwise invisible: an
        objective without attempts produces no signal on its own.
        """
        return [s for s in self.get_all_states(as_of) if s.total_attempts == 0]

    def get_stale(
        self, as_of: datetime | None = None, days: int | None = None
    ) -> list[ObjectiveState]:
        """Objectives with no activity in the last ``days`` days.

        Second layer of defense against failure 4: if nobody records anything,
        the state does not stay frozen in silence, the objectives start showing
        up in this list instead. A system that is not recording gives itself
        away.

        Args:
            as_of: cut date; ``None`` uses ``clock.now()``.
            days: inactivity threshold; ``None`` uses ``DEFAULT_STALE_DAYS``.
        """
        threshold = DEFAULT_STALE_DAYS if days is None else days
        # Only objectives with history: the ones that never had attempts belong
        # in get_unstarted (SPEC section 8, failure 4, layer 2).
        return [
            s
            for s in self.get_all_states(as_of)
            if s.days_since_last is not None and s.days_since_last > threshold
        ]

    def get_timeline(
        self,
        objective_id: str,
        start: datetime,
        end: datetime,
        step: timedelta = timedelta(days=1),
    ) -> list[ObjectiveState]:
        """Time series of states over a grid of dates. SPEC section 5.3.

        It is :meth:`get_state_at` in a loop. It exists so that the UI can plot
        the evolution without reimplementing the time cut, which is where it is
        easy to get things wrong.

        Raises:
            InvalidRangeError: if ``start > end`` or ``step <= 0``. The message
                text stays in Spanish: it reaches the user through the CLI.
        """
        if start > end:
            raise InvalidRangeError(f"start > end: {start} > {end}")
        if step <= timedelta(0):
            raise InvalidRangeError(f"step debe ser positivo: {step}")
        self._profiles.get_objective(self._profile_id, objective_id)
        states: list[ObjectiveState] = []
        moment = start
        while moment <= end:
            states.append(self._state(objective_id, moment))
            moment += step
        return states

    def compare_states(
        self, objective_id: str, earlier: datetime, later: datetime
    ) -> StateComparison:
        """Compares the objective at two dates. SPEC section 5.1.

        The direct answer to *"was I better two weeks ago than this week?"*:
        call it with ``earlier = today - 14d`` and ``later = today`` and look at
        ``improved`` / ``regressed``.

        Raises:
            InvalidRangeError: if ``earlier > later``.
        """
        if earlier > later:
            raise InvalidRangeError(f"earlier > later: {earlier} > {later}")
        before = self.get_state(objective_id, earlier)
        after = self.get_state(objective_id, later)
        score_delta = after.score - before.score
        return StateComparison(
            objective_id=objective_id,
            earlier=before,
            later=after,
            level_delta=int(after.level) - int(before.level),
            score_delta=score_delta,
            improved=score_delta > 0,
            regressed=score_delta < 0,
        )

    def get_summary(self, as_of: datetime | None = None) -> ProfileSummary:
        """Profile aggregate at a date. SPEC section 9.4."""
        moment = self._resolve(as_of)
        # A single read of the store: it feeds both the states and the total.
        listed = self._attempts.list_all(self._profile_id, until=moment)
        states = self._all_states(moment, listed)
        by_level = {level: 0 for level in Level}
        for state in states:
            by_level[state.level] += 1
        total = len(states)
        assessed = total - by_level[Level.UNASSESSED]
        return ProfileSummary(
            profile_id=self._profile_id,
            as_of=moment,
            total_objectives=total,
            by_level=by_level,
            assessed_objectives=assessed,
            unstarted_objectives=sum(1 for s in states if s.total_attempts == 0),
            due_objectives=sum(1 for s in states if s.is_due),
            total_attempts=len(listed),
            mean_score=(sum(s.score for s in states) / total) if total else 0.0,
            coverage=(assessed / total) if total else 0.0,
        )

    def get_profile(self) -> Profile:
        """The profile this tracker operates on."""
        return self._profiles.get_profile(self._profile_id)

    # ------------------------------------------------------------ verification

    def check_consistency(
        self, as_of: datetime | None = None
    ) -> ConsistencyReport:
        """Verifies that the store and the recomputation agree. SPEC section 8,
        failure 2.

        It compares **counts and sums**, never set membership (SPEC I9):
        comparing sets lets duplicates and cardinality mismatches through, which
        is precisely how the previous verifier ended up printing
        "OK - consistent" over a corrupt state.

        Minimum checks required by the contract, per objective and for the whole
        profile:

        * number of attempts in the store == number of recomputed attempts;
        * sum of hits in the store == recomputed sum;
        * no duplicated ``attempt_id`` (``count`` is compared against the number
          of unique ids: if they differ, there are duplicates);
        * every attempt points at an ``objective_id`` that exists in the
          profile.

        The ``detail`` texts stay in Spanish: the CLI prints them to the user.

        Returns:
            A :class:`ConsistencyReport` with the numbers from both sides of
            every comparison. ``ok`` is ``True`` only if every check passed
            **and** at least one objective was checked: having found no errors
            because nothing was looked at is not being fine.
        """
        moment = self._resolve(as_of)
        profile = self._profiles.get_profile(self._profile_id)
        objectives = self._profiles.list_objectives(self._profile_id)
        # "Store" side: the global read of the profile, grouped by objective.
        # "Recomputed" side: compute_state over the per-objective read.
        # They are two different read paths; their NUMBERS are compared (I9).
        # _all_states is deliberately NOT reused here: if both sides came from
        # the same list_all, a list_all that duplicates an attempt would agree
        # with itself and attempt_count would not detect it. The N per-objective
        # reads are the price of the two sides being independent (SPEC
        # section 8, failure 2).
        listed = self._attempts.list_all(self._profile_id, until=moment)
        count_by_objective: dict[str, int] = {}
        correct_by_objective: dict[str, int] = {}
        for attempt in listed:
            count_by_objective[attempt.objective_id] = (
                count_by_objective.get(attempt.objective_id, 0) + 1
            )
            correct_by_objective[attempt.objective_id] = (
                correct_by_objective.get(attempt.objective_id, 0)
                + int(attempt.correct)
            )

        checks: list[ConsistencyCheck] = []

        def add(name: str, expected: float, actual: float, detail: str) -> None:
            checks.append(
                ConsistencyCheck(
                    name=name,
                    expected=expected,
                    actual=actual,
                    passed=expected == actual,
                    detail=detail,
                )
            )

        recalculated_total = 0
        recalculated_correct = 0
        for objective in objectives:
            oid = objective.objective_id
            state = self._state(oid, moment)
            recalculated_total += state.total_attempts
            recalculated_correct += state.correct_attempts
            add(
                "attempt_count",
                state.total_attempts,
                count_by_objective.get(oid, 0),
                f"{oid}: intentos recalculados vs listados en el store",
            )
            add(
                "correct_sum",
                state.correct_attempts,
                correct_by_objective.get(oid, 0),
                f"{oid}: aciertos recalculados vs sumados en el store",
            )

        # Whole profile.
        add(
            "profile_attempt_count",
            recalculated_total,
            len(listed),
            "suma de intentos recalculados vs list_all del store",
        )
        add(
            "profile_correct_sum",
            recalculated_correct,
            sum(1 for a in listed if a.correct),
            "suma de aciertos recalculados vs list_all del store",
        )
        # The store's count() against its own full read (with no cut: count
        # does not accept as_of). It detects a counter that lies.
        everything = self._attempts.list_all(self._profile_id)
        add(
            "store_count",
            len(everything),
            self._attempts.count(self._profile_id),
            "len(list_all) vs count() del store",
        )
        add(
            "unique_attempt_ids",
            len(everything),
            len({a.attempt_id for a in everything}),
            "intentos vs attempt_id únicos: si difieren, hay duplicados",
        )
        add(
            "orphan_attempts",
            0,
            sum(1 for a in everything if a.objective_id not in profile.objectives),
            "intentos cuyo objective_id no existe en el perfil",
        )

        checked = len(objectives)
        return ConsistencyReport(
            ok=checked >= 1 and all(c.passed for c in checks),
            checks=tuple(checks),
            objectives_checked=checked,
            as_of=moment,
        )

    def rebuild(self, as_of: datetime | None = None) -> int:
        """Recomputes every derived projection from the history. SPEC I6.

        Since no aggregate is persisted, this is a safe and repeatable
        operation: any corrupt cache or index is fixed by running it. It is the
        reason failure 3 (corrupted, irreversible counters) has no equivalent
        here.

        Returns:
            How many objectives were recomputed.
        """
        # There is no cache or index to delete: state is always derived from the
        # history (I4). Recomputing everything is the complete operation, and
        # returning the count leaves evidence that the whole profile was walked.
        return len(self.get_all_states(as_of))
