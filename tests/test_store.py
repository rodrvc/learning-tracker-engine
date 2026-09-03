"""Tests de store/ contra SPEC.md §9.1, §6 (I1, I2, I6, I7, I8) y §7 (C4, C9).

Convenciones:

* ``spec``: contrato de cada método de ``AttemptStore`` / ``ProfileStore`` y
  de ``SystemClock``.
* ``invariant``: I1 (append-only), I2 (sin reloj en ``core/``), I6
  (reconstrucción), I7 (aislamiento entre perfiles), I8 (registro verificable).
* ``edge``: C4 (inserción fuera de orden) y C9 (``attempt_id`` duplicado).

Toda la suite corre contra los dos backends (memoria y JSON) mediante la
fixture ``attempts`` / ``profiles``: un backend que se desvíe del otro falla.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import core
import core.clock
import core.storage
import store
from core.errors import (
    DuplicateAttemptError,
    InvalidAttemptError,
    StorageError,
    UnknownObjectiveError,
    UnknownProfileError,
)
from core.leveling import compute_state
from core.models import Attempt, AttemptKind, Objective, Profile
from core.storage import AttemptStore, ProfileStore
from store import (
    InMemoryAttemptStore,
    InMemoryProfileStore,
    JsonAttemptStore,
    JsonProfileStore,
    SystemClock,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
P1, P2 = "ai-103", "az-900"
O1, O2 = "D1.1-foo", "D1.2-bar"

BACKENDS = ["memory", "json"]


def day(n: int) -> datetime:
    return T0 + timedelta(days=n)


def make_attempt(
    attempt_id: str,
    objective_id: str = O1,
    at: datetime = T0,
    correct: bool = True,
    **kw,
) -> Attempt:
    return Attempt(
        attempt_id=attempt_id, objective_id=objective_id, at=at, correct=correct, **kw
    )


@pytest.fixture(params=BACKENDS)
def backend(request) -> str:
    return request.param


@pytest.fixture
def attempts(backend, tmp_path) -> AttemptStore:
    if backend == "memory":
        return InMemoryAttemptStore()
    return JsonAttemptStore(tmp_path / "attempts.json")


@pytest.fixture
def profiles(backend, tmp_path) -> ProfileStore:
    if backend == "memory":
        return InMemoryProfileStore()
    return JsonProfileStore(tmp_path / "profiles.json")


@pytest.fixture
def profile() -> Profile:
    return Profile(
        profile_id=P1,
        name="AI-103",
        objectives={
            O1: Objective(objective_id=O1, title="Foo", domain="D1", tags=("a",)),
            O2: Objective(objective_id=O2, title="Bar", domain="D1", weight=2.0),
        },
    )


# =========================================================================== §9.1
# Los stores concretos cumplen los Protocol


@pytest.mark.spec
def test_concrete_stores_satisfy_protocols(attempts, profiles):
    assert isinstance(attempts, AttemptStore)
    assert isinstance(profiles, ProfileStore)


# =========================================================================== append


@pytest.mark.spec
def test_append_returns_the_persisted_attempt_and_makes_it_readable(attempts):
    a = make_attempt("a1", confidence=0.5, note="hola", kind=AttemptKind.LAB,
                     recorded_at=day(9))
    returned = attempts.append(P1, a)
    assert returned == a
    assert attempts.exists("a1")
    assert attempts.list_for_objective(P1, O1) == [a]
    assert attempts.count(P1) == 1


@pytest.mark.spec
def test_append_preserves_every_field_across_read(attempts):
    a = make_attempt(
        "a1",
        at=datetime(2026, 3, 4, 5, 6, 7, 123456, tzinfo=timezone(timedelta(hours=-3))),
        correct=False,
        kind=AttemptKind.EXAM_SIM,
        confidence=0.25,
        note="ñandú / unicode ✓",
        recorded_at=day(2),
    )
    attempts.append(P1, a)
    (read,) = attempts.list_all(P1)
    assert read == a
    assert read.at == a.at and read.at.utcoffset() == a.at.utcoffset()


@pytest.mark.spec
def test_append_rejects_naive_at(attempts):
    with pytest.raises(InvalidAttemptError):
        attempts.append(P1, make_attempt("a1", at=datetime(2026, 1, 1)))
    assert attempts.count(P1) == 0
    assert not attempts.exists("a1")


@pytest.mark.spec
@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_append_rejects_confidence_out_of_range(attempts, confidence):
    with pytest.raises(InvalidAttemptError):
        attempts.append(P1, make_attempt("a1", confidence=confidence))
    assert attempts.count(P1) == 0


@pytest.mark.spec
@pytest.mark.parametrize("field", ["attempt_id", "objective_id"])
def test_append_rejects_empty_ids(attempts, field):
    kwargs = {"attempt_id": "a1", "objective_id": O1, field: ""}
    with pytest.raises(InvalidAttemptError):
        attempts.append(P1, Attempt(at=T0, correct=True, **kwargs))


@pytest.mark.spec
def test_append_rejects_empty_profile_id(attempts):
    with pytest.raises(InvalidAttemptError):
        attempts.append("", make_attempt("a1"))


# =========================================================================== list_*


@pytest.mark.spec
def test_list_for_objective_orders_by_at_then_attempt_id(attempts):
    attempts.append(P1, make_attempt("b", at=day(2)))
    attempts.append(P1, make_attempt("z", at=day(1)))
    attempts.append(P1, make_attempt("a", at=day(1)))
    attempts.append(P1, make_attempt("c", at=day(0)))
    ids = [a.attempt_id for a in attempts.list_for_objective(P1, O1)]
    assert ids == ["c", "a", "z", "b"]


@pytest.mark.spec
def test_list_for_objective_filters_by_objective(attempts):
    attempts.append(P1, make_attempt("a1", objective_id=O1))
    attempts.append(P1, make_attempt("a2", objective_id=O2))
    assert [a.attempt_id for a in attempts.list_for_objective(P1, O1)] == ["a1"]
    assert [a.attempt_id for a in attempts.list_for_objective(P1, O2)] == ["a2"]
    assert attempts.list_for_objective(P1, "no-such") == []


@pytest.mark.spec
def test_list_for_objective_until_is_inclusive_and_cuts_by_at(attempts):
    attempts.append(P1, make_attempt("a0", at=day(0)))
    attempts.append(P1, make_attempt("a1", at=day(1)))
    attempts.append(P1, make_attempt("a2", at=day(2)))
    assert [a.attempt_id for a in attempts.list_for_objective(P1, O1, until=day(1))] == [
        "a0",
        "a1",
    ]
    assert attempts.list_for_objective(P1, O1, until=day(-1)) == []
    assert len(attempts.list_for_objective(P1, O1, until=day(100))) == 3
    assert len(attempts.list_for_objective(P1, O1, until=None)) == 3


@pytest.mark.spec
def test_until_cuts_by_at_never_by_recorded_at(attempts):
    # Ocurrió el día 0 pero se registró el día 5: el corte en el día 1 lo incluye.
    attempts.append(P1, make_attempt("late", at=day(0), recorded_at=day(5)))
    # Ocurrió el día 3 pero se registró el día 0: el corte en el día 1 lo excluye.
    attempts.append(P1, make_attempt("early", at=day(3), recorded_at=day(0)))
    assert [a.attempt_id for a in attempts.list_all(P1, until=day(1))] == ["late"]


@pytest.mark.spec
def test_list_all_returns_every_objective_ordered_with_cut(attempts):
    attempts.append(P1, make_attempt("a2", objective_id=O2, at=day(2)))
    attempts.append(P1, make_attempt("a1", objective_id=O1, at=day(1)))
    attempts.append(P1, make_attempt("a3", objective_id=O1, at=day(3)))
    assert [a.attempt_id for a in attempts.list_all(P1)] == ["a1", "a2", "a3"]
    assert [a.attempt_id for a in attempts.list_all(P1, until=day(2))] == ["a1", "a2"]


@pytest.mark.spec
def test_list_on_empty_store_and_unknown_profile_returns_empty(attempts):
    assert attempts.list_all("nobody") == []
    assert attempts.list_for_objective("nobody", O1) == []
    assert attempts.count("nobody") == 0


# =========================================================================== count / exists


@pytest.mark.spec
def test_count_by_profile_and_by_objective(attempts):
    attempts.append(P1, make_attempt("a1", objective_id=O1))
    attempts.append(P1, make_attempt("a2", objective_id=O1, at=day(1)))
    attempts.append(P1, make_attempt("a3", objective_id=O2))
    attempts.append(P2, make_attempt("b1", objective_id=O1))
    assert attempts.count(P1) == 3
    assert attempts.count(P1, O1) == 2
    assert attempts.count(P1, O2) == 1
    assert attempts.count(P1, "no-such") == 0
    assert attempts.count(P2) == 1


@pytest.mark.spec
def test_count_matches_len_of_list_all(attempts):
    for i in range(7):
        attempts.append(P1, make_attempt(f"a{i}", objective_id=O1 if i % 2 else O2, at=day(i)))
    assert attempts.count(P1) == len(attempts.list_all(P1))
    assert attempts.count(P1, O1) == len(attempts.list_for_objective(P1, O1))


@pytest.mark.spec
def test_exists_is_global_across_profiles(attempts):
    assert not attempts.exists("a1")
    attempts.append(P2, make_attempt("a1"))
    assert attempts.exists("a1")
    assert not attempts.exists("a2")


# =========================================================================== ProfileStore


@pytest.mark.spec
def test_save_and_get_profile_roundtrip(profiles, profile):
    assert profiles.save_profile(profile) == profile
    assert profiles.get_profile(P1) == profile


@pytest.mark.spec
def test_get_profile_unknown_raises(profiles):
    with pytest.raises(UnknownProfileError):
        profiles.get_profile("nope")


@pytest.mark.spec
def test_save_profile_replaces_existing(profiles, profile):
    profiles.save_profile(profile)
    replaced = Profile(profile_id=P1, name="Renombrado", objectives={})
    profiles.save_profile(replaced)
    assert profiles.get_profile(P1) == replaced
    assert profiles.list_objectives(P1) == []


@pytest.mark.spec
def test_list_profiles_sorted_by_id(profiles, profile):
    other = Profile(profile_id=P2, name="AZ-900")
    profiles.save_profile(other)
    profiles.save_profile(profile)
    assert [p.profile_id for p in profiles.list_profiles()] == sorted([P1, P2])
    assert profiles.list_profiles()[0] == profile


@pytest.mark.spec
def test_list_profiles_empty(profiles):
    assert profiles.list_profiles() == []


@pytest.mark.spec
def test_get_objective_and_errors(profiles, profile):
    profiles.save_profile(profile)
    assert profiles.get_objective(P1, O2) == profile.objectives[O2]
    with pytest.raises(UnknownObjectiveError):
        profiles.get_objective(P1, "ghost")
    with pytest.raises(UnknownProfileError):
        profiles.get_objective("ghost", O1)


@pytest.mark.spec
def test_list_objectives_sorted_by_id(profiles):
    profiles.save_profile(
        Profile(
            profile_id=P1,
            name="x",
            objectives={
                "z": Objective(objective_id="z", title="Z"),
                "a": Objective(objective_id="a", title="A"),
                "m": Objective(objective_id="m", title="M"),
            },
        )
    )
    assert [o.objective_id for o in profiles.list_objectives(P1)] == ["a", "m", "z"]
    with pytest.raises(UnknownProfileError):
        profiles.list_objectives("ghost")


@pytest.mark.spec
def test_upsert_objectives_adds_updates_and_counts(profiles, profile):
    profiles.save_profile(profile)
    updated_o1 = Objective(objective_id=O1, title="Foo v2", domain="D9")
    new_o3 = Objective(objective_id="D2.1-baz", title="Baz", tags=("x", "y"))
    written = profiles.upsert_objectives(P1, [updated_o1, new_o3])
    assert written == 2
    listed = profiles.list_objectives(P1)
    assert [o.objective_id for o in listed] == sorted([O1, O2, "D2.1-baz"])
    assert profiles.get_objective(P1, O1) == updated_o1
    assert profiles.get_objective(P1, O2) == profile.objectives[O2]
    assert profiles.get_objective(P1, "D2.1-baz") == new_o3
    assert profiles.get_profile(P1).name == profile.name


@pytest.mark.spec
def test_upsert_objectives_empty_iterable_writes_nothing(profiles, profile):
    profiles.save_profile(profile)
    assert profiles.upsert_objectives(P1, []) == 0
    assert profiles.get_profile(P1) == profile


@pytest.mark.spec
def test_upsert_objectives_unknown_profile_raises(profiles):
    with pytest.raises(UnknownProfileError):
        profiles.upsert_objectives("ghost", [Objective(objective_id="a", title="A")])


@pytest.mark.spec
def test_upsert_does_not_mutate_the_frozen_profile_passed_in(profiles, profile):
    profiles.save_profile(profile)
    profiles.upsert_objectives(P1, [Objective(objective_id="new", title="N")])
    assert "new" not in profile.objectives


# =========================================================================== SystemClock


@pytest.mark.spec
def test_system_clock_returns_aware_utc_now():
    clock = SystemClock()
    before = datetime.now(UTC)
    now = clock.now()
    after = datetime.now(UTC)
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    assert before <= now <= after


@pytest.mark.spec
def test_system_clock_honours_tz():
    tz = timezone(timedelta(hours=-4))
    now = SystemClock(tz=tz).now()
    assert now.utcoffset() == timedelta(hours=-4)


@pytest.mark.spec
def test_system_clock_is_a_clock():
    assert isinstance(SystemClock(), core.clock.Clock)


@pytest.mark.spec
def test_system_clock_rejects_naive():
    with pytest.raises(ValueError):
        SystemClock(tz=None)  # type: ignore[arg-type]


# =========================================================================== I1 — append-only


FORBIDDEN_METHOD_FRAGMENTS = ("update", "delete", "remove", "clear", "pop", "edit", "replace", "set")


@pytest.mark.invariant
def test_i1_attempt_store_protocol_has_no_mutation_methods():
    names = [n for n in vars(AttemptStore) if not n.startswith("_")]
    assert set(names) == {"append", "list_for_objective", "list_all", "count", "exists"}


@pytest.mark.invariant
@pytest.mark.parametrize("cls", [InMemoryAttemptStore, JsonAttemptStore])
def test_i1_concrete_attempt_stores_expose_no_update_or_delete(cls):
    public = {n for n in dir(cls) if not n.startswith("_")}
    assert public == {"append", "list_for_objective", "list_all", "count", "exists"} | (
        {"path", "ROOT_KEY"} if cls is JsonAttemptStore else set()
    )
    for name in public:
        assert not any(frag in name.lower() for frag in FORBIDDEN_METHOD_FRAGMENTS), name


@pytest.mark.invariant
def test_i1_append_cannot_replace_an_existing_attempt(attempts):
    original = make_attempt("a1", correct=False, note="v1")
    attempts.append(P1, original)
    tampered = make_attempt("a1", correct=True, note="v2", at=day(3))
    with pytest.raises(DuplicateAttemptError):
        attempts.append(P1, tampered)
    with pytest.raises(DuplicateAttemptError):
        attempts.append(P2, tampered)  # ni siquiera bajo otro perfil
    assert attempts.list_all(P1) == [original]
    assert attempts.count(P1) == 1
    assert attempts.count(P2) == 0


@pytest.mark.invariant
def test_i1_returned_lists_are_copies_not_internal_state(attempts):
    attempts.append(P1, make_attempt("a1"))
    listed = attempts.list_all(P1)
    listed.clear()
    assert attempts.count(P1) == 1
    assert len(attempts.list_all(P1)) == 1


# =========================================================================== I2 — sin reloj en core/


CORE_DIR = pathlib.Path(core.__file__).parent
FORBIDDEN_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("date", "today"),
    ("time", "time"),
    ("time", "monotonic"),
}
FORBIDDEN_TEXT = ("datetime.now(", "date.today(", "utcnow(", "time.time(")


def _code_only(path: pathlib.Path) -> str:
    """Fuente sin docstrings ni comentarios, para que el grep no tenga falsos positivos."""
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


@pytest.mark.invariant
def test_i2_no_file_under_core_calls_the_system_clock():
    offenders: list[str] = []
    for path in sorted(CORE_DIR.rglob("*.py")):
        code = _code_only(path)
        for fragment in FORBIDDEN_TEXT:
            if fragment in code:
                offenders.append(f"{path.name}: {fragment}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = node.func.value
                base_name = base.id if isinstance(base, ast.Name) else None
                if (base_name, node.func.attr) in FORBIDDEN_CALLS:
                    offenders.append(f"{path.name}:{node.lineno}: {base_name}.{node.func.attr}()")
    assert offenders == []


@pytest.mark.invariant
def test_i2_core_does_not_import_or_define_system_clock():
    for path in sorted(CORE_DIR.rglob("*.py")):
        assert "SystemClock" not in _code_only(path), path.name
        assert "import store" not in _code_only(path), path.name


@pytest.mark.invariant
def test_i2_system_clock_lives_in_store_and_is_importable():
    assert store.SystemClock is SystemClock
    assert SystemClock.__module__.split(".")[0] == "store"
    assert not hasattr(core.clock, "SystemClock")


# =========================================================================== I6 — reconstrucción


SERIES = [False, False, False, True, False, True, True, True, True, True]


def _load_series(attempts, profile_id=P1, objective_id=O1, prefix="s"):
    for i, correct in enumerate(SERIES):
        attempts.append(
            profile_id,
            make_attempt(f"{prefix}{i}", objective_id=objective_id, at=day(i), correct=correct),
        )


@pytest.mark.invariant
def test_i6_state_recomputed_from_store_is_identical_after_dropping_derived_state(attempts):
    _load_series(attempts)
    as_of = day(12)
    cache = {(P1, O1, as_of): compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)}
    snapshot = cache[(P1, O1, as_of)]
    # "Caché" derivada: se descarta por completo y se recalcula desde cero.
    cache.clear()
    rebuilt = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    assert rebuilt == snapshot
    assert rebuilt.total_attempts == len(SERIES)


@pytest.mark.invariant
def test_i6_json_state_survives_process_boundary_and_is_identical(tmp_path):
    path = tmp_path / "attempts.json"
    writer = JsonAttemptStore(path)
    _load_series(writer)
    as_of = day(12)
    expected = compute_state(O1, writer.list_for_objective(P1, O1, until=as_of), as_of)
    del writer  # nada en memoria: el archivo es el único estado
    reader = JsonAttemptStore(path)
    assert compute_state(O1, reader.list_for_objective(P1, O1, until=as_of), as_of) == expected
    assert reader.count(P1, O1) == len(SERIES)


@pytest.mark.invariant
def test_i6_memory_and_json_backends_yield_identical_state(tmp_path):
    mem = InMemoryAttemptStore()
    js = JsonAttemptStore(tmp_path / "a.json")
    _load_series(mem)
    _load_series(js)
    for n in (0, 3, 5, 9, 30):
        as_of = day(n) + timedelta(hours=1)
        s_mem = compute_state(O1, mem.list_for_objective(P1, O1, until=as_of), as_of)
        s_js = compute_state(O1, js.list_for_objective(P1, O1, until=as_of), as_of)
        assert s_mem == s_js


@pytest.mark.invariant
def test_i6_state_is_independent_of_insertion_order(attempts, backend, tmp_path):
    other = InMemoryAttemptStore() if backend == "memory" else JsonAttemptStore(tmp_path / "b.json")
    rows = [make_attempt(f"s{i}", at=day(i), correct=c) for i, c in enumerate(SERIES)]
    for a in rows:
        attempts.append(P1, a)
    for a in reversed(rows):
        other.append(P1, a)
    as_of = day(20)
    assert attempts.list_for_objective(P1, O1) == other.list_for_objective(P1, O1)
    assert compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of) == compute_state(
        O1, other.list_for_objective(P1, O1, until=as_of), as_of
    )


# =========================================================================== I7 — aislamiento


@pytest.mark.invariant
def test_i7_attempts_of_one_profile_do_not_affect_another(attempts):
    as_of = day(12)
    _load_series(attempts, profile_id=P1, prefix="p1-")
    baseline = compute_state(O1, attempts.list_for_objective(P2, O1, until=as_of), as_of)
    assert baseline.total_attempts == 0
    # Mismo objective_id en otro perfil, con muchos aciertos.
    for i in range(10):
        attempts.append(P2, make_attempt(f"p2-{i}", objective_id=O1, at=day(i), correct=True))
    p1_state = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    p1_alone = InMemoryAttemptStore()
    _load_series(p1_alone, profile_id=P1, prefix="p1-")
    assert p1_state == compute_state(O1, p1_alone.list_for_objective(P1, O1, until=as_of), as_of)
    assert attempts.count(P1) == len(SERIES)
    assert attempts.count(P2) == 10
    assert {a.attempt_id[:3] for a in attempts.list_all(P1)} == {"p1-"}
    assert {a.attempt_id[:3] for a in attempts.list_all(P2)} == {"p2-"}


@pytest.mark.invariant
def test_i7_attempts_of_one_objective_do_not_affect_another(attempts):
    as_of = day(12)
    _load_series(attempts, objective_id=O1, prefix="o1-")
    before = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    for i in range(10):
        attempts.append(P1, make_attempt(f"o2-{i}", objective_id=O2, at=day(i), correct=True))
    after = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    assert after == before
    assert attempts.count(P1, O1) == len(SERIES)
    assert attempts.count(P1, O2) == 10


@pytest.mark.invariant
def test_i7_profile_store_isolation(profiles, profile):
    profiles.save_profile(profile)
    profiles.save_profile(Profile(profile_id=P2, name="other"))
    profiles.upsert_objectives(P2, [Objective(objective_id="only-p2", title="x")])
    assert [o.objective_id for o in profiles.list_objectives(P1)] == sorted([O1, O2])
    with pytest.raises(UnknownObjectiveError):
        profiles.get_objective(P1, "only-p2")


# =========================================================================== I8 — registro verificable


@pytest.mark.invariant
def test_i8_failed_json_write_raises_storage_error_and_leaves_file_intact(tmp_path, monkeypatch):
    path = tmp_path / "attempts.json"
    st = JsonAttemptStore(path)
    st.append(P1, make_attempt("a1"))
    before = path.read_bytes()

    import store.json_store as js

    def boom(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(js.os, "replace", boom)
    with pytest.raises(StorageError):
        st.append(P1, make_attempt("a2", at=day(1)))
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["attempts.json"]  # sin temporales huérfanos
    monkeypatch.undo()
    assert st.count(P1) == 1 and not st.exists("a2")


@pytest.mark.invariant
def test_i8_corrupt_json_file_raises_storage_error(tmp_path):
    path = tmp_path / "attempts.json"
    path.write_text("{not json", encoding="utf-8")
    st = JsonAttemptStore(path)
    with pytest.raises(StorageError):
        st.count(P1)
    with pytest.raises(StorageError):
        st.append(P1, make_attempt("a1"))
    path.write_text('{"version": 1}', encoding="utf-8")
    with pytest.raises(StorageError):
        st.list_all(P1)


@pytest.mark.invariant
def test_i8_json_stores_create_parent_directories(tmp_path):
    st = JsonAttemptStore(tmp_path / "nested" / "dir" / "attempts.json")
    st.append(P1, make_attempt("a1"))
    assert st.count(P1) == 1
    ps = JsonProfileStore(tmp_path / "nested" / "profiles.json")
    ps.save_profile(Profile(profile_id=P1, name="x"))
    assert ps.get_profile(P1).name == "x"


# =========================================================================== §7 — casos límite


@pytest.mark.edge
def test_c4_late_insertion_is_legal_and_changes_past_state(attempts):
    attempts.append(P1, make_attempt("d1", at=day(1), correct=False))
    attempts.append(P1, make_attempt("d5", at=day(5), correct=False))
    as_of = day(4)
    before = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    # Inserción tardía del día 3, después del día 5, con recorded_at posterior.
    attempts.append(P1, make_attempt("d3", at=day(3), correct=False, recorded_at=day(9)))
    after = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    assert [a.attempt_id for a in attempts.list_for_objective(P1, O1)] == ["d1", "d3", "d5"]
    assert before.total_attempts == 1 and after.total_attempts == 2
    assert after != before


@pytest.mark.edge
def test_c9_duplicate_attempt_id_raises_and_does_not_duplicate_evidence(attempts):
    a = make_attempt("dup")
    attempts.append(P1, a)
    with pytest.raises(DuplicateAttemptError):
        attempts.append(P1, a)  # reintento idéntico
    with pytest.raises(DuplicateAttemptError):
        attempts.append(P1, make_attempt("dup", objective_id=O2, at=day(4)))
    with pytest.raises(DuplicateAttemptError):
        attempts.append(P2, make_attempt("dup"))  # otro perfil, mismo id
    assert attempts.count(P1) == 1
    assert attempts.count(P2) == 0
    assert attempts.list_all(P1) == [a]


@pytest.mark.edge
def test_c9_duplicate_is_detected_across_json_instances(tmp_path):
    path = tmp_path / "attempts.json"
    JsonAttemptStore(path).append(P1, make_attempt("dup"))
    with pytest.raises(DuplicateAttemptError):
        JsonAttemptStore(path).append(P1, make_attempt("dup"))
    assert JsonAttemptStore(path).count(P1) == 1


@pytest.mark.edge
def test_c9_duplicate_error_is_a_tracker_error(attempts):
    from core.errors import TrackerError

    attempts.append(P1, make_attempt("dup"))
    with pytest.raises(TrackerError):
        attempts.append(P1, make_attempt("dup"))
