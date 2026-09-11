"""Tests of ``content/`` against the guarantees of ``content/storage.py``.

Same harness shape as ``tests/test_store.py``: one shared, parametrized suite
runs against every backend (memory and Postgres) through the ``materials`` /
``questions`` fixtures, no per-backend branches. Postgres tests skip, with an
explicit reason, when no database is reachable.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from content.errors import (
    DuplicateMaterialError,
    DuplicateQuestionError,
    InvalidMaterialError,
    InvalidQuestionError,
    UnknownMaterialError,
    UnknownQuestionError,
)
from content.memory import new_memory_stores
from content.models import Material, Question
from content.storage import MaterialStore, QuestionStore

try:
    import psycopg

    from migrations.runner import apply_migrations
    from content.postgres import PostgresMaterialStore, PostgresQuestionStore
except ImportError:  # pragma: no cover - exercised when the postgres extra is absent
    psycopg = None

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TOPIC = "ai-103"

BACKENDS = ["memory", "postgres"]

# The compose file lets the host port move (5432 is usually taken by another
# project), so the default DSN has to follow it. Otherwise the normal case
# becomes "forgot the second variable, tests skipped, suite green".
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = os.environ.get(
    "LEARNING_TRACKER_TEST_DATABASE_URL",
    f"postgresql://learning_tracker:learning_tracker@localhost:{POSTGRES_PORT}"
    "/learning_tracker",
)
POSTGRES_SCHEMA = f"learning_test_content_{uuid.uuid4().hex[:8]}"


def _postgres_reachable() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


POSTGRES_AVAILABLE = _postgres_reachable()
_SKIP_REASON = (
    "postgres no disponible: instala el extra 'postgres', exporta "
    "LEARNING_TRACKER_TEST_DATABASE_URL o levanta `docker compose up -d postgres`"
)


@pytest.fixture(scope="session", autouse=True)
def _postgres_test_schema():
    """Builds a throwaway schema for the whole session and drops it after."""
    if POSTGRES_AVAILABLE:
        apply_migrations(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    yield
    if POSTGRES_AVAILABLE:
        with psycopg.connect(POSTGRES_DSN) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {POSTGRES_SCHEMA} CASCADE")
            conn.commit()


def _reset_postgres_schema() -> None:
    """Empties the throwaway schema so tests do not leak state into each other.

    ``TRUNCATE ... CASCADE`` also empties ``questions`` because it references
    ``materials`` - this follows from the foreign keys existing at all, not
    from their delete action (there is no ``ON DELETE CASCADE`` here: a
    manual ``DELETE`` against a live database is refused loudly instead,
    since ``MaterialStore`` is append-only).
    """
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(f"TRUNCATE {POSTGRES_SCHEMA}.materials CASCADE")
        conn.commit()


def day(n: int) -> datetime:
    return T0 + timedelta(days=n)


def make_material(material_id: str, topic_id: str = TOPIC, at: datetime = T0) -> Material:
    return Material(
        material_id=material_id, topic_id=topic_id, title="T", source="s", body="b", created_at=at
    )


def make_question(
    question_id: str, material_id: str, topic_id: str = TOPIC, objective_id: str = "D1.1", at=T0, **kw
) -> Question:
    return Question(
        question_id=question_id,
        topic_id=topic_id,
        objective_id=objective_id,
        stem="stem",
        options=kw.pop("options", (("a", "3"), ("b", "4"))),
        correct_key=kw.pop("correct_key", "b"),
        explanation="why",
        material_id=material_id,
        created_at=at,
    )

@pytest.fixture(params=BACKENDS)
def backend(request) -> str:
    return request.param


def _skip_if_postgres_unavailable(backend: str) -> None:
    if backend == "postgres" and not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)


@pytest.fixture
def content_store(backend):
    """A matched (MaterialStore, QuestionStore) pair sharing one backing
    store - the memory factory returns one directly; the two Postgres stores
    already share a connection provider and schema, so constructing them
    together here keeps both backends symmetric."""
    _skip_if_postgres_unavailable(backend)
    if backend == "memory":
        return new_memory_stores()
    _reset_postgres_schema()
    return (
        PostgresMaterialStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA),
        PostgresQuestionStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA),
    )


@pytest.fixture
def materials(content_store) -> MaterialStore:
    return content_store[0]


@pytest.fixture
def questions(content_store) -> QuestionStore:
    return content_store[1]


def seed_material(materials: MaterialStore, material_id: str = "m1") -> Material:
    material = make_material(material_id)
    materials.add(material)
    return material


def test_concrete_stores_satisfy_protocols(materials, questions):
    assert isinstance(materials, MaterialStore)
    assert isinstance(questions, QuestionStore)


# ============================================================================ Material


def test_material_store_appends_reads_and_rejects_duplicates(materials):
    m = seed_material(materials)
    materials.add(make_material("other", topic_id="az-900"))
    assert materials.get("m1") == m
    assert materials.exists("m1") and not materials.exists("nope")
    assert materials.list_for_topic(TOPIC) == [m]
    with pytest.raises(DuplicateMaterialError):
        materials.add(make_material("m1"))
    assert materials.get("m1") == m  # rejected duplicate left the original intact


def test_get_unknown_raises(materials, questions):
    with pytest.raises(UnknownMaterialError):
        materials.get("nope")
    with pytest.raises(UnknownQuestionError):
        questions.get("nope")


@pytest.mark.parametrize("field", ["material_id", "topic_id", "title", "source", "body"])
def test_material_rejects_empty_fields(field):
    kwargs = dict(material_id="m1", topic_id=TOPIC, title="T", source="s", body="b", created_at=T0)
    kwargs[field] = ""
    with pytest.raises(InvalidMaterialError):
        Material(**kwargs)


def test_material_and_question_reject_naive_created_at():
    with pytest.raises(InvalidMaterialError):
        make_material("m1", at=datetime(2026, 1, 1))
    with pytest.raises(InvalidQuestionError):
        make_question("q1", "m1", at=datetime(2026, 1, 1))


# ---- ordering: created_at first, id as tie-break, mixed case and punctuation
# ids on purpose - lowercase-only ASCII is the one input class where a
# locale-dependent database and Python's codepoint order happen to agree, so
# a suite using only those would green-light a backend that gets ordering
# wrong. This is exactly why every identifier column carries COLLATE "C" in
# migrations/0002_content.sql: that hole was found in this repository once
# already.


def test_list_for_topic_orders_by_created_at_then_id(materials):
    materials.add(make_material("b-mid", at=day(2)))
    materials.add(make_material("zebra", at=T0))
    materials.add(make_material("Zebra!", at=T0))
    materials.add(make_material("apple", at=T0))
    ids = [m.material_id for m in materials.list_for_topic(TOPIC)]
    assert ids == ["Zebra!", "apple", "zebra", "b-mid"]


# ============================================================================ Question store


def test_add_many_persists_counts_and_rejects_duplicate_ids(materials, questions):
    seed_material(materials)
    q1, q2 = make_question("q1", "m1", at=day(1)), make_question("q2", "m1", at=day(2))
    assert questions.add_many([q1, q2]) == 2
    assert questions.get("q1") == q1 and questions.exists("q2")
    assert questions.count() == questions.count(TOPIC) == 2 and questions.count("az-900") == 0
    with pytest.raises(DuplicateQuestionError):
        questions.add_many([q1])  # already in the store
    with pytest.raises(DuplicateQuestionError):
        questions.add_many([make_question("q3", "m1"), make_question("q3", "m1")])  # within batch
    assert questions.count() == 2  # neither rejected batch wrote anything


def test_list_for_objective_and_for_topic_scope_and_order_correctly(materials, questions):
    seed_material(materials)
    materials.add(make_material("m2", topic_id="az-900"))
    # mixed-case, punctuation-bearing ids on purpose - see the comment above
    # test_list_for_topic_orders_by_created_at_then_id.
    questions.add_many(
        [
            make_question("Q-zeta", "m1", topic_id=TOPIC, objective_id="D1.1"),
            make_question("q_alpha!", "m1", topic_id=TOPIC, objective_id="D1.2"),
            make_question("Q_alpha", "m2", topic_id="az-900", objective_id="D1.1"),
        ]
    )
    assert [q.question_id for q in questions.list_for_objective("D1.1")] == ["Q-zeta", "Q_alpha"]
    ids = [q.question_id for q in questions.list_for_topic(TOPIC)]
    assert ids == sorted(ids) == ["Q-zeta", "q_alpha!"]


def test_question_requires_at_least_two_unique_options_with_correct_key_among_them():
    with pytest.raises(InvalidQuestionError):
        make_question("q1", "m1", options=(("a", "only"),))
    with pytest.raises(InvalidQuestionError):
        make_question("q1", "m1", options=(("a", "1"), ("a", "2")), correct_key="a")
    with pytest.raises(InvalidQuestionError):
        make_question("q1", "m1", options=(("a", "1"), ("b", "2")), correct_key="c")


@pytest.mark.parametrize(
    "field", ["question_id", "topic_id", "objective_id", "stem", "explanation", "material_id"]
)
def test_question_rejects_empty_fields(field):
    kwargs = dict(
        question_id="q1",
        topic_id=TOPIC,
        objective_id="D1.1",
        stem="stem",
        options=(("a", "1"), ("b", "2")),
        correct_key="a",
        explanation="why",
        material_id="m1",
        created_at=T0,
    )
    kwargs[field] = ""
    with pytest.raises(InvalidQuestionError):
        Question(**kwargs)


def test_question_options_round_trip_in_order(materials, questions):
    """Options are stored/read verbatim, in order (SPEC-style contract, not an
    incidental detail: a postgres backend serializing them as JSON has to
    preserve array order, unlike JSON object key order)."""
    seed_material(materials)
    q = make_question("q1", "m1", options=(("c", "third"), ("a", "first"), ("b", "second")))
    questions.add_many([q])
    assert questions.get("q1").options == (("c", "third"), ("a", "first"), ("b", "second"))


# ============================================================================ replace_for_material


def test_replace_for_material_swaps_only_that_materials_questions(materials, questions):
    seed_material(materials, "m1")
    materials.add(make_material("m2"))
    questions.add_many(
        [
            make_question("q1", "m1", at=day(1)),
            make_question("q2", "m1", at=day(2)),
            make_question("other", "m2"),
        ]
    )
    written = questions.replace_for_material("m1", [make_question("q3", "m1", at=day(3))])
    assert written == 1
    assert [q.question_id for q in questions.list_for_topic(TOPIC)] == ["other", "q3"]
    assert not questions.exists("q1") and not questions.exists("q2")


@pytest.mark.parametrize(
    "bad_batch,error",
    [
        # q2 claims material_id "m2" while replacing "m1".
        (lambda: [make_question("q2", "m2")], InvalidQuestionError),
        # "shared" already belongs to m2: reusing it while replacing "m1".
        (lambda: [make_question("shared", "m1")], DuplicateQuestionError),
        # internal duplicate within the replacement batch itself.
        (
            lambda: [make_question("new", "m1"), make_question("new", "m1")],
            DuplicateQuestionError,
        ),
    ],
)
def test_replace_for_material_is_atomic_on_failure(materials, questions, bad_batch, error):
    seed_material(materials, "m1")
    materials.add(make_material("m2"))
    questions.add_many([make_question("q1", "m1"), make_question("shared", "m2")])
    with pytest.raises(error):
        questions.replace_for_material("m1", bad_batch())
    # the old set of "m1" (and everything under "m2") survives untouched.
    assert [q.question_id for q in questions.list_for_topic(TOPIC)] == ["q1", "shared"]
    assert questions.get("shared").material_id == "m2"


# ============================================================================ integrity: ownership and topic


def test_add_many_rejects_orphan_question_and_writes_nothing(materials, questions):
    # "no-such-material" was never added: a question cannot be created for a
    # material that does not exist - it would be unreachable by
    # replace_for_material forever.
    with pytest.raises(UnknownMaterialError):
        questions.add_many([make_question("q1", "no-such-material")])
    assert questions.count() == 0
    assert not questions.exists("q1")


def test_replace_for_material_rejects_unknown_material_and_writes_nothing(materials, questions):
    with pytest.raises(UnknownMaterialError):
        questions.replace_for_material("ghost", [make_question("q1", "ghost")])
    assert questions.count() == 0


def test_add_many_rejects_topic_mismatch_and_writes_nothing(materials, questions):
    seed_material(materials, "m1")  # topic_id is TOPIC ("ai-103")
    with pytest.raises(InvalidQuestionError):
        questions.add_many([make_question("q1", "m1", topic_id="az-900")])
    assert questions.count() == 0


def test_replace_for_material_rejects_topic_mismatch_and_leaves_old_set_intact(materials, questions):
    seed_material(materials, "m1")
    questions.add_many([make_question("q1", "m1")])
    with pytest.raises(InvalidQuestionError):
        questions.replace_for_material("m1", [make_question("q2", "m1", topic_id="az-900")])
    assert [q.question_id for q in questions.list_for_topic(TOPIC)] == ["q1"]
    assert not questions.exists("q2")
