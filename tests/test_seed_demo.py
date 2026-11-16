"""The demo seed (issues #74, #75) has to tell one believable story to both
audiences: a student's Progreso and the teacher's table. The date logic is
checked against the real engine with no database; the end-to-end test runs the
script twice against a throwaway Postgres schema and reads it back through the
API with the dev identity headers (authentication off).
"""

from __future__ import annotations

import os
import uuid
from collections import Counter
from datetime import datetime, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.leveling import compute_state
from core.models import Attempt, Level
from migrations.runner import apply_migrations
from scripts import seed_demo
from scripts.seed_demo import (
    HISTORIA,
    STUDENTS,
    TOPICS,
    Practice,
    attempt_times,
    personal_practice,
)
from web.app import create_app
from web.config import Settings

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = os.environ.get(
    "LEARNING_TRACKER_TEST_DATABASE_URL",
    f"postgresql://learning_tracker:learning_tracker@localhost:{POSTGRES_PORT}/learning_tracker",
)
SCHEMA = f"learning_test_seed_{uuid.uuid4().hex[:8]}"


def _states(practice_by_objective):
    out = {}
    for objective_id, practice in practice_by_objective.items():
        attempts = (
            [
                Attempt(attempt_id=f"{objective_id}-{i}", objective_id=objective_id, at=at, correct=ok)
                for i, (ok, at) in enumerate(attempt_times(practice, NOW))
            ]
            if practice
            else []
        )
        out[objective_id] = compute_state(objective_id, attempts, NOW)
    return out


def _student(user_id):
    return next(s for s in STUDENTS if s.user_id == user_id)


def test_attempt_times_are_ordered_and_end_at_last_days_ago():
    times = attempt_times(Practice("wcc", 2, 3), NOW)
    assert [ok for ok, _ in times] == [False, True, True]
    stamps = [at for _, at in times]
    assert stamps == sorted(stamps)
    assert (NOW - stamps[-1]).days == 2
    assert (stamps[-1] - stamps[0]).days == 6


def test_the_strong_student_has_a_realistic_spread():
    states = _states(personal_practice(_student("demo_ana"), HISTORIA))
    levels = Counter(state.level for state in states.values())
    assert levels[Level.MASTERED] + levels[Level.COMPETENT] >= 6
    assert levels[Level.LEARNING] >= 2
    assert 1 <= levels[Level.WEAK] <= 2
    assert levels[Level.UNASSESSED] == 1


def test_every_topic_has_units_and_upcoming_reviews():
    for topic in TOPICS:
        states = _states(personal_practice(_student("demo_ana"), topic))
        assert len({o.unit for o in topic.objectives}) >= 2
        assert any(s.next_review_at and not s.is_due for s in states.values())
        assert {o.objective_id for o in topic.objectives} == set(states)


def test_ids_are_unique_across_topics():
    ids = [o.objective_id for topic in TOPICS for o in topic.objectives]
    assert len(ids) == len(set(ids))


def test_the_lapsed_student_has_things_due_and_the_beginner_has_unstarted_ones():
    diego = _states(personal_practice(_student("demo_diego"), HISTORIA))
    ana = _states(personal_practice(_student("demo_ana"), HISTORIA))
    assert sum(s.is_due for s in diego.values()) > sum(s.is_due for s in ana.values())
    carla = _states(personal_practice(_student("demo_carla"), HISTORIA))
    assert sum(s.level is Level.UNASSESSED for s in carla.values()) > 6


def _postgres_reachable() -> bool:
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


@pytest.fixture
def seeded(monkeypatch):
    if not _postgres_reachable():
        pytest.skip("postgres no disponible: levanta `docker compose up -d postgres`")
    apply_migrations(POSTGRES_DSN, schema=SCHEMA)
    monkeypatch.setenv("LEARNING_TRACKER_DATABASE_URL", POSTGRES_DSN)
    monkeypatch.setenv("LEARNING_TRACKER_SCHEMA", SCHEMA)
    yield
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.commit()


def _count_attempts() -> int:
    with psycopg.connect(POSTGRES_DSN) as conn:
        return conn.execute(f"SELECT count(*) FROM {SCHEMA}.attempts").fetchone()[0]


def _as(user_id, role="member"):
    return {"X-Dev-User": user_id, "X-Dev-Org": seed_demo.ORG_ID, "X-Dev-Role": role}


@pytest.mark.spec
def test_one_command_seeds_a_class_the_teacher_and_each_student_see_consistently(seeded):
    assert seed_demo.main() == 0
    first = _count_attempts()
    assert first > 0
    assert seed_demo.main() == 0  # retry-safe: nothing duplicated, nothing crashes
    assert _count_attempts() == first

    settings = Settings(
        database_url=POSTGRES_DSN, schema=SCHEMA, host="127.0.0.1", port=8000, auth_disabled=True
    )
    with TestClient(create_app(settings)) as client:
        teacher = client.get("/org/progress", headers=_as("demo_teacher", "org:admin")).json()
        rows = {m["user_id"]: m["topics"] for m in teacher["members"]}
        assert set(rows) == {s.user_id for s in STUDENTS}
        assert {len(rows[s.user_id]) for s in STUDENTS} == {1, 2}
        assert len({t["level"] for topics in rows.values() for t in topics}) > 1
        # The same story from the student's side: their own topics, only theirs.
        for student in STUDENTS:
            topics = client.get("/topics", headers=_as(student.user_id)).json()
            assert {t["topic_id"] for t in topics} == {t.topic_id for t in student.topics}
            assert len(topics) == len(rows[student.user_id])
        assert client.get("/org/progress", headers=_as("demo_ana")).status_code == 403
