"""Tests de core/leveling.py contra SPEC.md §2, §3, §3.1 y §7.

Convenciones:

* ``spec``: un test por cada paso de §2.2.
* ``edge``: casos límite de §7 (C1, C2, C3, C5, C6, C7, C10).
* ``invariant``: determinismo (I3) e independencia del orden de inserción.

Los números de los tests de aceptación (§3 y §3.1) son los de la tabla de la
spec, copiados tal cual. Si un número no cuadra, se reporta la discrepancia; no
se ajusta el test.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.constants import (
    DECAY_HALF_LIFE_DAYS,
    MASTERY_MIN_DAYS,
    MASTERY_MIN_RAW,
    MASTERY_MIN_SPAN_DAYS,
    MIN_ATTEMPTS,
    RETENTION_FLOOR,
    SCORE_PRECISION,
    THRESHOLD_COMPETENT,
    THRESHOLD_LEARNING,
    WINDOW,
)
from core.leveling import (
    attempts_until,
    compute_level,
    compute_score,
    compute_state,
    distinct_attempt_days,
    order_attempts,
    recent_window,
    retention_factor,
    weighted_raw_score,
)
from core.models import Attempt, Level, ObjectiveState

OBJ = "X"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)

#: Tolerancia para comparar contra los 3 decimales de las tablas de la spec.
TABLE_TOL = 0.0005


def attempt(
    i: int,
    correct: bool,
    at: datetime,
    recorded_at: datetime | None = None,
    attempt_id: str | None = None,
) -> Attempt:
    return Attempt(
        attempt_id=attempt_id or f"a{i:03d}",
        objective_id=OBJ,
        at=at,
        correct=correct,
        recorded_at=recorded_at,
    )


def daily(results: str, start: datetime = T0) -> list[Attempt]:
    """'FFFCF' -> un intento por día consecutivo, en orden, desde ``start``."""
    return [
        attempt(i, ch == "C", start + i * DAY) for i, ch in enumerate(results)
    ]


# ---------------------------------------------------------------------------
# §2.2 paso 1 — filtrar y ordenar
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_paso1_order_attempts_ordena_por_at_y_desempata_por_attempt_id():
    a = attempt(0, True, T0 + DAY, attempt_id="b")
    b = attempt(1, True, T0 + DAY, attempt_id="a")
    c = attempt(2, True, T0, attempt_id="z")
    original = [a, b, c]
    ordered = order_attempts(original)
    assert [x.attempt_id for x in ordered] == ["z", "a", "b"]
    assert original == [a, b, c], "no debe mutar la entrada"
    assert ordered is not original


@pytest.mark.spec
def test_paso1_attempts_until_corta_por_at_inclusivo():
    history = daily("CCC")
    cut = attempts_until(history, T0 + DAY)
    assert [x.attempt_id for x in cut] == ["a000", "a001"]


@pytest.mark.spec
def test_paso1_attempts_until_ignora_recorded_at():
    late_write = T0 + 30 * DAY
    history = [
        attempt(0, True, T0, recorded_at=late_write),
        attempt(1, True, T0 + DAY, recorded_at=late_write),
        attempt(2, True, T0 + 2 * DAY, recorded_at=T0 + 2 * DAY),
    ]
    cut = attempts_until(history, T0 + DAY)
    assert [x.attempt_id for x in cut] == ["a000", "a001"]
    assert attempts_until(history, late_write) == order_attempts(history)


# ---------------------------------------------------------------------------
# §2.2 paso 2 — n < MIN_ATTEMPTS => UNASSESSED
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize("correct", [True, False])
def test_paso2_menos_de_min_attempts_es_unassessed_y_score_cero(correct):
    history = [attempt(0, correct, T0)]
    assert len(history) < MIN_ATTEMPTS
    assert compute_score(history, T0) == 0.0
    assert compute_level(0.0, history, T0) is Level.UNASSESSED
    # Aunque alguien pase un score alto, con n<MIN_ATTEMPTS sigue UNASSESSED.
    assert compute_level(1.0, history, T0) is Level.UNASSESSED


@pytest.mark.spec
def test_paso2_con_min_attempts_ya_se_asigna_nivel():
    history = daily("F" * MIN_ATTEMPTS)
    as_of = history[-1].at
    assert compute_level(compute_score(history, as_of), history, as_of) is Level.WEAK


# ---------------------------------------------------------------------------
# §2.2 paso 3 — ventana reciente
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_paso3_recent_window_ultimos_window_de_antiguo_a_reciente():
    history = daily("F" * 3 + "C" * WINDOW)
    window = recent_window(history)
    assert len(window) == WINDOW
    assert window == (True,) * WINDOW
    history = daily("FC")
    assert recent_window(history) == (False, True)
    assert recent_window([]) == ()


@pytest.mark.spec
def test_paso3_pesos_posicionales_ventana_llena_suma_36():
    # Con ventana llena los pesos son 1..8 (suma 36): un único acierto en la
    # posición más reciente pesa 8/36.
    window = (False,) * (WINDOW - 1) + (True,)
    total = sum(range(1, WINDOW + 1))
    assert total == 36
    assert weighted_raw_score(window) == pytest.approx(WINDOW / total)
    # ...y el más antiguo pesa 1/36.
    assert weighted_raw_score((True,) + (False,) * (WINDOW - 1)) == pytest.approx(1 / total)


# ---------------------------------------------------------------------------
# §2.2 paso 4 — raw
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_paso4_raw_es_suma_de_pesos_correctos_sobre_total():
    # Fila 4 de §3: [F,F,F,C] -> 4/10.
    assert weighted_raw_score((False, False, False, True)) == pytest.approx(0.4)
    # Fila 5 de §3: [F,F,F,C,F] -> 4/15.
    assert weighted_raw_score((False, False, False, True, False)) == pytest.approx(4 / 15)


@pytest.mark.spec
def test_paso4_raw_sin_suelo_puede_ser_cero_y_uno():
    assert weighted_raw_score((False, False, False)) == 0.0
    assert weighted_raw_score((True,) * WINDOW) == 1.0
    assert weighted_raw_score(()) == 0.0
    assert 0.0 < RETENTION_FLOOR, "el suelo existe, pero no toca al raw"


@pytest.mark.spec
def test_paso4_tabla_2_4_un_fallo_residual():
    full = (True,) * WINDOW
    oldest_fail = (False,) + (True,) * (WINDOW - 1)
    second_oldest_fail = (True, False) + (True,) * (WINDOW - 2)
    assert weighted_raw_score(full) == pytest.approx(1.0)
    assert weighted_raw_score(oldest_fail) == pytest.approx(0.972, abs=TABLE_TOL)
    assert weighted_raw_score(second_oldest_fail) == pytest.approx(0.944, abs=TABLE_TOL)
    assert weighted_raw_score(oldest_fail) >= MASTERY_MIN_RAW
    assert weighted_raw_score(second_oldest_fail) < MASTERY_MIN_RAW


# ---------------------------------------------------------------------------
# §2.2 paso 5 — decaimiento con suelo
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    "gap_days, expected",
    [(0, 1.000), (7, 0.948), (15, 0.891), (30, 0.794), (60, 0.630),
     (90, 0.500), (180, 0.400), (365, 0.400)],
)
def test_paso5_tabla_de_retencion(gap_days, expected):
    assert retention_factor(T0, T0 + gap_days * DAY) == pytest.approx(
        expected, abs=TABLE_TOL
    )


@pytest.mark.spec
def test_paso5_retention_formula_con_gap_fraccionario():
    gap = timedelta(days=45, hours=12)
    expected = 0.5 ** ((45 + 0.5) / DECAY_HALF_LIFE_DAYS)
    assert retention_factor(T0, T0 + gap) == pytest.approx(expected)
    assert retention_factor(T0, T0 + timedelta(days=DECAY_HALF_LIFE_DAYS)) == pytest.approx(0.5)


@pytest.mark.spec
def test_paso5_gap_no_positivo_o_sin_intentos_da_uno():
    assert retention_factor(T0, T0) == 1.0
    assert retention_factor(T0 + DAY, T0) == 1.0
    assert retention_factor(None, T0) == 1.0


@pytest.mark.spec
def test_paso5_suelo_se_aplica_solo_a_retention_nunca_al_raw():
    # Dominado y abandonado un año: raw 1.0 x 0.40 = 0.400.
    mastered_abandoned = daily("C" * WINDOW)
    a_year_later = mastered_abandoned[-1].at + 365 * DAY
    assert retention_factor(mastered_abandoned[-1].at, a_year_later) == RETENTION_FLOOR
    assert compute_score(mastered_abandoned, a_year_later) == pytest.approx(RETENTION_FLOOR)
    # Se falla siempre, recién visto: raw 0.0 x 1.0 = 0.0 (el suelo NO lo levanta).
    always_wrong = daily("F" * WINDOW)
    assert compute_score(always_wrong, always_wrong[-1].at) == 0.0
    # Se falla siempre y abandonado: 0.0 x 0.40 = 0.0, no 0.40.
    assert compute_score(always_wrong, always_wrong[-1].at + 365 * DAY) == 0.0


@pytest.mark.spec
def test_paso5_score_es_raw_por_retention_redondeado():
    history = daily("FCCC")
    as_of = history[-1].at + 33 * DAY
    raw = weighted_raw_score(recent_window(history))
    retention = retention_factor(history[-1].at, as_of)
    assert compute_score(history, as_of) == round(raw * retention, SCORE_PRECISION)


# ---------------------------------------------------------------------------
# §2.2 paso 6 — umbrales cerrados por abajo
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    "score, expected",
    [
        (0.0, Level.WEAK),
        (THRESHOLD_LEARNING - 1e-6, Level.WEAK),
        (THRESHOLD_LEARNING, Level.LEARNING),
        (THRESHOLD_COMPETENT - 1e-6, Level.LEARNING),
        (THRESHOLD_COMPETENT, Level.COMPETENT),
        (1.0, Level.COMPETENT),
    ],
)
def test_paso6_umbrales(score, expected):
    # Historial de una tarde: nunca puede ser MASTERED (span 0), así que el
    # test aísla el paso 6 del paso 7.
    history = [attempt(i, True, T0 + i * timedelta(minutes=1)) for i in range(WINDOW)]
    assert compute_level(score, history, history[-1].at) is expected


# ---------------------------------------------------------------------------
# §2.2 paso 7 — ascenso a MASTERED
# ---------------------------------------------------------------------------


def _mastery_candidate(span_days: int, results: str = "C" * WINDOW) -> list[Attempt]:
    """Intentos repartidos entre T0 y T0+span_days, en días distintos."""
    step = timedelta(days=span_days) / max(len(results) - 1, 1)
    return [attempt(i, ch == "C", T0 + i * step) for i, ch in enumerate(results)]


@pytest.mark.spec
def test_paso7_mastered_con_las_tres_condiciones():
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS)
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert distinct_attempt_days(history) >= MASTERY_MIN_DAYS
    assert compute_level(score, history, as_of) is Level.MASTERED


@pytest.mark.spec
def test_paso7_sin_span_suficiente_se_queda_en_competent():
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS - 1)
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert compute_level(score, history, as_of) is Level.COMPETENT


@pytest.mark.spec
def test_paso7_sin_dias_distintos_se_queda_en_competent():
    # Todos los intentos el mismo día natural, aunque el span sea >= 7 días
    # es imposible; aquí se fuerza distinct_days == 1 con span 0.
    history = [attempt(i, True, T0 + i * timedelta(hours=1)) for i in range(WINDOW)]
    as_of = history[-1].at
    assert distinct_attempt_days(history) == 1 < MASTERY_MIN_DAYS
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert compute_level(score, history, as_of) is Level.COMPETENT


@pytest.mark.spec
def test_paso7_raw_por_debajo_de_0_95_se_queda_en_competent():
    # Fallo con peso 2: raw = 34/36 = 0.944 < 0.95, score >= 0.85.
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS * 2, "CF" + "C" * (WINDOW - 2))
    as_of = history[-1].at
    score = compute_score(history, as_of)
    assert score >= THRESHOLD_COMPETENT
    assert weighted_raw_score(recent_window(history)) < MASTERY_MIN_RAW
    assert compute_level(score, history, as_of) is Level.COMPETENT
    # Fallo con peso 1: raw = 35/36 = 0.972 >= 0.95 -> MASTERED.
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS * 2, "F" + "C" * (WINDOW - 1))
    as_of = history[-1].at
    assert compute_level(compute_score(history, as_of), history, as_of) is Level.MASTERED


@pytest.mark.spec
def test_paso7_mastered_se_pierde_por_decaimiento_no_por_sostenimiento():
    # §2.4: el score cae por debajo de 0.85 a los 22 días y salta a LEARNING.
    history = _mastery_candidate(MASTERY_MIN_SPAN_DAYS * 2)
    last = history[-1].at
    assert compute_level(compute_score(history, last + 21 * DAY), history, last + 21 * DAY) is Level.MASTERED
    assert compute_level(compute_score(history, last + 22 * DAY), history, last + 22 * DAY) is Level.LEARNING


# ---------------------------------------------------------------------------
# distinct_attempt_days (C3)
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_distinct_attempt_days_compara_fechas_naturales():
    same_day = [
        attempt(0, True, datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)),
        attempt(1, True, datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)),
    ]
    assert distinct_attempt_days(same_day) == 1
    # Un minuto de diferencia, pero cruzando la medianoche: dos días.
    across_midnight = [
        attempt(0, True, datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)),
        attempt(1, True, datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)),
    ]
    assert distinct_attempt_days(across_midnight) == 2
    assert same_day[0].at.date() == date(2026, 1, 1)
    assert distinct_attempt_days([]) == 0


# ---------------------------------------------------------------------------
# §3 y §3.1 — tests de aceptación, número a número contra la tabla
# ---------------------------------------------------------------------------

# (#, resultado, raw, score, nivel) de las tablas §3 y §3.1. La fila 1 no tiene
# raw en la tabla ("—"); se codifica como None.
RECORRIDO = [
    (1, "F", None, 0.000, Level.UNASSESSED),
    (2, "F", 0.000, 0.000, Level.WEAK),
    (3, "F", 0.000, 0.000, Level.WEAK),
    (4, "C", 0.400, 0.400, Level.WEAK),
    (5, "F", 0.267, 0.267, Level.WEAK),
    (6, "C", 0.476, 0.476, Level.WEAK),
    (7, "C", 0.607, 0.607, Level.LEARNING),
    (8, "C", 0.694, 0.694, Level.LEARNING),
    (9, "C", 0.806, 0.806, Level.LEARNING),
    (10, "C", 0.889, 0.889, Level.COMPETENT),
    (11, "C", 0.944, 0.944, Level.COMPETENT),
    (12, "C", 0.972, 0.972, Level.MASTERED),
    (13, "C", 1.000, 1.000, Level.MASTERED),
]
RECORRIDO_RESULTADOS = "".join(row[1] for row in RECORRIDO)
RECORRIDO_INICIO = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.spec
@pytest.mark.parametrize("row", RECORRIDO, ids=[f"fila{r[0]}" for r in RECORRIDO])
def test_recorrido_seccion_3_y_3_1(row):
    n, _, raw_expected, score_expected, level_expected = row
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    as_of = history[n - 1].at
    state = compute_state(OBJ, history, as_of)
    window = recent_window(attempts_until(history, as_of))
    assert state.total_attempts == n
    assert len(window) == min(n, WINDOW)
    if raw_expected is not None:
        assert weighted_raw_score(window) == pytest.approx(raw_expected, abs=TABLE_TOL)
    assert state.retention == 1.0
    assert state.score == pytest.approx(score_expected, abs=TABLE_TOL)
    assert state.level is level_expected


@pytest.mark.spec
def test_recorrido_fila_12_condiciones_de_mastered():
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    state = compute_state(OBJ, history, history[11].at)
    assert state.distinct_days == 12
    assert state.last_attempt_at - state.first_attempt_at == 11 * DAY
    assert state.recent_window == (False,) + (True,) * (WINDOW - 1)


OLVIDO = [
    (datetime(2026, 1, 13, 12, 0, tzinfo=timezone.utc), 0, 1.000, 1.000, Level.MASTERED),
    (datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc), 7, 0.948, 0.948, Level.MASTERED),
    (datetime(2026, 2, 3, 12, 0, tzinfo=timezone.utc), 21, 0.851, 0.851, Level.MASTERED),
    (datetime(2026, 2, 4, 12, 0, tzinfo=timezone.utc), 22, 0.844, 0.844, Level.LEARNING),
    (datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc), 30, 0.794, 0.794, Level.LEARNING),
    (datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc), 60, 0.630, 0.630, Level.LEARNING),
    (datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc), 90, 0.500, 0.500, Level.WEAK),
    (datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc), 180, 0.400, 0.400, Level.WEAK),
    (datetime(2027, 1, 13, 12, 0, tzinfo=timezone.utc), 365, 0.400, 0.400, Level.WEAK),
]


@pytest.mark.spec
@pytest.mark.parametrize("row", OLVIDO, ids=[f"gap{r[1]}d" for r in OLVIDO])
def test_olvido_seccion_3_1_sin_intentos_nuevos(row):
    as_of, gap, retention_expected, score_expected, level_expected = row
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    assert as_of - history[-1].at == gap * DAY
    state = compute_state(OBJ, history, as_of)
    assert state.days_since_last == pytest.approx(gap)
    assert state.retention == pytest.approx(retention_expected, abs=TABLE_TOL)
    assert state.score == pytest.approx(score_expected, abs=TABLE_TOL)
    assert state.level is level_expected


# ---------------------------------------------------------------------------
# §7 — casos límite
# ---------------------------------------------------------------------------


@pytest.mark.edge
def test_c1_objetivo_sin_intentos():
    state = compute_state(OBJ, [], T0)
    assert state == ObjectiveState(
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


@pytest.mark.edge
@pytest.mark.parametrize("correct", [True, False])
def test_c2_un_solo_intento(correct):
    history = [attempt(0, correct, T0)]
    state = compute_state(OBJ, history, T0)
    assert state.level is Level.UNASSESSED
    assert state.score == 0.0
    assert state.total_attempts == 1
    assert state.correct_attempts == int(correct)
    assert state.recent_window == (correct,)
    assert state.first_attempt_at == state.last_attempt_at == T0
    assert state.next_review_at is not None
    assert state.next_review_at > T0


@pytest.mark.edge
def test_c3_dos_intentos_el_mismo_dia_son_independientes_pero_un_solo_dia():
    history = [
        attempt(0, False, T0),
        attempt(1, True, T0 + timedelta(hours=2)),
    ]
    state = compute_state(OBJ, history, history[-1].at)
    assert state.total_attempts == 2
    assert state.recent_window == (False, True)
    assert state.score == pytest.approx(2 / 3)
    assert state.distinct_days == 1


@pytest.mark.edge
def test_c3_mismo_at_exacto_desempata_por_attempt_id():
    a = attempt(0, True, T0, attempt_id="b")
    b = attempt(1, False, T0, attempt_id="a")
    state = compute_state(OBJ, [a, b], T0)
    # Orden: "a" (fallo) y luego "b" (acierto): el acierto es el más reciente.
    assert state.recent_window == (False, True)
    assert compute_state(OBJ, [b, a], T0) == state


@pytest.mark.edge
def test_c5_hueco_largo_con_suelo():
    history = daily("C" * WINDOW)
    last = history[-1].at
    ninety = compute_state(OBJ, history, last + 90 * DAY)
    assert ninety.retention == pytest.approx(0.5)
    assert ninety.score == pytest.approx(0.5)
    assert ninety.level is Level.WEAK
    year = compute_state(OBJ, history, last + 365 * DAY)
    assert year.retention == RETENTION_FLOOR
    assert year.score == pytest.approx(RETENTION_FLOOR)
    assert year.level is Level.WEAK
    decade = compute_state(OBJ, history, last + 3650 * DAY)
    assert decade.score == year.score
    assert year.is_due is True
    assert year.next_review_at < last + 365 * DAY


@pytest.mark.edge
def test_c6_as_of_anterior_al_primer_intento_equivale_a_c1():
    history = daily("CCC", T0 + 10 * DAY)
    state = compute_state(OBJ, history, T0)
    assert state == compute_state(OBJ, [], T0)
    assert state.level is Level.UNASSESSED


@pytest.mark.edge
def test_c7_as_of_futuro_es_legal_y_aplica_el_gap_futuro():
    history = daily("C" * WINDOW)
    exam_day = history[-1].at + 30 * DAY
    state = compute_state(OBJ, history, exam_day)
    assert state.total_attempts == WINDOW
    assert state.days_since_last == pytest.approx(30)
    assert state.retention == pytest.approx(0.794, abs=TABLE_TOL)
    assert state.level is Level.LEARNING


@pytest.mark.edge
def test_c10_empate_exacto_en_el_umbral():
    # Historial de una tarde (span 0): el paso 7 no interfiere.
    history = [attempt(i, True, T0 + i * timedelta(minutes=1)) for i in range(WINDOW)]
    as_of = history[-1].at
    assert compute_level(THRESHOLD_COMPETENT, history, as_of) is Level.COMPETENT
    assert compute_level(THRESHOLD_LEARNING, history, as_of) is Level.LEARNING
    # Redondeo a 6 decimales ANTES de umbral: 0.8499999999 es 0.85.
    assert compute_level(THRESHOLD_COMPETENT - 1e-9, history, as_of) is Level.COMPETENT
    assert compute_level(THRESHOLD_LEARNING - 1e-9, history, as_of) is Level.LEARNING
    # Y compute_score devuelve ya redondeado.
    score = compute_score(history, as_of + 21 * DAY)
    assert score == round(score, SCORE_PRECISION)


@pytest.mark.edge
def test_c10_score_redondeado_produce_empate_real():
    # Construimos un score que, sin redondear, quedaría a ~1e-9 bajo 0.85 y
    # comprobamos que compute_score lo entrega redondeado a 6 decimales.
    history = daily("C" * WINDOW)
    last = history[-1].at
    target_gap = DECAY_HALF_LIFE_DAYS * (-__import__("math").log2(THRESHOLD_COMPETENT))
    as_of = last + timedelta(days=target_gap)
    score = compute_score(history, as_of)
    assert score == pytest.approx(THRESHOLD_COMPETENT, abs=10 ** -SCORE_PRECISION)
    assert len(str(score).split(".")[1]) <= SCORE_PRECISION


# ---------------------------------------------------------------------------
# I3 / C4 — determinismo e independencia del orden de inserción
# ---------------------------------------------------------------------------


@pytest.mark.invariant
def test_i3_permutar_el_orden_de_insercion_da_el_mismo_estado():
    history = daily(RECORRIDO_RESULTADOS, RECORRIDO_INICIO)
    as_of = history[-1].at + 5 * DAY
    reference = compute_state(OBJ, history, as_of)
    for permuted in (list(reversed(history)), history[5:] + history[:5], history[::2] + history[1::2]):
        assert compute_state(OBJ, permuted, as_of) == reference
    assert compute_state(OBJ, tuple(history), as_of) == reference


@pytest.mark.invariant
def test_c4_insercion_tardia_cambia_el_pasado_solo_por_at():
    history = daily("CCCCC")
    day_4 = history[3].at
    before = compute_state(OBJ, history, day_4)
    late = attempt(99, False, history[2].at + timedelta(hours=1), recorded_at=history[-1].at + 10 * DAY)
    after = compute_state(OBJ, history + [late], day_4)
    assert after.total_attempts == before.total_attempts + 1
    assert after.score < before.score
    # Y nada cambia para consultas anteriores a su ``at``.
    assert compute_state(OBJ, history + [late], history[1].at) == compute_state(OBJ, history, history[1].at)


@pytest.mark.invariant
def test_i10_objective_state_no_expone_streak():
    state = compute_state(OBJ, daily("CCC"), T0 + 2 * DAY)
    assert not hasattr(state, "streak")
    assert "streak" not in ObjectiveState.__dataclass_fields__


@pytest.mark.invariant
def test_i5_compute_state_no_muta_la_entrada():
    history = daily("FCF")
    snapshot = list(history)
    compute_state(OBJ, history, history[-1].at)
    assert history == snapshot
