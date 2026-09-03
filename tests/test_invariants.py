"""La red de seguridad: SPEC.md §6 (invariantes I1-I10) y §8 (los cinco fallos).

Cada invariante tiene **un** test (``test_i1_`` .. ``test_i10_``) y cada fallo
conocido tiene el test que lo reproduciría si volviera (``test_fallo1_`` ..
``test_fallo5_``). Todos llevan el marker ``invariant``.

A diferencia de las suites por módulo, aquí se verifica la **visión de
conjunto** y siempre desde fuera: por la API pública de
:class:`~core.tracker.LearningTracker`, por introspección de la API o por
análisis estático del código fuente de ``core/``. No se duplican los tests de
detalle de ``test_tracker.py`` / ``test_leveling.py``: si una invariante falla
aquí, la spec está rota aunque cada pieza pase su suite.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import itertools
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import core
from core.clock import FixedClock, OffsetClock
from core.errors import StorageError
from core.leveling import compute_state
from core.models import Attempt, Level, Objective, ObjectiveState, Profile
from core.storage import AttemptStore
from core.tracker import LearningTracker
from store import (
    InMemoryAttemptStore,
    InMemoryProfileStore,
    JsonAttemptStore,
    JsonProfileStore,
)

pytestmark = pytest.mark.invariant

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
PID = "ai-103"
PID_B = "az-900"
O1, O2, O3 = "D1.1-a", "D1.2-b", "D2.1-c"
ALL_OBJECTIVES = (O1, O2, O3)

CORE_DIR = Path(core.__file__).resolve().parent

#: Historial de referencia: la serie de SPEC §3 más dos aciertos.
HISTORY = (False, False, False, True, False, True, True)


def d(n: float) -> datetime:
    """``T0 + n`` días."""
    return T0 + DAY * n


def make_profile(profile_id: str = PID) -> Profile:
    return Profile(
        profile_id=profile_id,
        name=profile_id,
        objectives={o: Objective(objective_id=o, title=o) for o in ALL_OBJECTIVES},
    )


def new_tracker(
    profile_id: str = PID,
    clock: FixedClock | OffsetClock | None = None,
    profiles: InMemoryProfileStore | JsonProfileStore | None = None,
    attempts: AttemptStore | None = None,
) -> LearningTracker:
    """Tracker sobre stores nuevos (o los dados), con el perfil ya guardado."""
    if profiles is None:
        profiles = InMemoryProfileStore()
    try:
        profiles.get_profile(profile_id)
    except Exception:
        profiles.save_profile(make_profile(profile_id))
    if attempts is None:
        attempts = InMemoryAttemptStore()
    return LearningTracker(profile_id, profiles, attempts, clock or FixedClock(d(30)))


def facts(
    results: tuple[bool, ...],
    objective_id: str = O1,
    start: int = 0,
    prefix: str = "",
) -> list[tuple[str, bool, datetime]]:
    """Hechos ``(attempt_id, correct, at)`` para registrar en cualquier orden.

    El ``attempt_id`` va fijado para que el desempate de orden (SPEC C4) no
    dependa de un uuid distinto en cada tracker. ``prefix`` evita colisiones
    de id entre perfiles que comparten store (SPEC C9: el id es global).
    """
    return [
        (f"{prefix}{objective_id}-{i:02d}", ok, d(start + i))
        for i, ok in enumerate(results)
    ]


def record_facts(
    tracker: LearningTracker,
    rows: list[tuple[str, bool, datetime]],
    objective_id: str = O1,
) -> None:
    for attempt_id, ok, at in rows:
        tracker.record_attempt(objective_id, correct=ok, at=at, attempt_id=attempt_id)


# ---------------------------------------------------------------------- I1


def _public_names(obj: object) -> set[str]:
    return {name for name in dir(obj) if not name.startswith("_")}


_MUTATING_FRAGMENTS = ("update", "delete", "remove", "clear", "pop", "edit", "set_")


def test_i1_append_only_no_mutating_api_and_attempt_frozen(tmp_path):
    """I1: ni el tracker ni los stores exponen forma de tocar un Attempt."""
    surfaces = {
        "LearningTracker": LearningTracker,
        "AttemptStore": AttemptStore,
        "InMemoryAttemptStore": InMemoryAttemptStore,
        "JsonAttemptStore": JsonAttemptStore,
    }
    for label, surface in surfaces.items():
        names = _public_names(surface)
        offenders = {
            n for n in names if any(frag in n.lower() for frag in _MUTATING_FRAGMENTS)
        }
        assert not offenders, f"{label} expone API mutadora: {sorted(offenders)}"
        assert "update_attempt" not in names and "delete_attempt" not in names

    # La instancia tampoco (atributos añadidos en __init__).
    tracker = new_tracker(attempts=JsonAttemptStore(tmp_path / "a.json"))
    for instance in (tracker, tracker._attempts):  # noqa: SLF001 - introspección
        offenders = {
            n
            for n in _public_names(instance)
            if any(frag in n.lower() for frag in _MUTATING_FRAGMENTS)
        }
        assert not offenders, offenders

    # El Protocol solo declara escritura por append.
    protocol_methods = {
        n for n, v in inspect.getmembers(AttemptStore) if not n.startswith("_") and callable(v)
    }
    assert protocol_methods == {"append", "list_for_objective", "list_all", "count", "exists"}

    # Attempt es inmutable por construcción.
    written = tracker.record_attempt(O1, correct=True, at=d(0))
    assert dataclasses.is_dataclass(written) and type(written).__dataclass_params__.frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        written.correct = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del written.at  # type: ignore[attr-defined]
    assert tracker._attempts.list_all(PID) == [written]  # noqa: SLF001


# ---------------------------------------------------------------------- I2


_FORBIDDEN_CALLS = {
    ("datetime", "now"),
    ("datetime", "today"),
    ("datetime", "utcnow"),
    ("date", "today"),
    ("time", "time"),
    ("time", "monotonic"),
    ("time", "perf_counter"),
}


def _clock_calls(source: str) -> list[tuple[int, str]]:
    """Llamadas ``X.y(...)`` prohibidas en CODIGO (el AST ignora docstrings y
    comentarios por construcción)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            base = func.value
            base_name = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None
            )
            if (base_name, func.attr) in _FORBIDDEN_CALLS:
                found.append((node.lineno, f"{base_name}.{func.attr}("))
        elif isinstance(func, ast.Name) and func.id in {"utcnow", "today"}:
            found.append((node.lineno, f"{func.id}("))
    return found


def test_i2_core_has_no_internal_clock():
    """I2: cero llamadas al reloj real en core/ y SystemClock no vive ahí."""
    # El escáner detecta código y deja pasar docstrings/comentarios.
    assert _clock_calls("x = datetime.now(tz)\ny = time.time()") == [
        (1, "datetime.now("),
        (2, "time.time("),
    ]
    assert _clock_calls('"""usa datetime.now()"""\n# time.time()\nz = 1') == []

    py_files = sorted(CORE_DIR.glob("*.py"))
    assert len(py_files) >= 9, py_files
    violations: dict[str, list[tuple[int, str]]] = {}
    for path in py_files:
        calls = _clock_calls(path.read_text(encoding="utf-8"))
        if calls:
            violations[path.name] = calls
    assert not violations, f"core/ consulta el reloj: {violations}"

    # Ningún módulo de core/ importa el módulo `time` siquiera.
    for path in py_files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(a.name != "time" for a in node.names), path.name
            if isinstance(node, ast.ImportFrom):
                assert node.module != "time", path.name

    # SystemClock no es importable desde core ni desde ningún submódulo.
    assert not hasattr(core, "SystemClock")
    assert "SystemClock" not in core.__all__
    for path in py_files:
        module = importlib.import_module(f"core.{path.stem}")
        assert not hasattr(module, "SystemClock"), path.name
    with pytest.raises(ImportError):
        from core import SystemClock  # noqa: F401
    with pytest.raises(ImportError):
        from core.clock import SystemClock  # noqa: F401,F811


# ---------------------------------------------------------------------- I3


def test_i3_determinism_across_insertion_orders():
    """I3: cualquier permutación del mismo historial da un estado idéntico."""
    as_of = d(30)
    base_rows = facts(HISTORY)  # 7 intentos -> 5040 permutaciones
    reference = None
    for permutation in itertools.permutations(base_rows):
        tracker = new_tracker()
        record_facts(tracker, list(permutation))
        state = tracker.get_state(O1, as_of)
        if reference is None:
            reference = state
        assert state == reference, permutation
    assert reference is not None and reference.total_attempts == len(HISTORY)

    # Uno de 20 intentos, con barajado aleatorio de semilla fija.
    long_history = tuple(i % 3 != 0 for i in range(20))
    long_rows = facts(long_history, objective_id=O2)
    rng = random.Random(20260903)
    long_reference = None
    for _ in range(25):
        shuffled = list(long_rows)
        rng.shuffle(shuffled)
        tracker = new_tracker()
        record_facts(tracker, shuffled, objective_id=O2)
        state = tracker.get_state(O2, as_of)
        if long_reference is None:
            long_reference = state
        assert state == long_reference
    assert long_reference is not None and long_reference.total_attempts == 20


# ---------------------------------------------------------------------- I4


def test_i4_state_is_pure_function_of_attempts_and_as_of():
    """I4: get_state == compute_state campo a campo, y nada más lo altera."""
    as_of = d(30)
    tracker = new_tracker(clock=FixedClock(d(10)))
    record_facts(tracker, facts(HISTORY))
    via_tracker = tracker.get_state(O1, as_of)
    history = tracker._attempts.list_for_objective(PID, O1, until=as_of)  # noqa: SLF001
    via_pure = compute_state(O1, history, as_of)
    assert via_tracker == via_pure
    for field in dataclasses.fields(ObjectiveState):
        assert getattr(via_tracker, field.name) == getattr(via_pure, field.name), field.name

    # Mismo historial, distinto orden de inserción y distinto recorded_at
    # (relojes distintos): ningún campo del estado cambia.
    other = new_tracker(clock=FixedClock(d(500)))
    record_facts(other, list(reversed(facts(HISTORY))))
    assert other.get_state(O1, as_of) == via_tracker
    recorded = {a.recorded_at for a in tracker._attempts.list_all(PID)}  # noqa: SLF001
    recorded_other = {a.recorded_at for a in other._attempts.list_all(PID)}  # noqa: SLF001
    assert recorded.isdisjoint(recorded_other), "el experimento exige recorded_at distintos"

    # as_of es la única otra entrada: cambiarlo sí cambia el estado.
    assert tracker.get_state(O1, d(31)) != via_tracker


# ---------------------------------------------------------------------- I5


def test_i5_cut_is_monotone_but_level_is_not():
    """I5: t1<=t2 => intentos(t1) ⊆ intentos(t2); el nivel sube y baja."""
    tracker = new_tracker()
    # Sube (aciertos) y luego baja (fallos), en fechas fuera de orden.
    series = (True, True, True, True, False, False, False, False)
    rows = facts(series)
    record_facts(tracker, [rows[5], rows[0], rows[7], rows[2], rows[1], rows[6], rows[3], rows[4]])
    store = tracker._attempts  # noqa: SLF001

    grid = [d(n / 2) for n in range(-2, 20)]  # cada 12 h, incluye antes del primero
    previous: set[str] = set()
    for moment in grid:
        current = {a.attempt_id for a in store.list_for_objective(PID, O1, until=moment)}
        assert previous <= current, moment
        assert current == {
            a.attempt_id for a in store.list_all(PID, until=moment)
        }
        previous = current
    assert previous == {r[0] for r in rows}

    # El conjunto es monótono, el nivel no: alcanza COMPETENT y cae a WEAK.
    timeline = tracker.get_timeline(O1, d(0), d(8))
    levels = [s.level for s in timeline]
    totals = [s.total_attempts for s in timeline]
    assert totals == sorted(totals), "total_attempts debe ser monótono"
    assert Level.COMPETENT in levels
    assert levels[-1] == Level.WEAK
    peak = levels.index(max(levels))
    assert any(l < levels[peak] for l in levels[peak:]), levels


# ---------------------------------------------------------------------- I6


def test_i6_rebuild_from_disk_is_identical(tmp_path):
    """I6: borrar toda instancia y reabrir desde disco da el mismo estado."""
    attempts_path = tmp_path / "attempts.json"
    profiles_path = tmp_path / "profiles.json"
    as_of = d(30)

    tracker = new_tracker(
        profiles=JsonProfileStore(profiles_path),
        attempts=JsonAttemptStore(attempts_path),
    )
    record_facts(tracker, facts(HISTORY))
    record_facts(tracker, facts((True, False, True), objective_id=O2), objective_id=O2)
    before = {o: tracker.get_state(o, as_of) for o in ALL_OBJECTIVES}
    summary_before = tracker.get_summary(as_of)
    assert tracker.rebuild(as_of) == len(ALL_OBJECTIVES)
    assert {o: tracker.get_state(o, as_of) for o in ALL_OBJECTIVES} == before

    del tracker  # se pierde cualquier estado derivado o caché de instancia

    reopened = LearningTracker(
        PID, JsonProfileStore(profiles_path), JsonAttemptStore(attempts_path), FixedClock(d(30))
    )
    assert reopened.rebuild(as_of) == len(ALL_OBJECTIVES)
    after = {o: reopened.get_state(o, as_of) for o in ALL_OBJECTIVES}
    assert after == before
    assert reopened.get_summary(as_of) == summary_before
    assert reopened.check_consistency(as_of).ok is True

    # Y contra el backend en memoria alimentado con los mismos hechos.
    mirror = new_tracker()
    record_facts(mirror, facts(HISTORY))
    record_facts(mirror, facts((True, False, True), objective_id=O2), objective_id=O2)
    assert {o: mirror.get_state(o, as_of) for o in ALL_OBJECTIVES} == before


# ---------------------------------------------------------------------- I7


def test_i7_profiles_are_isolated():
    """I7: los intentos del perfil A no mueven nada del perfil B."""
    profiles = InMemoryProfileStore()
    attempts = InMemoryAttemptStore()
    a = new_tracker(PID, profiles=profiles, attempts=attempts)
    b = new_tracker(PID_B, profiles=profiles, attempts=attempts)
    as_of = d(30)

    record_facts(b, facts((True, True), objective_id=O2, prefix="B-"), objective_id=O2)
    b_states = {o: b.get_state(o, as_of) for o in ALL_OBJECTIVES}
    b_summary = b.get_summary(as_of)
    b_due = b.get_due(as_of)
    b_report = b.check_consistency(as_of)

    # A registra mucho, incluso en los mismos objective_id y fechas.
    record_facts(a, facts(HISTORY))
    record_facts(a, facts((False,) * 6, objective_id=O2), objective_id=O2)
    record_facts(a, facts((True,) * 4, objective_id=O3), objective_id=O3)

    assert {o: b.get_state(o, as_of) for o in ALL_OBJECTIVES} == b_states
    assert b.get_summary(as_of) == b_summary
    assert b.get_due(as_of) == b_due
    assert b.check_consistency(as_of) == b_report
    assert b.get_summary(as_of).total_attempts == 2
    assert a.get_summary(as_of).total_attempts == len(HISTORY) + 6 + 4
    assert attempts.count(PID_B) == 2


# ---------------------------------------------------------------------- I8


class ExplodingAttemptStore(InMemoryAttemptStore):
    """Store cuya escritura falla siempre: simula disco lleno / permisos."""

    def append(self, profile_id: str, attempt: Attempt) -> Attempt:
        raise StorageError("disco lleno")


def test_i8_failed_write_raises_and_leaves_no_trace():
    """I8: si append falla, record_attempt propaga y el conteo no cambia."""
    store = ExplodingAttemptStore()
    tracker = new_tracker(attempts=store)
    tracker_ok = new_tracker()
    written = tracker_ok.record_attempt(O1, correct=True, at=d(0), attempt_id="x1")
    assert isinstance(written, Attempt) and written.attempt_id == "x1"

    before = store.count(PID)
    with pytest.raises(StorageError):
        tracker.record_attempt(O1, correct=True, at=d(0), attempt_id="boom")
    assert store.count(PID) == before == 0
    assert store.exists("boom") is False
    assert tracker.get_state(O1, d(1)).total_attempts == 0

    # La firma no admite "no hice nada": el retorno es Attempt, no Optional.
    hints = inspect.signature(LearningTracker.record_attempt).return_annotation
    assert "Attempt" in str(hints) and "None" not in str(hints)


# ---------------------------------------------------------------------- I9


class LyingCountStore(InMemoryAttemptStore):
    """Mismos ids y mismos conjuntos, pero ``count`` miente en uno."""

    def count(self, profile_id: str, objective_id: str | None = None) -> int:
        return super().count(profile_id, objective_id) + 1


class DuplicatingStore(InMemoryAttemptStore):
    """``list_all`` devuelve un intento dos veces: el conjunto de ids no cambia."""

    def list_all(self, profile_id: str, until: datetime | None = None) -> list[Attempt]:
        rows = super().list_all(profile_id, until)
        return rows + rows[:1] if rows else rows


def test_i9_consistency_compares_counts_not_sets():
    """I9: un store que conserva los conjuntos pero altera conteos se detecta."""
    as_of = d(30)
    honest = new_tracker()
    record_facts(honest, facts(HISTORY))
    assert honest.check_consistency(as_of).ok is True

    liar = LyingCountStore()
    tracker = new_tracker(attempts=liar)
    record_facts(tracker, facts(HISTORY))
    ids_via_list = {a.attempt_id for a in liar.list_all(PID)}
    assert ids_via_list == {r[0] for r in facts(HISTORY)}  # el conjunto es el "bueno"
    report = tracker.check_consistency(as_of)
    assert report.ok is False
    names = {c.name for c in report.failures}
    assert "store_count" in names
    for check in report.failures:
        assert check.expected != check.actual
        assert isinstance(check.expected, (int, float)) and isinstance(check.actual, (int, float))

    dup = DuplicatingStore()
    tracker_dup = new_tracker(attempts=dup)
    record_facts(tracker_dup, facts(HISTORY))
    assert {a.attempt_id for a in dup.list_all(PID)} == ids_via_list
    report_dup = tracker_dup.check_consistency(as_of)
    assert report_dup.ok is False
    assert {c.name for c in report_dup.failures} >= {"unique_attempt_ids", "profile_attempt_count"}

    # Un perfil sin objetivos: nada que comprobar no es "ok".
    profiles = InMemoryProfileStore()
    profiles.save_profile(Profile(profile_id="empty", name="empty"))
    empty = LearningTracker("empty", profiles, InMemoryAttemptStore(), FixedClock(d(0)))
    empty_report = empty.check_consistency(as_of)
    assert empty_report.objectives_checked == 0
    assert empty_report.failures == ()
    assert empty_report.ok is False


# ---------------------------------------------------------------------- I10


_STREAK_WORDS = ("streak", "racha")


def _identifiers(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_i10_state_has_no_streak_field():
    """I10: ObjectiveState no expone racha, ni por nombre ni en el modelo."""
    field_names = {f.name for f in dataclasses.fields(ObjectiveState)}
    for name in field_names:
        assert not any(w in name.lower() for w in _STREAK_WORDS), name
    assert not any(any(w in n.lower() for w in _STREAK_WORDS) for n in dir(ObjectiveState))

    tracker = new_tracker()
    record_facts(tracker, facts(HISTORY))
    state = tracker.get_state(O1, d(30))
    assert not hasattr(state, "streak") and not hasattr(state, "racha")
    assert set(dataclasses.asdict(state)) == field_names

    # grep (por AST, sin docstrings ni comentarios) sobre core/models.py.
    models_source = (CORE_DIR / "models.py").read_text(encoding="utf-8")
    offenders = {
        n for n in _identifiers(models_source) if any(w in n.lower() for w in _STREAK_WORDS)
    }
    assert not offenders, offenders


# ------------------------------------------------------------- §8 fallos


def test_fallo1_streak_is_not_progress():
    """Fallo 1: 3 aciertos seguidos tras un historial malo NO son COMPETENT."""
    tracker = new_tracker()
    record_facts(tracker, facts((False, False, False, False, False, True, True, True)))
    state = tracker.get_state(O1, d(8))
    assert state.level < Level.COMPETENT
    assert state.level == Level.WEAK
    assert state.recent_window[-3:] == (True, True, True)
    # El progreso se lee en lo que una racha no puede dar.
    assert state.total_attempts == 8 and state.correct_attempts == 3
    assert state.recent_window == (False,) * 5 + (True,) * 3
    assert 0.0 < state.score < 0.85
    assert "streak" not in dataclasses.asdict(state)

    # Y el caso literal de §8: cinco respuestas nunca parecen "no se guardó nada".
    spec3 = new_tracker()
    record_facts(spec3, facts((False, False, False, True, False), objective_id=O2), objective_id=O2)
    s5 = spec3.get_state(O2, d(4))
    assert s5.total_attempts == 5
    assert s5.recent_window == (False, False, False, True, False)
    assert round(s5.score, 3) == 0.267


def test_fallo2_sets_equal_but_counts_differ_is_not_ok():
    """Fallo 2: igualdad de conjuntos con conteos distintos NO puede ser OK."""
    dup = DuplicatingStore()
    tracker = new_tracker(attempts=dup)
    record_facts(tracker, facts(HISTORY))
    as_of = d(30)

    real = set(InMemoryAttemptStore.list_all(dup, PID))
    seen = set(dup.list_all(PID))
    assert seen == real, "por conjuntos el store corrupto parece sano"
    assert len(dup.list_all(PID)) != len(real)

    report = tracker.check_consistency(as_of)
    assert report.ok is False
    assert report.failures, "el reporte debe llevar los números de ambos lados"
    for check in report.failures:
        assert check.expected != check.actual
    by_name = {c.name: c for c in report.checks}
    assert by_name["profile_attempt_count"].expected == len(HISTORY)
    assert by_name["profile_attempt_count"].actual == len(HISTORY) + 1
    # ok es positivo: solo con todos los checks pasados. No es un bool suelto.
    assert isinstance(report.ok, bool)
    assert report.ok == (report.objectives_checked >= 1 and all(c.passed for c in report.checks))


_ACCUMULATOR_WORDS = (
    "level", "score", "streak", "racha", "ease", "lapse", "interval",
    "count", "total", "correct", "review", "due", "retention",
)


def test_fallo3_no_persisted_accumulators():
    """Fallo 3: nada de nivel/contador/ease/lapses se guarda: se deriva."""
    for model in (Objective, Profile):
        for field in dataclasses.fields(model):
            assert not any(w in field.name.lower() for w in _ACCUMULATOR_WORDS), (
                model.__name__,
                field.name,
            )
        assert model.__dataclass_params__.frozen
    # Attempt es el hecho: lleva `correct` (dato), pero ningún acumulador.
    attempt_fields = {f.name for f in dataclasses.fields(Attempt)}
    assert attempt_fields == {
        "attempt_id", "objective_id", "at", "correct", "kind",
        "confidence", "note", "recorded_at",
    }
    assert Attempt.__dataclass_params__.frozen

    # La "corrupción" de un agregado es imposible de persistir: tras registrar,
    # el único dato del store son Attempts, y el estado sale de recalcular.
    tracker = new_tracker()
    record_facts(tracker, facts(HISTORY))
    store_rows = tracker._attempts.list_all(PID)  # noqa: SLF001
    assert all(isinstance(a, Attempt) for a in store_rows)
    assert not any(isinstance(a, ObjectiveState) for a in store_rows)

    s1 = tracker.get_state(O1, d(30))
    assert tracker.rebuild(d(30)) == len(ALL_OBJECTIVES)
    assert tracker.get_state(O1, d(30)) == s1
    # Y volver a preguntar en un pasado anterior "revierte" sin ningún contador.
    assert tracker.get_state(O1, d(2)).total_attempts == 3


def test_fallo4_silence_is_visible_via_unstarted_and_stale():
    """Fallo 4: lo no registrado aparece en get_unstarted / get_stale."""
    tracker = new_tracker(clock=FixedClock(d(40)))
    record_facts(tracker, facts((True, True, True)))  # O1: días 0..2
    record_facts(tracker, facts((True,), objective_id=O2, start=35), objective_id=O2)

    unstarted = {s.objective_id for s in tracker.get_unstarted(d(40))}
    assert unstarted == {O3}
    assert all(s.total_attempts == 0 for s in tracker.get_unstarted(d(40)))

    stale = {s.objective_id for s in tracker.get_stale(d(40), days=14)}
    assert stale == {O1}, "O1 lleva 38 días sin actividad; O2 es reciente; O3 nunca empezó"
    assert stale.isdisjoint(unstarted)
    assert {s.objective_id for s in tracker.get_stale(d(40), days=3)} == {O1, O2}
    assert tracker.get_stale(d(3), days=14) == []

    # Con as_of=None, el reloj inyectado da el mismo veredicto.
    assert {s.objective_id for s in tracker.get_stale()} == {O1}
    assert {s.objective_id for s in tracker.get_unstarted()} == {O3}
    assert tracker.get_summary(d(40)).unstarted_objectives == 1


def test_fallo5_as_of_none_uses_injected_clock():
    """Fallo 5: sin as_of se usa el Clock inyectado; cambiarlo cambia el resultado."""
    attempts = InMemoryAttemptStore()
    profiles = InMemoryProfileStore()
    early = new_tracker(clock=FixedClock(d(8)), profiles=profiles, attempts=attempts)
    late = new_tracker(clock=FixedClock(d(200)), profiles=profiles, attempts=attempts)
    record_facts(early, facts((True,) * 7))  # COMPETENT/MASTERED en d(8)

    s_early = early.get_state(O1)
    s_late = late.get_state(O1)
    assert s_early.as_of == d(8) and s_late.as_of == d(200)
    assert s_early == early.get_state(O1, d(8))
    assert s_late == late.get_state(O1, d(200))
    assert s_early != s_late
    assert s_late.retention < s_early.retention
    assert s_late.score < s_early.score
    assert early.get_level(O1) >= Level.COMPETENT
    assert late.get_level(O1) < early.get_level(O1)
    assert early.get_summary().as_of == d(8) and late.get_summary().as_of == d(200)

    # OffsetClock simula el avance sin esperar.
    moved = new_tracker(
        clock=OffsetClock(FixedClock(d(8)), timedelta(days=192)),
        profiles=profiles,
        attempts=attempts,
    )
    assert moved.get_state(O1) == s_late
    # recorded_at sale también del reloj, no del sistema.
    written = late.record_attempt(O2, correct=True, at=d(0))
    assert written.recorded_at == d(200)
