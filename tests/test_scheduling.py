"""Tests de core/scheduling.py contra SPEC.md §4, §6 I10, §7 (C1, C2, C5) y §8.

Convenciones:

* ``spec``: §4.1 escalera, §4.2 regla (puntos 1-6) y §4.3 vencimiento, con el
  ejemplo numérico de la spec copiado tal cual.
* ``edge``: C1 (sin intentos), C2 (un solo intento), C5 (hueco largo).
* ``invariant``: I10, ``ObjectiveState`` no expone ``streak`` (fallo 1 de §8).

Ningún número mágico: la escalera, el multiplicador y el techo salen de
``core/constants.py``. Si un valor de la spec no cuadra con el código, se
reporta la discrepancia; no se ajusta el test.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.constants import (
    MASTERY_INTERVAL_MULTIPLIER,
    MAX_INTERVAL_DAYS,
    MIN_ATTEMPTS,
    SCHEDULE_DAYS,
)
from core.leveling import compute_state
from core.models import Attempt, Level, ObjectiveState
from core.scheduling import (
    compute_next_review,
    interval_days,
    is_due,
    trailing_success_run,
)

OBJ = "X"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)

#: Niveles que NO alargan el intervalo (todos menos MASTERED).
NON_MASTERED = [lvl for lvl in Level if lvl is not Level.MASTERED]


def attempt(i: int, correct: bool, at: datetime) -> Attempt:
    return Attempt(attempt_id=f"a{i:03d}", objective_id=OBJ, at=at, correct=correct)


def daily(results: str, start: datetime = T0) -> list[Attempt]:
    """'FFFCF' -> un intento por día consecutivo, en orden, desde ``start``."""
    return [attempt(i, ch == "C", start + i * DAY) for i, ch in enumerate(results)]


# ---------------------------------------------------------------------------
# §4.2 punto 1 — la racha final S (variable local, no medida de progreso)
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ("", 0),
        ("F", 0),
        ("C", 1),
        ("FFFCF", 0),  # fila 5 de §3: el último es fallo
        ("FFFC", 1),  # fila 4 de §3
        ("CCF", 0),
        ("FCC", 2),
        ("CFCCC", 3),
        ("C" * 8, 8),  # fila 13 de §3.1
    ],
)
def test_trailing_success_run_cuenta_desde_el_final_hasta_el_primer_fallo(results, expected):
    assert trailing_success_run(daily(results)) == expected


# ---------------------------------------------------------------------------
# §4.1 + §4.2 puntos 2-3 — la escalera completa
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_escalera_es_la_de_la_spec():
    assert SCHEDULE_DAYS == (1, 3, 7, 14, 30)


@pytest.mark.spec
@pytest.mark.parametrize("level", NON_MASTERED)
@pytest.mark.parametrize(
    ("success_run", "step"),
    [
        (0, 0),  # último intento fallido => índice 0 => 1 día
        (1, 0),  # S=1 -> 1d
        (2, 1),  # S=2 -> 3d
        (3, 2),  # S=3 -> 7d
        (4, 3),  # S=4 -> 14d
        (5, 4),  # S=5 -> 30d
        (6, 4),  # S>=5 satura en el último peldaño
        (8, 4),  # S=8 (fila 13 de §3.1) -> 30d
    ],
)
def test_escalera_sin_mastered(success_run, step, level):
    assert interval_days(success_run, level) == SCHEDULE_DAYS[step]


@pytest.mark.spec
def test_escalera_valores_literales_de_la_spec():
    """Los números de §4.2.3 tal cual, para que un cambio en constants.py sin
    tocar SPEC.md salte aquí."""
    expected = {0: 1, 1: 1, 2: 3, 3: 7, 4: 14, 5: 30, 8: 30}
    assert {s: interval_days(s, Level.WEAK) for s in expected} == expected


@pytest.mark.spec
def test_intervalo_siempre_al_menos_un_dia():
    for level in Level:
        for s in range(0, 20):
            assert interval_days(s, level) >= 1


# ---------------------------------------------------------------------------
# §4.2 punto 5 — MASTERED multiplica por 2 con techo 60
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize("success_run", range(0, 10))
def test_mastered_multiplica_con_techo(success_run):
    base = interval_days(success_run, Level.COMPETENT)
    assert interval_days(success_run, Level.MASTERED) == min(
        base * MASTERY_INTERVAL_MULTIPLIER, MAX_INTERVAL_DAYS
    )


@pytest.mark.spec
def test_mastered_valores_literales_de_la_spec():
    assert MASTERY_INTERVAL_MULTIPLIER == 2
    assert MAX_INTERVAL_DAYS == 60
    assert interval_days(5, Level.MASTERED) == 60
    assert interval_days(8, Level.MASTERED) == 60
    assert interval_days(4, Level.MASTERED) == 28
    assert interval_days(0, Level.MASTERED) == 2


@pytest.mark.spec
def test_el_techo_nunca_se_supera():
    for s in range(0, 50):
        assert interval_days(s, Level.MASTERED) <= MAX_INTERVAL_DAYS


@pytest.mark.spec
def test_solo_mastered_alarga_el_intervalo():
    for s in range(0, 10):
        base = {interval_days(s, lvl) for lvl in NON_MASTERED}
        assert len(base) == 1, "el nivel no-MASTERED no influye en el intervalo"


# ---------------------------------------------------------------------------
# §4.2 punto 4 — next_review_at = last_attempt_at + intervalo
# ---------------------------------------------------------------------------


@pytest.mark.spec
@pytest.mark.parametrize(
    ("results", "level"),
    [
        ("FFFCF", Level.WEAK),
        ("FFFC", Level.WEAK),
        ("FCC", Level.LEARNING),
        ("C" * 8, Level.COMPETENT),
        ("C" * 8, Level.MASTERED),
        ("C", Level.UNASSESSED),
    ],
)
def test_next_review_es_ultimo_intento_mas_intervalo(results, level):
    history = daily(results)
    expected_days = interval_days(trailing_success_run(history), level)
    assert compute_next_review(history, level) == history[-1].at + timedelta(days=expected_days)


@pytest.mark.spec
def test_next_review_conserva_la_hora_del_ultimo_intento():
    late = T0.replace(hour=23, minute=59)
    history = [attempt(0, True, late)]
    result = compute_next_review(history, Level.UNASSESSED)
    assert result == late + timedelta(days=SCHEDULE_DAYS[0])
    assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# §4.3 — vencimiento y ejemplo numérico de la spec
# ---------------------------------------------------------------------------


@pytest.mark.spec
def test_is_due_definicion():
    t = T0
    assert is_due(None, t) is False
    assert is_due(t, t) is True  # <=, no <
    assert is_due(t - timedelta(seconds=1), t) is True
    assert is_due(t + timedelta(seconds=1), t) is False


@pytest.mark.spec
def test_ejemplo_4_3_tras_fila_5_next_review_es_2026_01_06():
    """Tras la fila 5 (fallo del 2026-01-05), S=0 => 1 día => 2026-01-06."""
    history = daily("FFFCF")
    assert history[-1].at.date() == datetime(2026, 1, 5).date()
    state = compute_state(OBJ, history, history[-1].at)
    assert state.level is Level.WEAK
    assert trailing_success_run(history) == 0
    assert state.next_review_at == datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)
    assert state.next_review_at.date() == datetime(2026, 1, 6).date()
    assert state.is_due is False
    assert is_due(state.next_review_at, state.next_review_at) is True


@pytest.mark.spec
def test_ejemplo_4_3_tras_fila_13_mastered_y_2026_03_14():
    """Tras la fila 13 (2026-01-13), S=8 y MASTERED => 30 x 2 = 60 => 2026-03-14."""
    history = daily("FFFCF" + "C" * 8)
    assert len(history) == 13
    assert history[-1].at.date() == datetime(2026, 1, 13).date()
    state = compute_state(OBJ, history, history[-1].at)
    assert state.level is Level.MASTERED
    assert trailing_success_run(history) == 8
    assert interval_days(8, Level.MASTERED) == MAX_INTERVAL_DAYS == 60
    assert state.next_review_at == datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
    assert state.next_review_at.date() == datetime(2026, 3, 14).date()
    assert state.is_due is False


@pytest.mark.spec
def test_ejemplo_4_3_fila_12_ya_mastered_pero_racha_7():
    """Fila 12: MASTERED con S=7 (>=5 => 30d) x2 = 60d => 2026-03-13.
    Comprueba que el techo, no el índice, gobierna el resultado."""
    history = daily("FFFCF" + "C" * 7)
    state = compute_state(OBJ, history, history[-1].at)
    assert state.level is Level.MASTERED
    assert state.next_review_at == history[-1].at + timedelta(days=MAX_INTERVAL_DAYS)


# ---------------------------------------------------------------------------
# §7 — casos límite
# ---------------------------------------------------------------------------


@pytest.mark.edge
@pytest.mark.parametrize("level", list(Level))
def test_c1_sin_intentos_next_review_none_y_no_vencido(level):
    """§4.2 punto 6 / C1: sin evidencia no hay repaso ni vencimiento."""
    assert compute_next_review([], level) is None
    assert is_due(compute_next_review([], level), T0) is False
    assert is_due(None, T0 + 3650 * DAY) is False


@pytest.mark.edge
def test_c1_sin_intentos_via_compute_state():
    state = compute_state(OBJ, [], T0)
    assert state.next_review_at is None
    assert state.is_due is False
    assert state.level is Level.UNASSESSED


@pytest.mark.edge
@pytest.mark.parametrize("correct", [True, False])
def test_c2_un_solo_intento_unassessed_pero_con_next_review(correct):
    history = [attempt(0, correct, T0)]
    assert len(history) < MIN_ATTEMPTS
    state = compute_state(OBJ, history, T0)
    assert state.level is Level.UNASSESSED
    assert state.score == 0.0
    assert state.total_attempts == 1
    # El repaso SÍ se calcula: S=1 (acierto) o S=0 (fallo), ambos 1 día.
    assert state.next_review_at == T0 + timedelta(days=SCHEDULE_DAYS[0])
    assert compute_next_review(history, Level.UNASSESSED) == state.next_review_at
    assert state.is_due is False
    assert is_due(state.next_review_at, T0 + DAY) is True


@pytest.mark.edge
def test_c5_hueco_largo_next_review_en_el_pasado_y_vencido():
    history = daily("C" * 8)
    last = history[-1].at
    for gap_days in (90, 365, 3650):
        as_of = last + gap_days * DAY
        state = compute_state(OBJ, history, as_of)
        # El repaso no depende de as_of: es last_attempt_at + intervalo.
        assert state.next_review_at == compute_next_review(history, state.level)
        assert state.next_review_at <= last + timedelta(days=MAX_INTERVAL_DAYS)
        assert state.next_review_at < as_of
        assert state.is_due is True
        assert (as_of - state.next_review_at) >= (gap_days - MAX_INTERVAL_DAYS) * DAY


@pytest.mark.edge
def test_c5_el_mas_vencido_es_el_de_mayor_hueco():
    """Base del orden de get_due (§5.2): a más hueco, next_review_at más antiguo."""
    recent = daily("C" * 3, start=T0 + 100 * DAY)
    old = daily("C" * 3, start=T0)
    as_of = T0 + 400 * DAY
    nr_recent = compute_next_review(recent, Level.LEARNING)
    nr_old = compute_next_review(old, Level.LEARNING)
    assert nr_old < nr_recent
    assert is_due(nr_old, as_of) and is_due(nr_recent, as_of)


# ---------------------------------------------------------------------------
# §6 I10 / §8 fallo 1 — ObjectiveState no expone streak
# ---------------------------------------------------------------------------

FORBIDDEN_FIELD_NAMES = {"streak", "racha", "success_run", "trailing_success_run"}


@pytest.mark.invariant
def test_i10_objective_state_no_tiene_campo_streak():
    names = {f.name for f in dataclasses.fields(ObjectiveState)}
    assert "streak" not in names
    assert not (names & FORBIDDEN_FIELD_NAMES)


@pytest.mark.invariant
def test_i10_grep_models_no_declara_streak_como_campo():
    """Grep automatizado sobre core/models.py: ninguna línea declara un campo
    llamado ``streak`` (``streak: <tipo>``). Mencionarlo en un docstring para
    decir que NO existe está permitido; declararlo, no."""
    source = Path(__file__).resolve().parent.parent / "core" / "models.py"
    text = source.read_text(encoding="utf-8")
    field_decl = re.compile(r"^\s*\w*streak\w*\s*:", re.IGNORECASE | re.MULTILINE)
    assert field_decl.search(text) is None, "core/models.py declara un campo streak"


@pytest.mark.invariant
def test_i10_fila_5_de_la_spec_es_indistinguible_de_nada_solo_con_racha():
    """El fallo 1 de §8, demostrado: la racha de la fila 5 es 0 y la de la fila
    4 es 1, pero el estado expone total_attempts, recent_window y score."""
    history = daily("FFFCF")
    assert trailing_success_run(history[:4]) == 1
    assert trailing_success_run(history) == 0
    state = compute_state(OBJ, history, history[-1].at)
    assert state.total_attempts == 5
    assert state.recent_window == (False, False, False, True, False)
    assert state.score == pytest.approx(4 / 15, abs=1e-6)
    assert not hasattr(state, "streak")


@pytest.mark.invariant
def test_i3_determinismo_del_repaso():
    history = daily("FCCFCC")
    first = compute_next_review(history, Level.LEARNING)
    for _ in range(5):
        assert compute_next_review(list(history), Level.LEARNING) == first
