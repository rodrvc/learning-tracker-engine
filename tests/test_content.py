"""Tests of ``content/`` against the guarantees of ``content/storage.py``.

Scope of this delivery (ACU-245): the in-memory backend only - a ``postgres``
backend does not fit this change's line budget alongside a fully documented
memory backend (see the pull request description). Written through the
``materials`` / ``questions`` fixtures so a future ``postgres`` fixture needs
no per-test changes.
"""

from __future__ import annotations

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
from content.memory import InMemoryMaterialStore, InMemoryQuestionStore
from content.models import Material, Question
from content.storage import MaterialStore, QuestionStore

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
TOPIC = "ai-103"

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

@pytest.fixture
def materials() -> MaterialStore:
    return InMemoryMaterialStore()

@pytest.fixture
def questions() -> QuestionStore:
    return InMemoryQuestionStore()

def seed_material(materials: MaterialStore, material_id: str = "m1") -> Material:
    material = make_material(material_id)
    materials.add(material)
    return material

def test_concrete_stores_satisfy_protocols(materials, questions):
    assert isinstance(materials, MaterialStore)
    assert isinstance(questions, QuestionStore)

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
# it would hide a backend that gets this wrong (relevant once a postgres
# backend lands, under COLLATE "C" as the engine's own tables do).

def test_list_for_topic_orders_by_created_at_then_id(materials):
    materials.add(make_material("b-mid", at=day(2)))
    materials.add(make_material("zebra", at=T0))
    materials.add(make_material("Zebra!", at=T0))
    materials.add(make_material("apple", at=T0))
    ids = [m.material_id for m in materials.list_for_topic(TOPIC)]
    assert ids == ["Zebra!", "apple", "zebra", "b-mid"]

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
