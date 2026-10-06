"""The school demo seed (issue #74) has to tell a believable story: mostly
well learned, a few on track, a couple needing reinforcement, one never
practised, and reviews still ahead. Checked against the real engine, with no
database: ``attempt_times`` is the only date logic the script owns.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from core.leveling import compute_state
from core.models import Attempt, Level
from scripts.seed_school_data import HISTORIA, TOPICS, Practice, attempt_times

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _states(topic):
    out = {}
    for objective in topic.objectives:
        attempts = [
            Attempt(attempt_id=f"{objective.objective_id}-{i}", objective_id=objective.objective_id, at=at, correct=ok)
            for i, (ok, at) in enumerate(attempt_times(objective.practice, NOW))
        ] if objective.practice else []
        out[objective.objective_id] = compute_state(objective.objective_id, attempts, NOW)
    return out


def test_attempt_times_are_ordered_and_end_at_last_days_ago():
    times = attempt_times(Practice("wcc", 2, 3), NOW)
    assert [ok for ok, _ in times] == [False, True, True]
    stamps = [at for _, at in times]
    assert stamps == sorted(stamps)
    assert (NOW - stamps[-1]).days == 2
    assert (stamps[-1] - stamps[0]).days == 6


def test_history_topic_has_a_realistic_spread():
    levels = Counter(state.level for state in _states(HISTORIA).values())
    mastered_or_competent = levels[Level.MASTERED] + levels[Level.COMPETENT]
    assert mastered_or_competent >= 6
    assert levels[Level.LEARNING] >= 2
    assert 1 <= levels[Level.WEAK] <= 2
    assert levels[Level.UNASSESSED] == 1


def test_every_topic_has_units_and_upcoming_reviews():
    for topic in TOPICS:
        states = _states(topic)
        assert len({o.unit for o in topic.objectives}) >= 2
        assert any(s.next_review_at and not s.is_due for s in states.values())
        assert {o.objective_id for o in topic.objectives} == set(states)


def test_ids_are_unique_across_topics():
    ids = [o.objective_id for topic in TOPICS for o in topic.objectives]
    assert len(ids) == len(set(ids))
