"""Tests of store/ against SPEC.md section 9.1, section 6 (I1, I2, I6, I7, I8) and
section 7 (C4, C9).

Conventions:

* ``spec``: contract of each ``AttemptStore`` / ``ProfileStore`` method and of
  ``SystemClock``.
* ``invariant``: I1 (append-only), I2 (no clock in ``core/``), I6 (rebuild), I7
  (isolation between profiles), I8 (verifiable recording).
* ``edge``: C4 (out-of-order insertion) and C9 (duplicate ``attempt_id``).

The whole suite runs against three backends (memory, JSON and Postgres)
through the ``attempts`` / ``profiles`` fixture: a backend that deviates from
the others fails. Postgres tests skip, with an explicit reason, when no
database is reachable (set ``LEARNING_TRACKER_TEST_DATABASE_URL`` or run
``docker compose up -d postgres``); they never fail silently and never run
against production data, since each test session gets its own throwaway
schema, dropped at the end of the run.
"""

from __future__ import annotations

import ast
import fcntl
import json
import multiprocessing
import os
import pathlib
import threading
import uuid
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
from store.json_store import lock_path_for

try:
    import psycopg

    from migrations.runner import apply_migrations
    from store.postgres import PostgresAttemptStore, PostgresProfileStore
except ImportError:  # pragma: no cover - exercised when the postgres extra is absent
    psycopg = None

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
P1, P2 = "ai-103", "az-900"
O1, O2 = "D1.1-foo", "D1.2-bar"

BACKENDS = ["memory", "json", "postgres"]

# The compose file lets the host port move (5432 is usually taken by another
# project), so the default DSN has to follow it. Otherwise the normal case
# becomes "forgot the second variable, tests skipped, suite green".
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DSN = os.environ.get(
    "LEARNING_TRACKER_TEST_DATABASE_URL",
    f"postgresql://learning_tracker:learning_tracker@localhost:{POSTGRES_PORT}"
    "/learning_tracker",
)
POSTGRES_SCHEMA = f"learning_test_{uuid.uuid4().hex[:8]}"


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
    """Empties the throwaway schema so tests do not leak state into each other."""
    with psycopg.connect(POSTGRES_DSN) as conn:
        conn.execute(
            f"TRUNCATE {POSTGRES_SCHEMA}.attempts, {POSTGRES_SCHEMA}.objectives, "
            f"{POSTGRES_SCHEMA}.profiles CASCADE"
        )
        conn.commit()


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


def _skip_if_postgres_unavailable(backend: str) -> None:
    if backend == "postgres" and not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)


@pytest.fixture
def attempts(backend, tmp_path) -> AttemptStore:
    _skip_if_postgres_unavailable(backend)
    if backend == "memory":
        return InMemoryAttemptStore()
    if backend == "postgres":
        _reset_postgres_schema()
        return PostgresAttemptStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    return JsonAttemptStore(tmp_path / "attempts.json")


@pytest.fixture
def profiles(backend, tmp_path) -> ProfileStore:
    _skip_if_postgres_unavailable(backend)
    if backend == "memory":
        return InMemoryProfileStore()
    if backend == "postgres":
        _reset_postgres_schema()
        return PostgresProfileStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
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


# ====================================================================== section 9.1
# The concrete stores satisfy the Protocol types


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
    # `==` on ``Attempt`` (and on the aware ``datetime`` inside it) compares
    # instants, not offsets: the shared contract across backends is "the same
    # instant comes back" (Postgres normalizes to UTC, JSON keeps the literal
    # offset - see the dedicated test right below, which exercises exactly
    # that distinction without branching per backend).
    assert read == a
    assert read.at == a.at


#: What each backend does with the offset it was given, declared rather than
#: defaulted: a new backend has to add its row here, which is the point. Memory
#: and JSON hand back the literal offset; Postgres stores an instant in a
#: ``timestamptz`` and returns it in UTC.
OFFSET_BEHAVIOUR = {
    "memory": "preserved",
    "json": "preserved",
    "postgres": "normalized-to-utc",
}


@pytest.mark.spec
def test_offset_handling_is_the_documented_one_per_backend(attempts, backend):
    """The shared contract is the instant; the offset is each backend's own.

    This is the one test in the suite that branches per backend on purpose. It
    is not a contract test: it characterizes a documented divergence, so that
    memory or JSON silently starting to normalize to UTC would fail. That check
    lived inside ``test_append_preserves_every_field_across_read`` until
    Postgres, which cannot honour it, forced it out of the shared contract
    (ACU-247).
    """
    tz = timezone(timedelta(hours=-5))
    at = datetime(2026, 3, 1, 10, 0, tzinfo=tz)
    attempts.append(P1, make_attempt("a1", at=at))
    (read,) = attempts.list_all(P1)

    # The shared part: every backend owes the same instant, aware.
    assert read.at == at
    assert read.at.tzinfo is not None

    expected = OFFSET_BEHAVIOUR[backend]
    if expected == "preserved":
        assert read.at.utcoffset() == tz.utcoffset(None)
    else:
        assert read.at.utcoffset() == timedelta(0)


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


@pytest.mark.edge
def test_ties_order_by_codepoint_not_by_locale(attempts):
    """The tie-break is codepoint order, and every backend owes the same one.

    All-lowercase ASCII ids hide the failure this guards: a SQL backend orders
    text under the database collation, which typically ignores case and
    punctuation, while Python compares codepoints. Mixed case and punctuation
    are where the two disagree. It matters because ties at the same ``at`` are
    ordinary and ``recent_window`` is a positional sequence: a different order
    is a different score, and can be a different level (SPEC C3, C4, I3).
    """
    ids = ["a1", "A1", "B-2", "b_2", "Z9", "z9", "a-1"]
    for attempt_id in ids:
        attempts.append(P1, make_attempt(attempt_id, at=day(1)))
    assert [a.attempt_id for a in attempts.list_for_objective(P1, O1)] == sorted(ids)
    assert [a.attempt_id for a in attempts.list_all(P1)] == sorted(ids)


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
    # It happened on day 0 but was recorded on day 5: the cut on day 1 includes it.
    attempts.append(P1, make_attempt("late", at=day(0), recorded_at=day(5)))
    # It happened on day 3 but was recorded on day 0: the cut on day 1 excludes it.
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


@pytest.mark.edge
def test_list_profiles_orders_by_codepoint_not_by_locale(profiles):
    """Same collation trap as the attempts, and here it needs no odd input.

    Profile ids are written by hand and mixed case is their normal shape, so
    this is the ordering a locale-dependent backend gets wrong first.
    """
    ids = ["a1", "ai-103", "Az-900", "B1"]
    for profile_id in ids:
        profiles.save_profile(Profile(profile_id=profile_id, name=profile_id))
    assert [p.profile_id for p in profiles.list_profiles()] == sorted(ids)


@pytest.mark.spec
def test_list_profiles_empty(profiles):
    assert profiles.list_profiles() == []


@pytest.mark.spec
def test_list_profiles_matches_get_profile_for_every_profile(profiles):
    """Guards ``_row_to_objective``-style mapping against diverging per method.

    Every field that isn't a default (``weight``, ``domain``, ``tags``) is
    exercised here so a sixth column added to one row-mapping and not the
    other would show up as a mismatch instead of passing silently.
    """
    profiles.save_profile(
        Profile(
            profile_id=P1,
            name="AI-103",
            objectives={
                O1: Objective(
                    objective_id=O1, title="Foo", domain="D1", weight=2.5,
                    tags=("a", "b"),
                ),
            },
        )
    )
    profiles.save_profile(
        Profile(
            profile_id=P2,
            name="AZ-900",
            objectives={
                O2: Objective(objective_id=O2, title="Bar", domain=None, weight=0.5),
            },
        )
    )
    listed = profiles.list_profiles()
    assert listed == [profiles.get_profile(p.profile_id) for p in listed]


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


# ======================================================================== archiving


@pytest.mark.spec
def test_a_saved_profile_starts_unarchived(profiles, profile):
    profiles.save_profile(profile)
    assert profiles.get_profile(P1).archived is False
    assert profiles.list_profiles()[0].archived is False


@pytest.mark.spec
def test_set_archived_persists_and_returns_the_updated_profile(profiles, profile):
    profiles.save_profile(profile)
    returned = profiles.set_archived(P1, True)
    assert returned.archived is True
    assert profiles.get_profile(P1) == returned
    assert profiles.set_archived(P1, False).archived is False
    assert profiles.get_profile(P1).archived is False


@pytest.mark.spec
def test_set_archived_touches_nothing_but_the_flag(profiles, profile):
    """The contract of the method, checked field by field.

    Flipping the flag through ``save_profile`` would rewrite the objective
    catalog, so a backend that implements it that way passes the flag
    assertion above and still loses a concurrent objective upload. Comparing
    the whole profile is what tells the two apart.
    """
    profiles.save_profile(profile)
    archived = profiles.set_archived(P1, True)
    assert archived == Profile(
        profile_id=profile.profile_id,
        name=profile.name,
        objectives=profile.objectives,
        archived=True,
    )
    assert profiles.list_objectives(P1) == [profile.objectives[O1], profile.objectives[O2]]


@pytest.mark.spec
def test_archived_profiles_still_appear_in_list_profiles(profiles, profile):
    """The store answers what exists; hiding is the caller's decision.

    A store that filtered archived profiles out of its own listing would make
    the archive unreachable: there would be no call left that names it.
    """
    profiles.save_profile(profile)
    profiles.save_profile(Profile(profile_id=P2, name="AZ-900"))
    profiles.set_archived(P1, True)
    assert [p.profile_id for p in profiles.list_profiles()] == sorted([P1, P2])


@pytest.mark.spec
def test_set_archived_unknown_profile_raises(profiles):
    with pytest.raises(UnknownProfileError):
        profiles.set_archived("ghost", True)


@pytest.mark.edge
def test_set_archived_is_idempotent(profiles, profile):
    profiles.save_profile(profile)
    first = profiles.set_archived(P1, True)
    assert profiles.set_archived(P1, True) == first


@pytest.mark.edge
def test_upsert_objectives_does_not_unarchive_the_profile(profiles, profile):
    """Guards the merge that rebuilds the profile around the new catalog.

    Rebuilding it from ``profile_id`` and ``name`` alone silently drops every
    other field, and an objective upload against an archived topic would bring
    it back into the listing for no reason anybody asked for.
    """
    profiles.save_profile(profile)
    profiles.set_archived(P1, True)
    profiles.upsert_objectives(P1, [Objective(objective_id="D2.1-baz", title="Baz")])
    assert profiles.get_profile(P1).archived is True


@pytest.mark.spec
def test_save_profile_writes_the_archived_flag_it_is_given(profiles):
    profiles.save_profile(Profile(profile_id=P1, name="AI-103", archived=True))
    assert profiles.get_profile(P1).archived is True


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


# ========================================================================= I1 - append-only


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


# ============================================================== I2 - no clock in core/


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
    """Source without docstrings or comments, so the grep has no false positives."""
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


# ============================================================================ I6 - rebuild


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
    # Derived "cache": it is discarded entirely and recomputed from scratch.
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


# ========================================================================== I7 - isolation


@pytest.mark.invariant
def test_i7_attempts_of_one_profile_do_not_affect_another(attempts):
    as_of = day(12)
    _load_series(attempts, profile_id=P1, prefix="p1-")
    baseline = compute_state(O1, attempts.list_for_objective(P2, O1, until=as_of), as_of)
    assert baseline.total_attempts == 0
    # Same objective_id in another profile, with many hits.
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


# ============================================================ I8 - verifiable recording


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
    # No orphan temporaries: only the JSON and its lock sidecar.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["attempts.json", "attempts.json.lock"]
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


@pytest.mark.edge
def test_json_file_written_before_the_archived_field_still_reads(tmp_path):
    """A file from an older version has no ``archived`` key, and is not broken.

    Every profile in such a file was being studied, because there was no way
    to put one away. Reading the absence as "not archived" is the only reading
    that keeps that true; raising instead would turn an upgrade into data
    loss for whoever runs the JSON backend.
    """
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {"version": 1, "profiles": [{"profile_id": P1, "name": "AI-103", "objectives": []}]}
        ),
        encoding="utf-8",
    )
    assert JsonProfileStore(path).get_profile(P1).archived is False


@pytest.mark.invariant
def test_i8_json_stores_create_parent_directories(tmp_path):
    st = JsonAttemptStore(tmp_path / "nested" / "dir" / "attempts.json")
    st.append(P1, make_attempt("a1"))
    assert st.count(P1) == 1
    ps = JsonProfileStore(tmp_path / "nested" / "profiles.json")
    ps.save_profile(Profile(profile_id=P1, name="x"))
    assert ps.get_profile(P1).name == "x"


# ------------------------------------------------------------ I8 - concurrent writers
# Without a lock, two processes doing read-append-rewrite at the same time can
# overwrite each other: the second ``os.replace`` discards the first one's
# attempt with no exception. The ``<name>.lock`` sidecar (exclusive flock)
# prevents that.

N_PROCS, N_PER_PROC = 8, 5


def _append_many(path: str, worker: int) -> None:
    """Body of each child process: N_PER_PROC appends with its own ids."""
    st = JsonAttemptStore(path)
    for i in range(N_PER_PROC):
        st.append(P1, make_attempt(f"w{worker}-{i}", at=day(i)))


def _hold_lock(path: str, held, release) -> None:
    """Takes the sidecar flock the way another writer would and holds it."""
    fd = os.open(lock_path_for(pathlib.Path(path)), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    held.set()
    release.wait()
    os.close(fd)


@pytest.mark.invariant
def test_i8_concurrent_processes_do_not_lose_attempts(tmp_path):
    path = tmp_path / "attempts.json"
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_append_many, args=(str(path), w)) for w in range(N_PROCS)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=30)
    assert [proc.exitcode for proc in procs] == [0] * N_PROCS

    st = JsonAttemptStore(path)
    expected = N_PROCS * N_PER_PROC
    assert st.count(P1) == expected
    ids = [a.attempt_id for a in st.list_all(P1)]
    assert len(set(ids)) == expected


@pytest.mark.spec
def test_json_writes_create_lock_sidecar_next_to_file(tmp_path):
    attempts_path = tmp_path / "attempts.json"
    JsonAttemptStore(attempts_path).append(P1, make_attempt("a1"))
    assert lock_path_for(attempts_path) == tmp_path / "attempts.json.lock"
    assert lock_path_for(attempts_path).is_file()
    assert lock_path_for(attempts_path).stat().st_size == 0  # vacío: no lleva datos

    profiles_path = tmp_path / "profiles.json"
    JsonProfileStore(profiles_path).save_profile(Profile(profile_id=P1, name="x"))
    assert (tmp_path / "profiles.json.lock").is_file()

    # The JSON keeps its shape: the sidecar is a separate file.
    document = json.loads(attempts_path.read_text(encoding="utf-8"))
    assert set(document) == {"version", "attempts"}


@pytest.mark.spec
def test_json_writer_waits_for_lock_held_by_another_process(tmp_path):
    path = tmp_path / "attempts.json"
    ctx = multiprocessing.get_context("spawn")
    held, release = ctx.Event(), ctx.Event()
    holder = ctx.Process(target=_hold_lock, args=(str(path), held, release))
    holder.start()
    try:
        assert held.wait(timeout=30)
        errors: list[BaseException] = []

        def write() -> None:
            try:
                JsonAttemptStore(path).append(P1, make_attempt("a1"))
            except BaseException as exc:  # pragma: no cover - solo si el test falla
                errors.append(exc)

        writer = threading.Thread(target=write)
        writer.start()
        writer.join(timeout=0.5)
        assert writer.is_alive()  # espera, no falla ni escribe
        assert not path.exists()
    finally:
        release.set()
        holder.join(timeout=30)
    writer.join(timeout=30)
    assert not writer.is_alive() and errors == []
    assert JsonAttemptStore(path).count(P1) == 1


@pytest.mark.invariant
def test_i8_lock_failure_raises_storage_error(tmp_path, monkeypatch):
    import store.json_store as js

    def boom(*args, **kwargs):
        raise OSError("flock no soportado")

    monkeypatch.setattr(js.fcntl, "flock", boom)
    path = tmp_path / "attempts.json"
    with pytest.raises(StorageError):
        JsonAttemptStore(path).append(P1, make_attempt("a1"))
    assert not path.exists()
    with pytest.raises(StorageError):
        JsonProfileStore(tmp_path / "profiles.json").save_profile(
            Profile(profile_id=P1, name="x")
        )


# ===================================================================== section 7 - edge cases


@pytest.mark.edge
def test_c4_late_insertion_is_legal_and_changes_past_state(attempts):
    attempts.append(P1, make_attempt("d1", at=day(1), correct=False))
    attempts.append(P1, make_attempt("d5", at=day(5), correct=False))
    as_of = day(4)
    before = compute_state(O1, attempts.list_for_objective(P1, O1, until=as_of), as_of)
    # Late insertion of day 3, after day 5, with a later recorded_at.
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


# ================================================= postgres connection provider (ACU-255)


@pytest.mark.spec
@pytest.mark.skipif(psycopg is None, reason="requires the psycopg driver")
def test_failing_connection_provider_raises_storage_error_not_driver_exception():
    def broken():
        raise RuntimeError("no network")

    with pytest.raises(StorageError):
        PostgresAttemptStore(broken).append(P1, make_attempt("a1"))
    with pytest.raises(StorageError):
        PostgresAttemptStore(broken).count(P1)
    with pytest.raises(StorageError):
        PostgresProfileStore(broken).get_profile(P1)


@pytest.mark.spec
@pytest.mark.skipif(psycopg is None, reason="requires the psycopg driver")
def test_provider_that_fails_on_checkout_also_raises_storage_error():
    """Acquisition is two steps and the second one is how a pool really fails.

    The test above covers a provider that raises when it is called. A pool does
    not fail there: describing a checkout always succeeds, and the failure -
    exhaustion, a dead connection - arrives when the connection is actually
    checked out, which is ``__enter__``. Guarding only the call let the failure
    mode that happens in production leak the raw exception straight through
    every method, which is precisely what I8 forbids.
    """

    class ExhaustedPool:
        def __enter__(self):
            raise RuntimeError("pool exhausted")

        def __exit__(self, *exc_info):
            return False

    def checkout_fails():
        return ExhaustedPool()

    attempts = PostgresAttemptStore(checkout_fails)
    profiles = PostgresProfileStore(checkout_fails)
    for call in (
        lambda: attempts.append(P1, make_attempt("a1")),
        lambda: attempts.list_all(P1),
        lambda: attempts.list_for_objective(P1, O1),
        lambda: attempts.count(P1),
        lambda: attempts.exists("a1"),
        lambda: profiles.get_profile(P1),
        lambda: profiles.list_profiles(),
        lambda: profiles.save_profile(Profile(profile_id=P1, name="x")),
    ):
        with pytest.raises(StorageError):
            call()


@pytest.mark.spec
@pytest.mark.skipif(psycopg is None, reason="requires the psycopg driver")
def test_connection_provider_is_invoked_once_per_operation_never_reused():
    if not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)
    _reset_postgres_schema()
    calls: list[object] = []

    def counting_connect():
        conn = psycopg.connect(POSTGRES_DSN)
        calls.append(conn)
        return conn

    store = PostgresAttemptStore(counting_connect, schema=POSTGRES_SCHEMA)
    store.append(P1, make_attempt("a1"))
    store.append(P1, make_attempt("a2", at=day(1)))
    store.count(P1)
    # One connection per operation: the provider ran three times. This
    # provider hands back a plain ``psycopg.Connection`` (its own context
    # manager), so releasing it means closing it — see the pool-style test
    # below for a provider where "released" does not mean "closed".
    assert len(calls) == 3
    assert all(conn.closed for conn in calls)


@pytest.mark.spec
@pytest.mark.skipif(psycopg is None, reason="requires the psycopg driver")
def test_connection_provider_context_manager_is_released_without_closing():
    """Binds Blocking 1: the seam must actually support pooling.

    A pool-style provider returns a context manager whose ``__exit__``
    commits-or-rolls-back and *returns the connection to the pool* — it never
    closes it. If the store called ``.close()`` itself, or only worked with a
    bare ``psycopg.Connection``, this would fail or the connection would come
    back closed. Reusing the same connection across three operations without
    ever closing it, and reading back what was written, is precisely how a
    real pool checkout has to behave.
    """
    if not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)
    _reset_postgres_schema()
    conn = psycopg.connect(POSTGRES_DSN)
    releases: list[bool] = []

    class PoolStyleContext:
        def __enter__(self):
            return conn

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                conn.commit()
            else:
                conn.rollback()
            releases.append(conn.closed)  # released, not closed
            return False

    try:
        store = PostgresAttemptStore(lambda: PoolStyleContext(), schema=POSTGRES_SCHEMA)
        store.append(P1, make_attempt("a1"))
        store.append(P1, make_attempt("a2", at=day(1)))
        assert store.count(P1) == 2
        # Every operation released the connection at the end (the context
        # manager was exited), but never by closing it — a real pool would
        # keep it alive for reuse.
        assert len(releases) == 3
        assert releases == [False, False, False]
        assert not conn.closed
    finally:
        conn.close()


@pytest.mark.spec
@pytest.mark.skipif(psycopg is None, reason="requires the psycopg driver")
def test_list_profiles_invokes_the_connection_provider_once_not_per_profile():
    """Binds Blocking 2: the N+1 fix in ``list_profiles`` itself.

    Reverting ``list_profiles`` to ``[self.get_profile(pid) for pid in ids]``
    makes this provider run once per profile instead of once total, which is
    exactly the connection-per-request cost this ticket exists to remove.
    """
    if not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)
    _reset_postgres_schema()
    calls: list[object] = []

    def counting_connect():
        conn = psycopg.connect(POSTGRES_DSN)
        calls.append(conn)
        return conn

    seeding_store = PostgresProfileStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    for profile_id in (P1, P2, "az-900-2"):
        seeding_store.save_profile(Profile(profile_id=profile_id, name=profile_id))

    store = PostgresProfileStore(counting_connect, schema=POSTGRES_SCHEMA)
    profiles_listed = store.list_profiles()

    assert len(profiles_listed) == 3
    assert len(calls) == 1


@pytest.mark.spec
@pytest.mark.skipif(psycopg is None, reason="requires the psycopg driver")
def test_from_dsn_is_equivalent_to_an_injected_provider():
    if not POSTGRES_AVAILABLE:
        pytest.skip(_SKIP_REASON)
    _reset_postgres_schema()
    injected = PostgresAttemptStore(lambda: psycopg.connect(POSTGRES_DSN), schema=POSTGRES_SCHEMA)
    from_dsn = PostgresAttemptStore.from_dsn(POSTGRES_DSN, schema=POSTGRES_SCHEMA)
    injected.append(P1, make_attempt("a1"))
    assert from_dsn.list_all(P1) == injected.list_all(P1)
