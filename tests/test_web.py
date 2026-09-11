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

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.constants import DEFAULT_STALE_DAYS, WINDOW
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
        # Materials and questions are truncated too. They have no foreign key
        # to profiles, so truncating profiles does not cascade to them, and
        # they used to survive from one test into the next. Anything asserting
        # on a whole listing then saw rows another test had left behind.
        conn.execute(
            f"TRUNCATE {POSTGRES_SCHEMA}.attempts, {POSTGRES_SCHEMA}.questions, "
            f"{POSTGRES_SCHEMA}.materials, {POSTGRES_SCHEMA}.objectives, "
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


def _iso(at: datetime) -> str:
    """Formats an aware ``datetime`` as the ``...Z`` shape the query params use."""
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
def test_summary_reports_real_computed_values(client: TestClient) -> None:
    """Pins actual numbers, not just key presence, for every aggregate field.

    Three objectives, each contributing a known, distinct state:

    * ``D1.1-foo`` gets two same-day hits (score 1.0, COMPETENT — n=2 meets
      MIN_ATTEMPTS, the window's two weights are both correct so raw=1.0, and
      querying at the moment of the last attempt makes gap=0 so
      retention=1.0; it does not reach MASTERED because both attempts land on
      a single calendar day). Not due: its next review (3 days out, S=2) is
      well past ``as_of``.
    * ``D1.2-bar`` has no attempts at all (score 0.0, UNASSESSED, unstarted).
    * ``D1.3-baz`` has exactly one miss, a week before ``as_of`` (score 0.0,
      UNASSESSED per SPEC C2 — a single attempt is never enough — but
      *started*, not unstarted). Its next review was one day after that miss,
      long past by ``as_of``, so it is the one due objective.

    With those three known states, every aggregate below is forced to a
    specific, mostly non-zero number — ``due_objectives`` in particular,
    which a fixture with nothing due could not tell apart from a router that
    hardcodes it to zero. A router that hardcodes any of ``mean_score``,
    ``coverage``, ``assessed_objectives``, ``unstarted_objectives`` or
    ``due_objectives``, or restates them without going through
    ``get_summary``, is caught here — where the old ``test_summary_shape``
    only checked that the keys existed.
    """
    _seed_objective("ai-103", "D1.1-foo")
    _seed_objective("ai-103", "D1.2-bar")
    _seed_objective("ai-103", "D1.3-baz")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-01T00:00:00Z", True)
    _seed_attempt("ai-103", "D1.1-foo", "a2", "2020-01-01T01:00:00Z", True)
    _seed_attempt("ai-103", "D1.3-baz", "a3", "2019-12-25T00:00:00Z", False)

    response = client.get("/topics/ai-103/summary?as_of=2020-01-01T01:00:00Z")
    assert response.status_code == 200
    summary = response.json()
    assert summary["topic_id"] == "ai-103"
    assert summary["total_objectives"] == 3
    assert summary["total_attempts"] == 3
    assert summary["assessed_objectives"] == 1
    assert summary["unstarted_objectives"] == 1
    assert summary["due_objectives"] == 1
    assert summary["coverage"] == pytest.approx(1 / 3)
    assert summary["mean_score"] == pytest.approx(1 / 3)
    assert summary["by_level"] == {
        "UNASSESSED": 2,
        "WEAK": 0,
        "LEARNING": 0,
        "COMPETENT": 1,
        "MASTERED": 0,
    }


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
def test_recent_window_capped_and_ordered_oldest_to_newest(client: TestClient) -> None:
    """More than WINDOW attempts: the window stays capped, not truncated to
    an arbitrary smaller size, and keeps the oldest-to-newest order the spec
    requires (the weights are positional, so a reversed window would plot a
    client's progress backwards). Asserted with more attempts than the cap
    and an alternating hit/miss pattern, so a regression that shrinks the
    window or reverses it is actually caught here rather than silently
    matching a uniform or coincidentally small fixture."""
    _seed_objective("ai-103", "D1.1-foo")
    results = [index % 2 == 0 for index in range(WINDOW + 2)]
    for index, correct in enumerate(results):
        _seed_attempt(
            "ai-103",
            "D1.1-foo",
            f"a{index}",
            f"2020-01-{index + 1:02d}T00:00:00Z",
            correct,
        )

    response = client.get("/topics/ai-103/objectives/states?as_of=2020-06-01T00:00:00Z")
    state = response.json()[0]
    assert state["total_attempts"] == WINDOW + 2
    assert state["recent_window"] == results[-WINDOW:]


@pytest.mark.spec
def test_unstarted_respects_the_cut_date(client: TestClient) -> None:
    """Replacing the engine call's ``as_of`` with ``None`` would make this
    route silently use the real clock instead of the requested cut date.
    ``/due`` and ``/stale`` already bind this; this pins it for
    ``/unstarted`` too, straddling the one attempt with two ``as_of``
    values."""
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", "2020-01-10T00:00:00Z", True)

    before = client.get(
        "/topics/ai-103/objectives/unstarted?as_of=2020-01-05T00:00:00Z"
    ).json()
    after = client.get(
        "/topics/ai-103/objectives/unstarted?as_of=2020-01-15T00:00:00Z"
    ).json()

    assert [item["objective_id"] for item in before] == ["D1.1-foo"]
    assert after == []


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
def test_stale_uses_the_engine_default_when_days_is_omitted(client: TestClient) -> None:
    """``days`` is left out of the query entirely, so the engine's own
    ``DEFAULT_STALE_DAYS`` must be what decides the boundary. Restating ``14``
    in the router, or dropping ``days`` from the ``get_stale`` call so it
    silently falls back to some other value, both pass a suite that always
    sends ``days`` explicitly — which is what every other stale test here
    does. This one imports the constant rather than writing ``14``, so it
    keeps pinning the exact boundary if the constant ever moves."""
    at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", _iso(at), True)

    not_yet_stale = client.get(
        "/topics/ai-103/objectives/stale"
        f"?as_of={_iso(at + timedelta(days=DEFAULT_STALE_DAYS - 1))}"
    ).json()
    now_stale = client.get(
        "/topics/ai-103/objectives/stale"
        f"?as_of={_iso(at + timedelta(days=DEFAULT_STALE_DAYS + 1))}"
    ).json()

    assert not_yet_stale == []
    assert [item["objective_id"] for item in now_stale] == ["D1.1-foo"]


@pytest.mark.spec
def test_stale_days_parameter_overrides_the_default(client: TestClient) -> None:
    """A hardcoded ``14`` in the router is byte-identical to passing ``None``
    today, since ``DEFAULT_STALE_DAYS`` is 14 — no test of the omitted-``days``
    path alone can ever tell them apart. An explicit override that is nowhere
    near the default can: at gap=5 days, the default says "not stale" and
    ``days=1`` says "stale". Only forwarding the caller's ``days`` all the way
    to the engine satisfies both."""
    at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    _seed_objective("ai-103", "D1.1-foo")
    _seed_attempt("ai-103", "D1.1-foo", "a1", _iso(at), True)
    as_of = _iso(at + timedelta(days=5))

    with_default = client.get(f"/topics/ai-103/objectives/stale?as_of={as_of}").json()
    with_override = client.get(
        f"/topics/ai-103/objectives/stale?as_of={as_of}&days=1"
    ).json()

    assert with_default == []
    assert [item["objective_id"] for item in with_override] == ["D1.1-foo"]


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


# --------------------------------------------------------------- ACU-250: practice

def _insert_objective(conn, objective_id: str, topic_id: str = "ai-103") -> None:
    conn.execute(
        f"""INSERT INTO {POSTGRES_SCHEMA}.objectives
            (profile_id, objective_id, title, domain, weight, tags)
            VALUES (%s, %s, 'Title', NULL, 1.0, ARRAY[]::text[])""",
        (topic_id, objective_id),
    )


def _insert_attempt(
    conn, objective_id: str, at: datetime, correct: bool, topic_id: str = "ai-103"
) -> None:
    conn.execute(
        f"""INSERT INTO {POSTGRES_SCHEMA}.attempts
            (attempt_id, profile_id, objective_id, at, correct, kind, recorded_at)
            VALUES (%s, %s, %s, %s, %s, 'quiz', %s)""",
        (uuid.uuid4().hex, topic_id, objective_id, at, correct, at),
    )


def _insert_question(
    conn,
    question_id: str,
    objective_id: str,
    topic_id: str = "ai-103",
    correct_key: str = "a",
) -> None:
    material_id = f"mat-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    conn.execute(
        f"""INSERT INTO {POSTGRES_SCHEMA}.materials
            (material_id, topic_id, title, source, body, created_at)
            VALUES (%s, %s, 'Material', 'src', 'body', %s)""",
        (material_id, topic_id, now),
    )
    options = json.dumps([["a", "Yes"], ["b", "No"]])
    conn.execute(
        f"""INSERT INTO {POSTGRES_SCHEMA}.questions
            (question_id, topic_id, objective_id, stem, options, correct_key,
             explanation, material_id, created_at)
            VALUES (%s, %s, %s, 'What is the answer?', %s::jsonb, %s,
                    'Because the spec says so.', %s, %s)""",
        (question_id, topic_id, objective_id, options, correct_key, material_id, now),
    )


@pytest.fixture
def practice_topic(client: TestClient) -> str:
    client.post("/topics", json={"topic_id": "ai-103", "name": "AI-103"})
    return "ai-103"


@pytest.mark.spec
def test_next_question_prefers_due_over_unstarted(client: TestClient, practice_topic: str) -> None:
    """The engine's ordering decides, not this layer: due beats unstarted."""
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-due")
        _insert_objective(conn, "obj-new")
        # A miss five days ago sets next_review_at = at + 1 day, well in the
        # past: is_due is True. obj-new never had an attempt: get_unstarted.
        _insert_attempt(
            conn, "obj-due", datetime.now(timezone.utc) - timedelta(days=5), correct=False
        )
        _insert_question(conn, "q-due", "obj-due")
        _insert_question(conn, "q-new", "obj-new")
        conn.commit()

    response = client.get(f"/topics/{practice_topic}/practice/next")
    assert response.status_code == 200
    assert response.json()["objective_id"] == "obj-due"


@pytest.mark.spec
def test_next_question_orders_most_overdue_due_objective_first(
    client: TestClient, practice_topic: str
) -> None:
    """"Most overdue first" is the headline rule of SPEC section 5.2.

    Distinct from the due-vs-unstarted preference above: both objectives
    here are due, so this is the only test that actually exercises ordering
    among several due objectives rather than the due/unstarted boundary.
    """
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-barely-due")
        _insert_objective(conn, "obj-very-overdue")
        now = datetime.now(timezone.utc)
        # A miss sets next_review_at = at + 1 day (SPEC section 4.2, S=0).
        # obj-barely-due: next_review_at = now - 1 day (just crossed is_due).
        # obj-very-overdue: next_review_at = now - 9 days (far more overdue).
        _insert_attempt(conn, "obj-barely-due", now - timedelta(days=2), correct=False)
        _insert_attempt(conn, "obj-very-overdue", now - timedelta(days=10), correct=False)
        _insert_question(conn, "q-barely-due", "obj-barely-due")
        _insert_question(conn, "q-very-overdue", "obj-very-overdue")
        conn.commit()

    response = client.get(f"/topics/{practice_topic}/practice/next")
    assert response.status_code == 200
    assert response.json()["objective_id"] == "obj-very-overdue"


@pytest.mark.edge
def test_next_question_skips_due_objective_without_a_question(
    client: TestClient, practice_topic: str
) -> None:
    """A content gap on the most urgent objective must not brick the endpoint.

    The consumer repo has questions for only a fraction of its objectives
    (HANDOFF.md, Open questions). The single most likely production state is
    exactly this one: the most overdue objective has no question. ``/next``
    must keep walking the engine's order until it finds an objective that
    does, not stop at the first element and 404 forever.
    """
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-mute-but-urgent")
        _insert_objective(conn, "obj-covered")
        now = datetime.now(timezone.utc)
        # obj-mute-but-urgent is far more overdue, but has no question.
        _insert_attempt(conn, "obj-mute-but-urgent", now - timedelta(days=20), correct=False)
        _insert_attempt(conn, "obj-covered", now - timedelta(days=2), correct=False)
        _insert_question(conn, "q-covered", "obj-covered")
        conn.commit()

    response = client.get(f"/topics/{practice_topic}/practice/next")
    assert response.status_code == 200
    assert response.json()["objective_id"] == "obj-covered"


@pytest.mark.edge
def test_next_question_rotates_through_available_questions(
    client: TestClient, practice_topic: str
) -> None:
    """A fixed "first in canonical order" pick would serve the same card
    forever until the level moved, testing card recall rather than mastery
    of the objective. The pick must rotate as ``total_attempts`` grows.

    The second attempt is inserted directly (rather than via ``POST
    .../answer``) with a date far enough in the past to make the objective
    due again immediately: recording through the API always leaves
    ``next_review_at`` in the future relative to "now", so the objective
    would otherwise vanish from both ``get_due`` and ``get_unstarted``
    between the two ``GET`` calls -- true of the real app too, not a test
    artifact, which is exactly why the rotation index has to come from state
    already in hand rather than a second engine round trip.
    """
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-rotate")
        _insert_question(conn, "q-rotate-0", "obj-rotate")
        _insert_question(conn, "q-rotate-1", "obj-rotate")
        conn.commit()

    # total_attempts == 0: unstarted, index 0 % 2 == 0.
    first = client.get(f"/topics/{practice_topic}/practice/next")
    assert first.status_code == 200
    assert first.json()["question_id"] == "q-rotate-0"

    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_attempt(
            conn, "obj-rotate", datetime.now(timezone.utc) - timedelta(days=5), correct=False
        )
        conn.commit()

    # total_attempts == 1, now due: index 1 % 2 == 1.
    second = client.get(f"/topics/{practice_topic}/practice/next")
    assert second.status_code == 200
    assert second.json()["question_id"] == "q-rotate-1"


@pytest.mark.spec
def test_next_question_falls_back_to_unstarted_when_nothing_is_due(
    client: TestClient, practice_topic: str
) -> None:
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-fresh")
        _insert_question(conn, "q-fresh", "obj-fresh")
        conn.commit()

    response = client.get(f"/topics/{practice_topic}/practice/next")
    assert response.status_code == 200
    assert response.json()["objective_id"] == "obj-fresh"


@pytest.mark.edge
def test_next_question_hides_the_solution(client: TestClient, practice_topic: str) -> None:
    """The prototype this replaces shipped the answer with the question.

    The correct key and the explanation must not appear anywhere in the
    response body, before the question has been answered.
    """
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-secret")
        _insert_question(conn, "q-secret", "obj-secret", correct_key="b")
        conn.commit()

    response = client.get(f"/topics/{practice_topic}/practice/next")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"topic_id", "objective_id", "question_id", "stem", "options"}
    assert "correct_key" not in response.text
    assert "Because the spec says so." not in response.text


@pytest.mark.edge
def test_due_objective_without_questions_fails_clearly(
    client: TestClient, practice_topic: str
) -> None:
    """The engine says an objective is due, but the topic has no question for
    it: this must say so, not answer an empty success."""
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-mute")
        _insert_attempt(
            conn, "obj-mute", datetime.now(timezone.utc) - timedelta(days=5), correct=False
        )
        conn.commit()

    response = client.get(f"/topics/{practice_topic}/practice/next")
    assert response.status_code == 404
    assert "obj-mute" in response.json()["detail"]


@pytest.mark.edge
def test_next_unknown_topic_fails(client: TestClient) -> None:
    response = client.get("/topics/does-not-exist/practice/next")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


@pytest.mark.spec
def test_answering_correctly_records_one_attempt_and_new_state(
    client: TestClient, practice_topic: str
) -> None:
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-answer")
        _insert_question(conn, "q-answer", "obj-answer", correct_key="a")
        conn.commit()

    response = client.post(
        f"/topics/{practice_topic}/practice/answer",
        json={"question_id": "q-answer", "attempt_id": "att-1", "selected_key": "a"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert body["explanation"] == "Because the spec says so."
    assert body["objective_id"] == "obj-answer"
    assert body["state"]["total_attempts"] == 1
    assert body["state"]["correct_attempts"] == 1
    # n=1 < MIN_ATTEMPTS (SPEC C2): one attempt is not enough evidence yet.
    assert body["state"]["level"] == "UNASSESSED"

    with psycopg.connect(POSTGRES_DSN) as conn:
        (count,) = conn.execute(
            f"SELECT count(*) FROM {POSTGRES_SCHEMA}.attempts WHERE objective_id = 'obj-answer'"
        ).fetchone()
    assert count == 1


@pytest.mark.spec
def test_answering_wrong_is_recorded_as_wrong(client: TestClient, practice_topic: str) -> None:
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-wrong")
        _insert_question(conn, "q-wrong", "obj-wrong", correct_key="a")
        conn.commit()

    response = client.post(
        f"/topics/{practice_topic}/practice/answer",
        json={"question_id": "q-wrong", "attempt_id": "att-2", "selected_key": "b"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is False
    assert body["state"]["correct_attempts"] == 0

    with psycopg.connect(POSTGRES_DSN) as conn:
        (correct,) = conn.execute(
            f"SELECT correct FROM {POSTGRES_SCHEMA}.attempts WHERE objective_id = 'obj-wrong'"
        ).fetchone()
    assert correct is False


@pytest.mark.edge
def test_duplicate_attempt_id_is_rejected_not_duplicated(
    client: TestClient, practice_topic: str
) -> None:
    """One question, one recorded attempt: a retried request must not double it."""
    with psycopg.connect(POSTGRES_DSN) as conn:
        _insert_objective(conn, "obj-dup")
        _insert_question(conn, "q-dup", "obj-dup", correct_key="a")
        conn.commit()

    body = {"question_id": "q-dup", "attempt_id": "att-dup", "selected_key": "a"}
    first = client.post(f"/topics/{practice_topic}/practice/answer", json=body)
    second = client.post(f"/topics/{practice_topic}/practice/answer", json=body)
    assert first.status_code == 200
    assert second.status_code == 409

    with psycopg.connect(POSTGRES_DSN) as conn:
        (count,) = conn.execute(
            f"SELECT count(*) FROM {POSTGRES_SCHEMA}.attempts WHERE objective_id = 'obj-dup'"
        ).fetchone()
    assert count == 1


@pytest.mark.edge
def test_answer_unknown_question_fails_instead_of_empty_success(
    client: TestClient, practice_topic: str
) -> None:
    response = client.post(
        f"/topics/{practice_topic}/practice/answer",
        json={"question_id": "does-not-exist", "attempt_id": "att-3", "selected_key": "a"},
    )
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


# ============================================================ material (ACU-249)


@pytest.fixture
def material_topic(client: TestClient):
    """A topic plus a generator that needs no network and no credential.

    The application builds the real generator at startup; swapping it here is
    what keeps the suite from depending on a key or on the model being up,
    and what makes generation assertions deterministic.
    """
    from generate.stub import StubGenerator

    client.post("/topics", json={"topic_id": "ai-103", "name": "AI-103"})
    client.app.state.resources.generator = StubGenerator()
    return "ai-103"


def _upload(client: TestClient, topic_id: str, *, title: str = "Cuotas", body: str | None = None):
    return client.post(
        f"/topics/{topic_id}/material",
        json={
            "title": title,
            "source": "notes.md",
            "body": body
            or ". ".join(f"Concepto {i} sobre cuotas y limites de la plataforma" for i in range(10)),
        },
    )


@pytest.mark.spec
def test_upload_stores_the_page_and_returns_it(client: TestClient, material_topic: str) -> None:
    response = _upload(client, material_topic)
    assert response.status_code == 201
    body = response.json()
    assert body["material_id"]
    assert body["topic_id"] == material_topic
    assert body["title"] == "Cuotas"
    assert "Concepto 0" in body["body"]


@pytest.mark.spec
def test_listing_is_newest_first_and_carries_no_bodies(
    client: TestClient, material_topic: str
) -> None:
    """Bodies are whole pages; a listing that shipped them would slow down as
    a topic accumulates material, which is backwards."""
    _upload(client, material_topic, title="Primera")
    _upload(client, material_topic, title="Segunda")

    listing = client.get(f"/topics/{material_topic}/material")
    assert listing.status_code == 200
    rows = listing.json()
    assert [r["title"] for r in rows] == ["Segunda", "Primera"]
    assert all("body" not in r for r in rows)


@pytest.mark.spec
def test_reading_one_material_includes_its_body(client: TestClient, material_topic: str) -> None:
    material_id = _upload(client, material_topic).json()["material_id"]
    got = client.get(f"/topics/{material_topic}/material/{material_id}")
    assert got.status_code == 200
    assert "Concepto 0" in got.json()["body"]


@pytest.mark.spec
def test_generation_writes_objectives_and_questions(
    client: TestClient, material_topic: str
) -> None:
    material_id = _upload(client, material_topic).json()["material_id"]
    generated = client.post(f"/topics/{material_topic}/material/{material_id}/generate")
    assert generated.status_code == 200
    body = generated.json()
    assert body["questions_written"] > 0
    assert body["objectives_written"] > 0

    # The questions are reachable through the study path, which is the only
    # reason to have written them.
    nxt = client.get(f"/topics/{material_topic}/practice/next")
    assert nxt.status_code == 200


@pytest.mark.spec
def test_regenerating_replaces_questions_and_never_touches_attempts(
    client: TestClient, material_topic: str
) -> None:
    """The guarantee that matters most in this router.

    Questions are derived and disposable. Attempts are evidence of what
    somebody knew, are append-only by contract, and regenerating the questions
    does not un-know it (SPEC I1).
    """
    material_id = _upload(client, material_topic).json()["material_id"]
    first = client.post(f"/topics/{material_topic}/material/{material_id}/generate").json()

    question = client.get(f"/topics/{material_topic}/practice/next").json()
    answered = client.post(
        f"/topics/{material_topic}/practice/answer",
        json={
            "question_id": question["question_id"],
            "attempt_id": "att-before-regeneration",
            "selected_key": question["options"][0]["key"],
        },
    )
    assert answered.status_code == 200

    with psycopg.connect(POSTGRES_DSN) as conn:
        before = conn.execute(f"SELECT count(*) FROM {POSTGRES_SCHEMA}.attempts").fetchone()[0]
    assert before == 1

    second = client.post(f"/topics/{material_topic}/material/{material_id}/generate").json()
    assert second["questions_written"] == first["questions_written"]

    with psycopg.connect(POSTGRES_DSN) as conn:
        after = conn.execute(f"SELECT count(*) FROM {POSTGRES_SCHEMA}.attempts").fetchone()[0]
        questions = conn.execute(
            f"SELECT count(*) FROM {POSTGRES_SCHEMA}.questions WHERE material_id = %s",
            (material_id,),
        ).fetchone()[0]
    assert after == before, "regenerating destroyed recorded evidence"
    assert questions == second["questions_written"], "regeneration accumulated duplicates"


@pytest.mark.spec
def test_oversized_body_is_refused_with_its_size(client: TestClient, material_topic: str) -> None:
    from web.routers.material import MAX_BODY_CHARS

    response = _upload(client, material_topic, body="x" * (MAX_BODY_CHARS + 1))
    assert response.status_code == 413
    assert str(MAX_BODY_CHARS) in response.json()["detail"]


@pytest.mark.spec
def test_upload_to_unknown_topic_fails_instead_of_orphaning(client: TestClient) -> None:
    response = _upload(client, "no-such-topic")
    assert response.status_code == 404
    assert "no-such-topic" in response.json()["detail"]


@pytest.mark.spec
def test_material_of_another_topic_is_not_reachable(client: TestClient, material_topic: str) -> None:
    """Material ids are unique across topics, so fetching by id alone would
    serve somebody else's page from this topic's URL."""
    client.post("/topics", json={"topic_id": "az-900", "name": "AZ-900"})
    material_id = _upload(client, material_topic).json()["material_id"]

    got = client.get(f"/topics/az-900/material/{material_id}")
    assert got.status_code == 404
    assert material_id in got.json()["detail"]


@pytest.mark.spec
def test_missing_credential_fails_only_generation(client: TestClient, material_topic: str) -> None:
    """Everything that is not generation keeps working without a key."""
    from generate.errors import MissingCredentialsError

    class NoCredentials:
        def generate(self, material, existing_objectives, *, now):
            raise MissingCredentialsError("ANTHROPIC_API_KEY is not set")

    client.app.state.resources.generator = NoCredentials()
    material_id = _upload(client, material_topic).json()["material_id"]

    generated = client.post(f"/topics/{material_topic}/material/{material_id}/generate")
    assert generated.status_code == 503
    assert "ANTHROPIC_API_KEY" in generated.json()["detail"]

    # Uploading, listing and reading are unaffected.
    assert _upload(client, material_topic, title="Otra").status_code == 201
    assert client.get(f"/topics/{material_topic}/material").status_code == 200
    assert client.get(f"/topics/{material_topic}/material/{material_id}").status_code == 200


@pytest.mark.spec
def test_blank_fields_are_rejected_as_a_client_error(
    client: TestClient, material_topic: str
) -> None:
    """Whitespace is not a title, and saying so is this layer's job.

    ``Material`` refuses to be built from a blank field. Without a matching
    check here, a title of three spaces passed request validation, failed
    inside the domain model, and reached the caller as an unhandled 500: a
    client mistake reported as a server fault (ACU-249 review).
    """
    for field in ("title", "source", "body"):
        payload = {"title": "T", "source": "s.md", "body": "cuerpo", field: "   "}
        response = client.post(f"/topics/{material_topic}/material", json=payload)
        assert response.status_code == 422, f"{field} blank returned {response.status_code}"


@pytest.mark.spec
def test_generation_failure_is_502_not_a_crash(client: TestClient, material_topic: str) -> None:
    """A model that fails is a bad gateway, not a broken server."""
    from generate.errors import GenerationError

    class Failing:
        def generate(self, material, existing_objectives, *, now):
            raise GenerationError("the model produced no structured output")

    client.app.state.resources.generator = Failing()
    material_id = _upload(client, material_topic).json()["material_id"]
    response = client.post(f"/topics/{material_topic}/material/{material_id}/generate")
    assert response.status_code == 502
    assert "structured output" in response.json()["detail"]


@pytest.mark.spec
def test_listing_an_unknown_topic_is_404_not_an_empty_list(client: TestClient) -> None:
    """A front end must be able to tell "no such topic" from "topic is empty"."""
    response = client.get("/topics/no-such-topic/material")
    assert response.status_code == 404
    assert "no-such-topic" in response.json()["detail"]
