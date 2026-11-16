"""Per-user data (issue #58): two signed-in users with the same topic id never
see each other's topics, objectives, attempts or material.

Runs the real app against a throwaway Postgres schema, with authentication on
and tokens signed by a throwaway key (the JWKS lookup is the only thing faked,
exactly as in ``tests/test_auth.py``). Skips, with a reason, when Postgres is
not reachable - the same convention as ``tests/test_web.py``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import web.auth as auth_module
from content.errors import UnknownMaterialError
from content.models import Material, Question
from content.postgres import PostgresMaterialStore, PostgresQuestionStore
from core.models import Attempt, AttemptKind, Profile
from migrations.runner import apply_migrations
from store.postgres import LOCAL_USER_ID, PostgresAttemptStore, PostgresProfileStore
from web.app import create_app
from web.config import Settings

POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = os.environ.get(
    "LEARNING_TRACKER_TEST_DATABASE_URL",
    f"postgresql://learning_tracker:learning_tracker@localhost:{POSTGRES_PORT}"
    "/learning_tracker",
)
POSTGRES_SCHEMA = f"learning_test_scope_{uuid.uuid4().hex[:8]}"
ISSUER = "https://example-app.clerk.accounts.example"


def _postgres_reachable() -> bool:
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="module", autouse=True)
def _schema():
    if not _postgres_reachable():
        pytest.skip("postgres no disponible: levanta `docker compose up -d postgres`")
    apply_migrations(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    yield
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {POSTGRES_SCHEMA} CASCADE")
        conn.commit()


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _clean(_schema):
    yield
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"TRUNCATE {POSTGRES_SCHEMA}.attempts, {POSTGRES_SCHEMA}.questions, "
            f"{POSTGRES_SCHEMA}.materials, {POSTGRES_SCHEMA}.objectives, "
            f"{POSTGRES_SCHEMA}.profiles CASCADE"
        )
        conn.commit()


class _Key:
    def __init__(self, key):
        self.key = key


class _Jwks:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _Key(self._public_key)


def bearer(private_key, sub: str) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    claims = {"iss": ISSUER, "sub": sub, "iat": now, "exp": now + timedelta(minutes=5)}
    return {"Authorization": "Bearer " + jwt.encode(claims, private_key, algorithm="RS256")}


@pytest.fixture
def secured(monkeypatch, private_key):
    monkeypatch.setattr(
        auth_module, "_jwks_client", lambda issuer: _Jwks(private_key.public_key())
    )
    settings = Settings(
        database_url=POSTGRES_DSN,
        schema=POSTGRES_SCHEMA,
        host="127.0.0.1",
        port=8000,
        clerk_issuer=ISSUER,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _seed_topic(client, headers, *, attempts: int):
    """One topic ``t1`` with one objective, ``attempts`` attempts and a material."""
    assert client.post("/topics", json={"topic_id": "t1", "name": "T1"}, headers=headers).status_code == 201
    assert (
        client.post(
            "/topics/t1/objectives",
            json={"objectives": [{"objective_id": "o1", "title": "O1"}]},
            headers=headers,
        ).status_code
        == 201
    )
    now = datetime.now(timezone.utc)
    for index in range(attempts):
        response = client.post(
            "/topics/t1/objectives/o1/attempts",
            json={
                "correct": True,
                "at": (now - timedelta(days=index + 1)).isoformat(),
                "kind": "quiz",
                "attempt_id": uuid.uuid4().hex,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
    material = client.post(
        "/topics/t1/material",
        json={"title": "Notes", "source": "me", "body": "some notes"},
        headers=headers,
    )
    assert material.status_code == 201
    return material.json()["material_id"]


@pytest.mark.spec
def test_two_users_with_the_same_topic_id_never_see_each_other(secured, private_key):
    alice = bearer(private_key, "user_alice")
    bob = bearer(private_key, "user_bob")
    alice_material = _seed_topic(secured, alice, attempts=3)

    # Bob sees nothing of Alice's: no topic, no objectives, no material.
    assert secured.get("/topics", headers=bob).json() == []
    assert secured.get("/topics/t1", headers=bob).status_code == 404
    assert secured.get("/topics/t1/material", headers=bob).status_code == 404
    assert secured.get("/topics/t1/summary", headers=bob).status_code == 404

    # The same topic id is free for Bob: no 409 from Alice's.
    bob_material = _seed_topic(secured, bob, attempts=1)

    alice_summary = secured.get("/topics/t1/summary", headers=alice).json()
    bob_summary = secured.get("/topics/t1/summary", headers=bob).json()
    assert alice_summary["total_attempts"] == 3
    assert bob_summary["total_attempts"] == 1

    assert [m["material_id"] for m in secured.get("/topics/t1/material", headers=alice).json()] == [
        alice_material
    ]
    assert [m["material_id"] for m in secured.get("/topics/t1/material", headers=bob).json()] == [
        bob_material
    ]
    # Another user's material id is not reachable even by guessing it.
    assert secured.get(f"/topics/t1/material/{alice_material}", headers=bob).status_code == 404
    assert [t["topic_id"] for t in secured.get("/topics", headers=alice).json()] == ["t1"]


@pytest.mark.spec
def test_user_id_comes_from_the_token_never_from_the_request(secured, private_key):
    """A query string or body naming another user changes nothing."""
    alice = bearer(private_key, "user_alice")
    bob = bearer(private_key, "user_bob")
    _seed_topic(secured, alice, attempts=1)
    response = secured.get("/topics?user_id=user_alice", headers=bob)
    assert response.json() == []
    response = secured.get("/topics", headers={**bob, "X-User-Id": "user_alice"})
    assert response.json() == []


@pytest.mark.edge
def test_attempt_ids_stay_globally_unique_across_users(secured, private_key):
    alice = bearer(private_key, "user_alice")
    bob = bearer(private_key, "user_bob")
    _seed_topic(secured, alice, attempts=0)
    _seed_topic(secured, bob, attempts=0)
    body = {
        "correct": True,
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": "quiz",
        "attempt_id": "shared-id",
    }
    path = "/topics/t1/objectives/o1/attempts"
    assert secured.post(path, json=body, headers=alice).status_code == 201
    assert secured.post(path, json=body, headers=bob).status_code == 409
    assert secured.get("/topics/t1/summary", headers=bob).json()["total_attempts"] == 0


@pytest.mark.spec
def test_auth_off_is_one_implicit_local_user():
    settings = Settings(
        database_url=POSTGRES_DSN, schema=POSTGRES_SCHEMA, host="127.0.0.1", port=8000
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/topics", json={"topic_id": "t1", "name": "T1"}).status_code == 201
    stored = PostgresProfileStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    assert [p.profile_id for p in stored.list_profiles()] == ["t1"]
    with psycopg.connect(POSTGRES_DSN) as conn:
        (owner,) = conn.execute(f"SELECT user_id FROM {POSTGRES_SCHEMA}.profiles").fetchone()
    assert owner == LOCAL_USER_ID


@pytest.mark.spec
def test_stores_bound_to_different_users_are_disjoint():
    base = PostgresProfileStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    ann, ben = base.for_user("ann"), base.for_user("ben")
    ann.save_profile(Profile(profile_id="p", name="Ann's"))
    assert ben.list_profiles() == []
    ben.save_profile(Profile(profile_id="p", name="Ben's"))
    assert ann.get_profile("p").name == "Ann's"
    assert ben.get_profile("p").name == "Ben's"
    assert [p.profile_id for p in base.list_profiles()] == []  # the local user owns nothing

    attempts = PostgresAttemptStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    now = datetime.now(timezone.utc)
    attempts.for_user("ann").append(
        "p", Attempt(attempt_id="a1", objective_id="o", at=now, correct=True, kind=AttemptKind.QUIZ)
    )
    assert attempts.for_user("ann").count("p") == 1
    assert attempts.for_user("ben").count("p") == 0
    assert attempts.for_user("ben").list_all("p") == []


@pytest.mark.edge
def test_empty_user_id_is_rejected():
    with pytest.raises(ValueError):
        PostgresProfileStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA, user_id="  ")


@pytest.mark.spec
def test_a_user_cannot_attach_questions_to_another_users_material():
    """``material_id`` is a global key and the foreign key on it does not look
    at ``user_id``, so the question store has to: user B writing a question
    that points at user A's material must fail, and must leave A's set alone."""
    now = datetime.now(timezone.utc)
    materials = PostgresMaterialStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    questions = PostgresQuestionStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    materials.for_user("ann").add(
        Material(material_id="m1", topic_id="t", title="T", source="S", body="B", created_at=now)
    )
    foreign = Question(
        question_id="q-ben",
        topic_id="t",
        objective_id="o",
        stem="Stem?",
        options=(("a", "A"), ("b", "B")),
        correct_key="a",
        explanation="Because.",
        material_id="m1",
        created_at=now,
    )
    with pytest.raises(UnknownMaterialError):
        questions.for_user("ben").add_many([foreign])
    assert questions.for_user("ann").list_for_topic("t") == []
    assert questions.for_user("ben").list_for_topic("t") == []
    with pytest.raises(UnknownMaterialError):
        questions.for_user("ben").replace_for_material("m1", [foreign])
