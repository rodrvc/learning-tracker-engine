"""Tests de core/models.py contra SPEC.md §1, §9.2 e invariantes I1 e I10.

Convenciones:

* ``spec``: las validaciones que §1.3 exige a un ``Attempt`` y el hecho de que
  ``confidence``/``weight`` no afectan a ningún cálculo (§10).
* ``invariant``: inmutabilidad (I1) y ausencia de ``streak`` (I10).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from core.errors import InvalidAttemptError, TrackerError
from core.leveling import compute_score
from core.models import (
    Attempt,
    AttemptKind,
    ConsistencyCheck,
    ConsistencyReport,
    Level,
    Objective,
    ObjectiveState,
    Profile,
    ProfileSummary,
    SessionReport,
    SessionStatus,
    StateComparison,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
OBJ = "D3.2-content-understanding"

MODEL_TYPES = (
    Profile,
    Objective,
    Attempt,
    ObjectiveState,
    ProfileSummary,
    StateComparison,
    ConsistencyCheck,
    ConsistencyReport,
    SessionReport,
)


def attempt(i: int, correct: bool, **overrides) -> Attempt:
    fields = dict(
        attempt_id=f"a{i:03d}",
        objective_id=OBJ,
        at=T0 + timedelta(days=i),
        correct=correct,
    )
    fields.update(overrides)
    return Attempt(**fields)


def state(**overrides) -> ObjectiveState:
    fields = dict(
        objective_id=OBJ,
        as_of=T0,
        level=Level.UNASSESSED,
        score=0.0,
        total_attempts=0,
        correct_attempts=0,
        recent_window=(),
        first_attempt_at=None,
        last_attempt_at=None,
        distinct_days=0,
        days_since_last=None,
        retention=1.0,
        next_review_at=None,
        is_due=False,
    )
    fields.update(overrides)
    return ObjectiveState(**fields)


# --------------------------------------------------------------------------
# I1: inmutabilidad
# --------------------------------------------------------------------------


@pytest.mark.invariant
def test_i1_attempt_no_se_puede_mutar():
    a = attempt(0, True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.correct = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.at = T0 + timedelta(days=1)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del a.note  # type: ignore[misc]
    assert a.correct is True


@pytest.mark.invariant
@pytest.mark.parametrize("model", MODEL_TYPES, ids=lambda t: t.__name__)
def test_i1_todos_los_modelos_son_frozen(model):
    assert dataclasses.is_dataclass(model)
    assert model.__dataclass_params__.frozen is True


@pytest.mark.invariant
def test_i1_objective_state_no_se_puede_mutar():
    s = state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.score = 1.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# I10: sin streak
# --------------------------------------------------------------------------


@pytest.mark.invariant
def test_i10_objective_state_no_expone_streak():
    names = {f.name for f in dataclasses.fields(ObjectiveState)}
    assert "streak" not in names
    assert not any("streak" in n for n in names)
    assert not hasattr(ObjectiveState, "streak")


@pytest.mark.invariant
def test_i10_objective_no_guarda_progreso():
    names = {f.name for f in dataclasses.fields(Objective)}
    assert names == {"objective_id", "title", "domain", "weight", "tags"}


@pytest.mark.spec
def test_objective_state_tiene_los_campos_de_spec_1_5():
    names = {f.name for f in dataclasses.fields(ObjectiveState)}
    required = {
        "objective_id",
        "as_of",
        "level",
        "score",
        "total_attempts",
        "correct_attempts",
        "recent_window",
        "first_attempt_at",
        "last_attempt_at",
        "distinct_days",
        "next_review_at",
        "is_due",
    }
    assert required <= names


# --------------------------------------------------------------------------
# §1.4: Level ordenado
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_level_es_ordenado_y_con_los_valores_de_spec():
    assert [lvl.value for lvl in Level] == [0, 1, 2, 3, 4]
    assert Level.UNASSESSED < Level.WEAK < Level.LEARNING < Level.COMPETENT < Level.MASTERED
    assert Level.MASTERED - Level.WEAK == 3


@pytest.mark.spec
def test_attempt_kind_tiene_los_cinco_valores_de_spec():
    assert {k.value for k in AttemptKind} == {
        "quiz",
        "exercise",
        "lab",
        "exam_sim",
        "self_report",
    }


# --------------------------------------------------------------------------
# §1.3: validaciones de Attempt
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_attempt_valido_se_construye_con_defaults():
    a = attempt(0, True)
    assert a.kind is AttemptKind.QUIZ
    assert a.confidence is None
    assert a.note is None
    assert a.recorded_at is None


@pytest.mark.spec
def test_attempt_at_y_recorded_at_son_campos_separados():
    recorded = T0 + timedelta(days=30)
    a = attempt(0, True, recorded_at=recorded)
    assert a.at == T0
    assert a.recorded_at == recorded
    assert a.at != a.recorded_at


@pytest.mark.spec
def test_attempt_at_naive_lanza_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, at=datetime(2026, 1, 1, 12, 0))


@pytest.mark.spec
def test_attempt_recorded_at_naive_lanza_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, recorded_at=datetime(2026, 1, 1, 12, 0))


@pytest.mark.spec
def test_attempt_at_no_datetime_lanza_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, at="2026-01-01T12:00:00+00:00")


@pytest.mark.spec
@pytest.mark.parametrize("bad", ["", "   "])
def test_attempt_objective_id_vacio_lanza_invalid_attempt(bad):
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, objective_id=bad)


@pytest.mark.spec
@pytest.mark.parametrize("bad", ["", "   "])
def test_attempt_id_vacio_lanza_invalid_attempt(bad):
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, attempt_id=bad)


@pytest.mark.spec
@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_attempt_confidence_fuera_de_rango_lanza_invalid_attempt(bad):
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, confidence=bad)


@pytest.mark.spec
@pytest.mark.parametrize("ok", [0.0, 0.5, 1.0, None])
def test_attempt_confidence_en_rango_es_valido(ok):
    assert attempt(0, True, confidence=ok).confidence == ok


@pytest.mark.spec
def test_attempt_kind_invalido_lanza_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, True, kind="quiz")


@pytest.mark.spec
def test_attempt_correct_no_bool_lanza_invalid_attempt():
    with pytest.raises(InvalidAttemptError):
        attempt(0, correct=1)


@pytest.mark.spec
def test_invalid_attempt_error_hereda_de_tracker_error():
    assert issubclass(InvalidAttemptError, TrackerError)


# --------------------------------------------------------------------------
# §10: confidence y weight no afectan a ningún cálculo
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_confidence_no_mueve_el_score():
    results = [False, True, True, False, True, True, True, False, True, True]
    sin = [attempt(i, r) for i, r in enumerate(results)]
    con = [
        attempt(i, r, confidence=(0.05 if r else 0.95), kind=AttemptKind.EXAM_SIM)
        for i, r in enumerate(results)
    ]
    as_of = T0 + timedelta(days=len(results))
    assert compute_score(sin, as_of) == compute_score(con, as_of)
    assert compute_score(sin, as_of) > 0.0


@pytest.mark.spec
def test_weight_del_objetivo_es_solo_informativo():
    """El cálculo del score ni siquiera recibe el ``Objective``; su ``weight``
    no puede influir en el nivel."""
    pesado = Objective(objective_id=OBJ, title="t", weight=10.0)
    ligero = Objective(objective_id=OBJ, title="t", weight=0.1)
    assert pesado.weight != ligero.weight
    history = [attempt(i, True) for i in range(5)]
    as_of = T0 + timedelta(days=5)
    # No hay forma de pasarle un peso a compute_score: mismo historial => mismo score.
    assert compute_score(history, as_of) == compute_score(list(history), as_of)
    assert Objective(objective_id=OBJ, title="t").weight == 1.0


# --------------------------------------------------------------------------
# §1.1 / §1.2: Profile y Objective
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_profile_indexa_objetivos_por_id():
    o = Objective(objective_id=OBJ, title="Content understanding", domain="D3")
    p = Profile(profile_id="ai-103", name="Microsoft AI-103", objectives={OBJ: o})
    assert p.objectives[OBJ] is o
    assert Profile(profile_id="x", name="x").objectives == {}


# --------------------------------------------------------------------------
# §9.5 / §8 fallo 2: ConsistencyReport.failures
# --------------------------------------------------------------------------


def check(name: str, expected: float, actual: float) -> ConsistencyCheck:
    return ConsistencyCheck(
        name=name, expected=expected, actual=actual, passed=expected == actual
    )


@pytest.mark.spec
def test_consistency_report_failures_devuelve_solo_los_fallidos():
    ok = check("attempt_count", 5, 5)
    bad = check("correct_sum", 3, 4)
    report = ConsistencyReport(
        ok=False, checks=(ok, bad), objectives_checked=1, as_of=T0
    )
    assert report.failures == (bad,)


@pytest.mark.spec
def test_consistency_report_sin_fallos_devuelve_tupla_vacia():
    report = ConsistencyReport(
        ok=True,
        checks=(check("attempt_count", 5, 5),),
        objectives_checked=1,
        as_of=T0,
    )
    assert report.failures == ()
    assert isinstance(report.failures, tuple)


@pytest.mark.spec
def test_consistency_check_compara_numeros_sin_tolerancia():
    assert check("attempt_count", 5, 5).passed is True
    assert check("attempt_count", 5, 6).passed is False


# --------------------------------------------------------------------------
# §9.6: SessionReport
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_session_report_empty_es_un_estado_explicito():
    report = SessionReport(
        session_id="s1",
        started_at=T0,
        ended_at=T0 + timedelta(minutes=5),
        attempts_recorded=0,
        objectives_touched=(),
        status=SessionStatus.EMPTY,
    )
    assert report.status is SessionStatus.EMPTY
    assert SessionStatus.EMPTY != SessionStatus.RECORDED


# --------------------------------------------------------------------------
# §5.1: StateComparison
# --------------------------------------------------------------------------


@pytest.mark.spec
def test_state_comparison_guarda_los_dos_estados():
    earlier = state(level=Level.WEAK, score=0.3)
    later = state(as_of=T0 + timedelta(days=14), level=Level.COMPETENT, score=0.8)
    cmp = StateComparison(
        objective_id=OBJ,
        earlier=earlier,
        later=later,
        level_delta=later.level - earlier.level,
        score_delta=later.score - earlier.score,
        improved=True,
        regressed=False,
    )
    assert cmp.level_delta == 2
    assert cmp.improved and not cmp.regressed
