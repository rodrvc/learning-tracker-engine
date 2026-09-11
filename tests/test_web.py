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


