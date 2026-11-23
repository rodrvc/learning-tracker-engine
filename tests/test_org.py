"""Teacher view (issue #75): org claims from the token, membership, the
read-only ``GET /org/progress`` and the dev-only impersonation.

The claim-parsing and impersonation tests need no database (``/me`` never
touches storage); the rest run against a throwaway Postgres schema and skip,
with a reason, when it is not reachable.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import web.auth as auth_module
from core.models import Attempt, AttemptKind, Objective, Profile
from migrations.runner import apply_migrations
from store.members import PostgresMemberStore
from store.postgres import PostgresAttemptStore, PostgresProfileStore
from web.app import create_app
from web.auth import identity_from_claims, normalize_role
from web.config import ConfigurationError, Settings

from .clerk_support import ISSUER, StubJwksClient, bearer

DEAD_DSN = "postgresql://nobody:nobody@127.0.0.1:1/nowhere"
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = os.environ.get(
    "LEARNING_TRACKER_TEST_DATABASE_URL",
    f"postgresql://learning_tracker:learning_tracker@localhost:{POSTGRES_PORT}"
    "/learning_tracker",
)
POSTGRES_SCHEMA = f"learning_test_org_{uuid.uuid4().hex[:8]}"

TEACHER = {"o": {"id": "org_1", "rol": "admin"}}
STUDENT = {"o": {"id": "org_1", "rol": "member"}}


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def stub_jwks(monkeypatch, private_key):
    monkeypatch.setattr(
        auth_module, "_jwks_client", lambda issuer: StubJwksClient(private_key.public_key())
    )


def _client(dsn=DEAD_DSN, schema=None, issuer=ISSUER) -> TestClient:
    settings = Settings(
        database_url=dsn,
        schema=schema,
        host="127.0.0.1",
        port=8000,
        clerk_issuer=issuer,
        auth_disabled=issuer is None,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


# --- claim parsing (no database) ---------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    "role, expected",
    [("admin", "org:admin"), ("org:admin", "org:admin"), ("member", "org:member"), ("", None), (None, None), (3, None)],
)
def test_role_is_normalized_to_the_full_clerk_key(role, expected):
    assert normalize_role(role) == expected


@pytest.mark.spec
def test_v2_token_shape_reads_o_id_and_o_rol():
    identity = identity_from_claims({"sub": "u1", "v": 2, "o": {"id": "org_9", "rol": "admin", "slg": "x"}})
    assert (identity.user_id, identity.org_id, identity.org_role) == ("u1", "org_9", "org:admin")
    assert identity.is_org_admin


@pytest.mark.spec
def test_v1_token_shape_reads_org_id_and_org_role():
    identity = identity_from_claims({"sub": "u1", "org_id": "org_9", "org_role": "org:member"})
    assert (identity.org_id, identity.org_role) == ("org_9", "org:member")
    assert not identity.is_org_admin


@pytest.mark.edge
def test_no_organization_means_no_role_and_no_admin():
    assert identity_from_claims({"sub": "u1"}).org_id is None
    orphan = identity_from_claims({"sub": "u1", "org_role": "org:admin"})
    assert orphan.org_role is None and not orphan.is_org_admin


@pytest.mark.spec
def test_a_verified_token_carries_its_org_to_the_request(stub_jwks, private_key):
    with _client() as client:
        body = client.get("/me", headers=bearer(private_key, "t1", **TEACHER)).json()
    assert body == {"user_id": "t1", "org_id": "org_1", "org_role": "org:admin", "is_teacher": True}


# --- impersonation (no database) ----------------------------------------------

DEV = {"X-Dev-User": "demo_teacher", "X-Dev-Org": "org_demo", "X-Dev-Role": "admin"}


@pytest.mark.spec
def test_dev_headers_pick_an_identity_when_auth_is_off():
    with _client(issuer=None) as client:
        assert client.get("/me").json()["user_id"] == "local"
        body = client.get("/me", headers=DEV).json()
    assert body == {
        "user_id": "demo_teacher",
        "org_id": "org_demo",
        "org_role": "org:admin",
        "is_teacher": True,
    }


@pytest.mark.spec
def test_dev_headers_are_never_honoured_when_auth_is_on(stub_jwks, private_key):
    with _client() as client:
        # No session: the headers do not stand in for one.
        assert client.get("/me", headers=DEV).status_code == 401
        # With a session: the token wins, the headers change nothing.
        body = client.get("/me", headers={**bearer(private_key, "real_student", **STUDENT), **DEV}).json()
        forged = client.get("/org/progress", headers={**bearer(private_key, "real_student", **STUDENT), **DEV})
    assert body["user_id"] == "real_student" and body["is_teacher"] is False
    assert forged.status_code == 403


@pytest.mark.spec
def test_a_deploy_missing_its_issuer_refuses_to_start_instead_of_trusting_dev_headers():
    # The review risk: with the issuer unset the app used to fall back to
    # X-Dev-* identities, so anyone could claim org:admin. Authentication now
    # fails closed: no issuer and no explicit opt-out means no app at all, so
    # there is nothing to send dev headers to.
    env = {"LEARNING_TRACKER_DATABASE_URL": DEAD_DSN}
    with pytest.raises(ConfigurationError):
        Settings.from_env(env)
    # Only the explicit opt-out makes the headers meaningful.
    off = Settings.from_env({**env, "LEARNING_TRACKER_AUTH_DISABLED": "true"})
    with TestClient(create_app(off), raise_server_exceptions=False) as client:
        assert client.get("/me", headers=DEV).json()["is_teacher"] is True


@pytest.mark.spec
def test_non_admins_get_403_before_storage_is_touched(stub_jwks, private_key):
    with _client() as client:  # dead database: a 403 proves it never got that far
        member = client.get("/org/progress", headers=bearer(private_key, "s1", **STUDENT))
        no_org = client.get("/org/progress", headers=bearer(private_key, "s2"))
    assert member.status_code == 403
    assert no_org.status_code == 403


# --- with Postgres ------------------------------------------------------------


def _postgres_reachable() -> bool:
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="module")
def schema():
    if not _postgres_reachable():
        pytest.skip("postgres no disponible: levanta `docker compose up -d postgres`")
    apply_migrations(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    yield POSTGRES_SCHEMA
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {POSTGRES_SCHEMA} CASCADE")
        conn.commit()


@pytest.fixture
def db(schema):
    yield schema
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"TRUNCATE {schema}.attempts, {schema}.questions, {schema}.materials, "
            f"{schema}.objectives, {schema}.profiles, {schema}.org_members CASCADE"
        )
        conn.commit()


def _learn(user_id: str, topic: str, history: dict[str, list[tuple[bool, int]]]) -> None:
    """Writes a topic for ``user_id`` straight into the stores: ``history``
    maps objective id to (correct, days ago) attempts."""
    profiles = PostgresProfileStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA, user_id=user_id)
    attempts = PostgresAttemptStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA, user_id=user_id)
    profiles.save_profile(
        Profile(
            profile_id=topic,
            name=topic.title(),
            objectives={o: Objective(objective_id=o, title=o) for o in history},
        )
    )
    now = datetime.now(timezone.utc)
    for objective, rows in history.items():
        for index, (correct, days_ago) in enumerate(rows):
            attempts.append(
                topic,
                Attempt(
                    attempt_id=f"{user_id}-{topic}-{objective}-{index}",
                    objective_id=objective,
                    at=now - timedelta(days=days_ago),
                    correct=correct,
                    kind=AttemptKind.QUIZ,
                ),
            )


def _touch(user_id: str, role: str, *, name=None, org="org_1") -> None:
    PostgresMemberStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA).upsert(
        org, user_id, role, datetime.now(timezone.utc), display_name=name
    )


@pytest.mark.spec
def test_teacher_sees_each_members_summary_per_topic(db, stub_jwks, private_key):
    _learn("ana", "redes", {"o1": [(True, 9), (True, 8), (True, 7)], "o2": [(False, 6)], "o3": []})
    _learn("bruno", "redes", {"o1": []})
    _touch("ana", "org:member", name="Ana")
    _touch("bruno", "org:member")
    with _client(POSTGRES_DSN, db) as client:
        response = client.get("/org/progress", headers=bearer(private_key, "teacher", **TEACHER))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["org_id"] == "org_1"
    members = {m["user_id"]: m for m in body["members"]}
    assert set(members) == {"ana", "bruno"}  # the teacher is not listed among students
    assert members["ana"]["display_name"] == "Ana"
    assert members["bruno"]["display_name"] == "bruno"
    (ana_topic,) = members["ana"]["topics"]
    assert ana_topic["topic_id"] == "redes"
    assert ana_topic["total_objectives"] == 3
    assert ana_topic["unstarted_objectives"] == 1  # o3, never practised
    assert ana_topic["total_attempts"] == 4
    assert ana_topic["due_objectives"] >= 1  # o2 was missed 6 days ago
    assert ana_topic["level"] in {"UNASSESSED", "WEAK", "LEARNING", "COMPETENT", "MASTERED"}
    (bruno_topic,) = members["bruno"]["topics"]
    assert bruno_topic["unstarted_objectives"] == 1 and bruno_topic["level"] == "UNASSESSED"


@pytest.mark.spec
def test_teacher_only_sees_their_own_organization(db, stub_jwks, private_key):
    _learn("ana", "redes", {"o1": [(True, 2)]})
    _learn("zoe", "redes", {"o1": [(True, 2)]})
    _touch("ana", "org:member", org="org_1")
    _touch("zoe", "org:member", org="org_2")
    with _client(POSTGRES_DSN, db) as client:
        body = client.get("/org/progress", headers=bearer(private_key, "teacher", **TEACHER)).json()
    assert [m["user_id"] for m in body["members"]] == ["ana"]


@pytest.mark.spec
def test_membership_is_recorded_from_an_authenticated_request(db, stub_jwks, private_key):
    with _client(POSTGRES_DSN, db) as client:
        client.get("/topics", headers=bearer(private_key, "s1", **STUDENT, name="Sofia", email="s@x.cl"))
        client.get("/topics", headers=bearer(private_key, "s1", **STUDENT))  # no name this time
        client.get("/topics", headers=bearer(private_key, "loner"))  # no organization
    members = PostgresMemberStore.from_dsn(POSTGRES_DSN, schema=db).list_members("org_1")
    assert [(m.user_id, m.role, m.display_name, m.email) for m in members] == [
        ("s1", "org:member", "Sofia", "s@x.cl")  # a later request without a name keeps it
    ]


@pytest.mark.spec
def test_members_never_see_anyone_elses_data(db, stub_jwks, private_key):
    _learn("ana", "redes", {"o1": [(True, 2)]})
    _learn("bruno", "redes", {"o1": [(False, 2)]})
    _touch("ana", "org:member")
    _touch("bruno", "org:member")
    with _client(POSTGRES_DSN, db) as client:
        ana = bearer(private_key, "ana", **STUDENT)
        assert client.get("/org/progress", headers=ana).status_code == 403
        summary = client.get("/topics/redes/summary", headers=ana).json()
        topics = client.get("/topics", headers=ana).json()
    assert summary["total_attempts"] == 1
    assert [t["topic_id"] for t in topics] == ["redes"]


@pytest.mark.spec
def test_dev_impersonation_drives_the_teacher_view_with_auth_off(db):
    _learn("demo_ana", "redes", {"o1": [(True, 3)]})
    student = {"X-Dev-User": "demo_ana", "X-Dev-Org": "org_demo", "X-Dev-Role": "member"}
    teacher = {"X-Dev-User": "demo_teacher", "X-Dev-Org": "org_demo", "X-Dev-Role": "admin"}
    with _client(POSTGRES_DSN, db, issuer=None) as client:
        assert client.get("/topics", headers=student).status_code == 200  # records membership
        assert client.get("/org/progress", headers=student).status_code == 403
        body = client.get("/org/progress", headers=teacher).json()
    assert [m["user_id"] for m in body["members"]] == ["demo_ana"]


@pytest.mark.spec
def test_demo_seed_gives_the_teacher_a_varied_class(db, monkeypatch):
    from scripts import seed_demo_org

    monkeypatch.setenv("LEARNING_TRACKER_DATABASE_URL", POSTGRES_DSN)
    monkeypatch.setenv("LEARNING_TRACKER_SCHEMA", db)
    assert seed_demo_org.main() == 0
    assert seed_demo_org.main() == 0  # idempotent
    teacher = {"X-Dev-User": "demo_teacher", "X-Dev-Org": "org_demo", "X-Dev-Role": "org:admin"}
    with _client(POSTGRES_DSN, db, issuer=None) as client:
        body = client.get("/org/progress", headers=teacher).json()
    rows = {m["user_id"]: m["topics"][0] for m in body["members"]}
    assert set(rows) == {"demo_ana", "demo_bruno", "demo_carla", "demo_diego"}
    assert rows["demo_carla"]["unstarted_objectives"] > rows["demo_ana"]["unstarted_objectives"]
    assert rows["demo_diego"]["due_objectives"] > rows["demo_ana"]["due_objectives"]
    assert len({r["level"] for r in rows.values()}) > 1
