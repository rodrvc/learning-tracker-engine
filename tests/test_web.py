"""Tests of ``web/`` against ACU-246: health, topics, config and error mapping.

The tests that need no database at all live in ``tests/test_web_wiring.py``:
this module's autouse fixture skips the whole file when Postgres is
unreachable, which was skipping them for a reason that had nothing to do
with them.

Runs against a throwaway Postgres schema, the same convention as
``tests/test_store.py``: reachability is decided once, and every Postgres test
skips with an explicit reason when it is not reachable. In CI, Postgres is
always reachable, so nothing here is expected to actually skip there.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.constants import WINDOW
from migrations.runner import apply_migrations
from web.app import create_app
from web.config import Settings

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = os.environ.get(
    "LEARNING_TRACKER_TEST_DATABASE_URL",
    f"postgresql://learning_tracker:learning_tracker@localhost:{POSTGRES_PORT}"
    "/learning_tracker",
)
POSTGRES_SCHEMA = f"learning_test_web_{uuid.uuid4().hex[:8]}"


def _postgres_reachable() -> bool:
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


POSTGRES_AVAILABLE = _postgres_reachable()
_SKIP_REASON = (
    "postgres no disponible: exporta LEARNING_TRACKER_TEST_DATABASE_URL o "
    "levanta `docker compose up -d postgres`"
)


@pytest.fixture(scope="module", autouse=True)
def _postgres_test_schema():
    if not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)
    apply_migrations(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    yield
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {POSTGRES_SCHEMA} CASCADE")
        conn.commit()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url=POSTGRES_DSN, schema=POSTGRES_SCHEMA, host="127.0.0.1", port=8000)


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"TRUNCATE {POSTGRES_SCHEMA}.attempts, {POSTGRES_SCHEMA}.objectives, "
            f"{POSTGRES_SCHEMA}.profiles CASCADE"
        )
        conn.commit()


@pytest.mark.spec
def test_health_reports_real_storage_state(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.spec
def test_create_and_list_topics(client: TestClient) -> None:
    created = client.post("/topics", json={"topic_id": "ai-103", "name": "AI-103"})
    assert created.status_code == 201
    assert created.json() == {"topic_id": "ai-103", "name": "AI-103", "objective_count": 0}

    listing = client.get("/topics")
    assert listing.status_code == 200
    assert listing.json() == [{"topic_id": "ai-103", "name": "AI-103", "objective_count": 0}]


@pytest.mark.edge
def test_create_topic_twice_conflicts(client: TestClient) -> None:
    client.post("/topics", json={"topic_id": "az-900", "name": "AZ-900"})
    second = client.post("/topics", json={"topic_id": "az-900", "name": "AZ-900 v2"})
    assert second.status_code == 409


@pytest.mark.spec
def test_get_topic_returns_its_objectives(client: TestClient) -> None:
    client.post("/topics", json={"topic_id": "ai-103", "name": "AI-103"})
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"""INSERT INTO {POSTGRES_SCHEMA}.objectives
                (profile_id, objective_id, title, domain, weight, tags)
                VALUES ('ai-103', 'D1.1-foo', 'Foo', 'D1', 1.0, ARRAY[]::text[])"""
        )
        conn.commit()

    response = client.get("/topics/ai-103")
    assert response.status_code == 200
    body = response.json()
    assert body["topic_id"] == "ai-103"
    assert body["objectives"] == [
        {
            "objective_id": "D1.1-foo",
            "title": "Foo",
            "domain": "D1",
            "weight": 1.0,
            "tags": [],
        }
    ]


@pytest.mark.edge
def test_get_unknown_topic_fails_instead_of_empty_success(client: TestClient) -> None:
    response = client.get("/topics/does-not-exist")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def _seed_objective(topic_id: str, objective_id: str) -> None:
    """Creates a topic (if absent) with one objective, no attempts yet."""
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"INSERT INTO {POSTGRES_SCHEMA}.profiles (profile_id, name) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (topic_id, topic_id),
        )
        conn.execute(
            f"""INSERT INTO {POSTGRES_SCHEMA}.objectives
                (profile_id, objective_id, title, domain, weight, tags)
                VALUES (%s, %s, 'Foo', NULL, 1.0, ARRAY[]::text[])""",
            (topic_id, objective_id),
        )
        conn.commit()


def _seed_attempt(
    topic_id: str, objective_id: str, attempt_id: str, at: str, correct: bool
) -> None:
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"""INSERT INTO {POSTGRES_SCHEMA}.attempts
                (attempt_id, profile_id, objective_id, at, correct, kind)
                VALUES (%s, %s, %s, %s, %s, 'quiz')""",
            (attempt_id, topic_id, objective_id, at, correct),
        )
        conn.commit()


@pytest.mark.spec
def test_objective_states_shape(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", False)

    response = client.get("/topics/ai-103/objectives/states?as_of=2020-06-01T00:00:00Z")
    assert response.status_code == 200
    states = response.json()
    assert len(states) == 1
    state = states[0]
    assert state["objective_id"] == "D1.1-foo"
    assert state["total_attempts"] == 1
    assert state["correct_attempts"] == 0
    assert state["level"] == "UNASSESSED"
    assert state["recent_window"] == [False]
    assert "next_review_at" in state
    assert "is_due" in state
    assert "streak" not in state
    assert "run" not in state


@pytest.mark.spec
def test_cut_date_changes_the_answer(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", False)
    _seed_attempt("ai-103", "D1.1-foo", "a2", "2020-01-10T00:00:00Z", True)

    before = client.get(
        "/topics/ai-103/objectives/states?as_of=2020-01-05T00:00:00Z"
    ).json()[0]
    after = client.get(
        "/topics/ai-103/objectives/states?as_of=2020-01-15T00:00:00Z"
    ).json()[0]

    assert before["total_attempts"] == 1
    assert after["total_attempts"] == 2
    assert before != after


@pytest.mark.spec
def test_due_sorted_most_overdue_first(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_objective("ai-103", "D1.2-bar")
    # Both miss their last attempt: next review is one day after `at`. The
    # older attempt is more overdue at the same `as_of`.
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", False)
    _seed_attempt("ai-103", "D1.2-bar", "a2", "2020-01-05T00:00:00Z", False)

    response = client.get("/topics/ai-103/objectives/due?as_of=2020-06-01T00:00:00Z")
    assert response.status_code == 200
    due = response.json()
    assert [item["objective_id"] for item in due] == ["D1.1-foo", "D1.2-bar"]
    assert all(item["is_due"] for item in due)


@pytest.mark.spec
def test_cut_date_changes_due(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", False)
    # A miss schedules the next review one day later (SPEC 4.2): 2020-01-02.

    before = client.get(
        "/topics/ai-103/objectives/due?as_of=2020-01-01T12:00:00Z"
    ).json()
    after = client.get(
        "/topics/ai-103/objectives/due?as_of=2020-01-03T00:00:00Z"
    ).json()

    assert before == []
    assert [item["objective_id"] for item in after] == ["D1.1-foo"]


@pytest.mark.spec
def test_due_limit_caps_and_keeps_the_most_overdue(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_objective("ai-103", "D1.2-bar")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", False)
    _seed_attempt("ai-103", "D1.2-bar", "a2", "2020-01-05T00:00:00Z", False)

    response = client.get(
        "/topics/ai-103/objectives/due?as_of=2020-06-01T00:00:00Z&limit=1"
    )
    assert response.status_code == 200
    due = response.json()
    assert [item["objective_id"] for item in due] == ["D1.1-foo"]


@pytest.mark.spec
def test_summary_shape(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", True)

    response = client.get("/topics/ai-103/summary?as_of=2020-06-01T00:00:00Z")
    assert response.status_code == 200
    summary = response.json()
    assert summary["topic_id"] == "ai-103"
    assert summary["total_objectives"] == 1
    assert summary["total_attempts"] == 1
    assert set(summary["by_level"]) == {
        "UNASSESSED",
        "WEAK",
        "LEARNING",
        "COMPETENT",
        "MASTERED",
    }
    assert "mean_score" in summary
    assert "coverage" in summary


@pytest.mark.spec
def test_cut_date_changes_summary(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", True)
    _seed_attempt("ai-103", "D1.1-foo", "a2", "2020-01-02T00:00:00Z", True)

    before = client.get("/topics/ai-103/summary?as_of=2020-01-01T12:00:00Z").json()
    after = client.get("/topics/ai-103/summary?as_of=2020-01-03T00:00:00Z").json()

    assert before["total_attempts"] == 1
    assert after["total_attempts"] == 2
    assert before != after


@pytest.mark.spec
def test_recent_window_capped_at_window_size(client: TestClient) -> None:
    """More than WINDOW attempts: the window stays capped, not truncated to
    an arbitrary smaller size. Asserted with more attempts than the cap, so a
    regression that shrinks the window would actually be caught here rather
    than silently matching a coincidentally small fixture."""
    _seed_objective("ai-103", "D1.1-foo")
    for index in range(WINDOW + 2):
        _seed_attempt(
            "ai-103", "D1.1-foo", f"a{index}", f"2020-01-{index + 1:02d}T00:00:00Z", True
        )

    response = client.get("/topics/ai-103/objectives/states?as_of=2020-06-01T00:00:00Z")
    state = response.json()[0]
    assert state["total_attempts"] == WINDOW + 2
    assert len(state["recent_window"]) == WINDOW


@pytest.mark.spec
def test_unstarted_lists_objectives_without_attempts(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_objective("ai-103", "D1.2-bar")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", True)

    response = client.get("/topics/ai-103/objectives/unstarted?as_of=2020-06-01T00:00:00Z")
    assert response.status_code == 200
    unstarted = response.json()
    assert [item["objective_id"] for item in unstarted] == ["D1.2-bar"]
    assert unstarted[0]["total_attempts"] == 0


@pytest.mark.spec
def test_stale_lists_objectives_without_recent_activity(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", True)

    fresh = client.get(
        "/topics/ai-103/objectives/stale?as_of=2020-01-02T00:00:00Z&days=14"
    ).json()
    stale = client.get(
        "/topics/ai-103/objectives/stale?as_of=2020-06-01T00:00:00Z&days=14"
    ).json()

    assert fresh == []
    assert [item["objective_id"] for item in stale] == ["D1.1-foo"]


@pytest.mark.spec
def test_compare_states_answers_was_i_better(client: TestClient) -> None:
    # SPEC section 3's canonical walkthrough: wrong, wrong, wrong, right,
    # wrong, right, right, right, one attempt per day starting 2020-01-01.
    # At day 3 the score is still 0.0 (WEAK); by day 7 it has crossed 0.60
    # (LEARNING) — an unambiguous, spec-verified improvement.
    _seed_objective("ai-103", "D1.1-foo")
    results = [False, False, False, True, False, True, True, True]
    for index, correct in enumerate(results):
        _seed_attempt(
            "ai-103",
            "D1.1-foo",
            f"a{index}",
            f"2020-01-{index + 1:02d}T00:00:00Z",
            correct,
        )

    response = client.get(
        "/topics/ai-103/objectives/D1.1-foo/compare"
        "?earlier=2020-01-03T00:00:00Z&later=2020-01-07T00:00:00Z"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["objective_id"] == "D1.1-foo"
    assert body["earlier"]["as_of"] == "2020-01-03T00:00:00Z"
    assert body["later"]["as_of"] == "2020-01-07T00:00:00Z"
    assert body["earlier"]["score"] == 0.0
    assert body["later"]["score"] == pytest.approx(0.607, abs=1e-3)
    assert body["improved"] is True
    assert body["regressed"] is False
    assert body["score_delta"] > 0


@pytest.mark.edge
def test_progress_endpoints_fail_on_unknown_topic(client: TestClient) -> None:
    for path in (
        "/topics/nope/objectives/states",
        "/topics/nope/objectives/due",
        "/topics/nope/objectives/unstarted",
        "/topics/nope/objectives/stale",
        "/topics/nope/summary",
        "/topics/nope/objectives/whatever/compare"
        "?earlier=2020-01-01T00:00:00Z&later=2020-01-02T00:00:00Z",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "nope" in response.json()["detail"]


@pytest.mark.edge
def test_compare_fails_on_unknown_objective(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    response = client.get(
        "/topics/ai-103/objectives/does-not-exist/compare"
        "?earlier=2020-01-01T00:00:00Z&later=2020-01-02T00:00:00Z"
    )
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


@pytest.mark.edge
def test_compare_earlier_after_later_is_400(client: TestClient) -> None:
    _seed_objective("ai-103", "D1.1-foo")
    response = client.get(
        "/topics/ai-103/objectives/D1.1-foo/compare"
        "?earlier=2020-01-10T00:00:00Z&later=2020-01-01T00:00:00Z"
    )
    assert response.status_code == 400


