"""El modelo de datos. Ver SPEC.md §1.

Todas las estructuras son ``dataclass(frozen=True)``: inmutables por
construcción. Un ``Attempt`` que no se puede mutar no se puede corromper, y el
historial append-only (SPEC I1) deja de depender de la disciplina de quien
programa.

Distinción clave que atraviesa todo el módulo:

* :class:`Attempt` es un **hecho persistido**. Se escribe una vez y no cambia.
* :class:`ObjectiveState` es una **proyección calculada**. Nunca se persiste;
  se recalcula desde los intentos cada vez que se pide (SPEC I4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum


class AttemptKind(str, Enum):
    """De qué tipo de evidencia procede un intento.

    No afecta al cálculo del nivel en v1 (SPEC §10); sirve para filtrar y para
    auditar de dónde salió una afirmación sobre el progreso.
    """

    QUIZ = "quiz"
    EXERCISE = "exercise"
    LAB = "lab"
    EXAM_SIM = "exam_sim"
    SELF_REPORT = "self_report"


class Level(IntEnum):
    """Nivel de dominio de un objetivo. Ver SPEC §1.4.

    Es un ``IntEnum`` **ordenado** a propósito: comparar dos niveles con ``<``
    debe funcionar, porque la pregunta central del usuario ("¿estaba mejor hace
    dos semanas?") es literalmente una comparación.
    """

    UNASSESSED = 0
    WEAK = 1
    LEARNING = 2
    COMPETENT = 3
    MASTERED = 4


class SessionStatus(str, Enum):
    """Cómo terminó una sesión de registro (SPEC §9.6)."""

    #: Se registró al menos un intento.
    RECORDED = "recorded"
    #: La sesión se cerró sin registrar nada. Visible a propósito: es la
    #: señal de que alguien olvidó registrar (SPEC §8, fallo 4).
    EMPTY = "empty"


@dataclass(frozen=True)
class Objective:
    """Una unidad de conocimiento evaluable. Ver SPEC §1.2.

    Obsérvese lo que **no** tiene: ni nivel, ni racha, ni contadores, ni fecha
    de repaso. Todo eso son proyecciones del historial y vive en
    :class:`ObjectiveState`. Si algún día aparece aquí un campo mutable de
    progreso, el fallo 3 (contadores corruptos e irreversibles) vuelve a ser
    posible.

    Attributes:
        objective_id: único dentro del perfil. Ej. ``"D3.2-content-understanding"``.
        title: descripción legible para un humano.
        domain: agrupación opcional. Ej. ``"D3"``.
        weight: peso relativo en el examen. Informativo; no afecta al nivel.
        tags: etiquetas libres para filtrar.
    """

    objective_id: str
    title: str
    domain: str | None = None
    weight: float = 1.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    """Un tema de estudio con sus objetivos. Ver SPEC §1.1.

    Los perfiles están aislados entre sí (SPEC I7): ningún intento de un perfil
    influye en el estado de otro. Multi-perfil no es requisito hoy, pero este
    aislamiento hace que añadirlo no obligue a rediseñar nada.

    Attributes:
        profile_id: identificador estable. Ej. ``"ai-103"``.
        name: nombre legible.
        objectives: objetivos indexados por ``objective_id``.
    """

    profile_id: str
    name: str
    objectives: dict[str, Objective] = field(default_factory=dict)


@dataclass(frozen=True)
class Attempt:
    """Un hecho ocurrido: en tal fecha se respondió bien o mal. Ver SPEC §1.3.

    **Inmutable y append-only.** No existe API para modificarlo ni borrarlo
    (SPEC I1). Es el único dato que se persiste como verdad; todo lo demás se
    deriva de una colección de estos.

    ``at`` lo aporta quien registra, nunca el motor: eso es lo que permite a un
    bot simular "mal, mal, mal, bien, mal" en fechas arbitrarias y lo que hacía
    imposible el fallo 5.

    Attributes:
        attempt_id: identificador único e inmutable. Un duplicado es error.
        objective_id: objetivo al que pertenece.
        at: **cuándo ocurrió**, aware (con ``tzinfo``). Es el eje de ordenación
            y de todo corte temporal.
        correct: ``True`` acierto, ``False`` fallo. Único eje binario.
        kind: naturaleza de la evidencia.
        confidence: autoevaluación 0.0-1.0. No afecta al nivel en v1.
        note: texto libre (el enunciado, por qué falló...).
        recorded_at: cuándo se escribió en el store, si difiere de ``at``.
            Solo auditoría; **jamás** se usa para ordenar ni para cortar, de
            modo que insertar fuera de orden no altere resultados (SPEC C4).
    """

    attempt_id: str
    objective_id: str
    at: datetime
    correct: bool
    kind: AttemptKind = AttemptKind.QUIZ
    confidence: float | None = None
    note: str | None = None
    recorded_at: datetime | None = None


@dataclass(frozen=True)
class ObjectiveState:
    """El estado derivado de un objetivo en una fecha. Ver SPEC §1.5.

    **Nunca se persiste.** Es siempre el resultado de recalcular desde los
    intentos con ``at <= as_of`` (SPEC I4, I6). Por eso una corrupción de datos
    agregados es irrelevante: se borra y se vuelve a calcular.

    No existe ni existirá un campo ``streak`` (SPEC I10). El progreso se lee en
    ``score`` (continuo, ponderado por recencia), en los contadores acumulados
    y en ``recent_window`` (la secuencia literal). Un objetivo con 5 respuestas
    mixtas muestra aquí los 5 intentos y un score intermedio, no un "1" que
    parece que no se guardó nada.

    Attributes:
        objective_id: a qué objetivo corresponde.
        as_of: fecha de corte con la que se calculó. Sin esto el estado no
            significa nada: todo estado es estado *en una fecha*.
        level: nivel según SPEC §2.
        score: puntuación continua 0.0-1.0 que produjo el nivel. Distingue dos
            objetivos del mismo nivel y hace visible una mejora que aún no
            cruzó umbral.
        total_attempts: intentos con ``at <= as_of``. Solo crece.
        correct_attempts: cuántos de ellos fueron acierto.
        recent_window: los últimos ``WINDOW`` resultados, **del más antiguo al
            más reciente**. El orden importa: los pesos son posicionales.
        first_attempt_at: primer intento hasta ``as_of``, o ``None``.
        last_attempt_at: último intento hasta ``as_of``, o ``None``.
        distinct_days: días naturales distintos con al menos un intento.
            Dos intentos el mismo día cuentan uno (SPEC C3).
        days_since_last: días fraccionarios entre el último intento y ``as_of``.
            Es el ``gap`` que alimenta el decaimiento.
        retention: factor de decaimiento aplicado, en (0.0, 1.0].
        next_review_at: próximo repaso según SPEC §4, o ``None`` si no hay
            intentos.
        is_due: ``next_review_at is not None and next_review_at <= as_of``.
    """

    objective_id: str
    as_of: datetime
    level: Level
    score: float
    total_attempts: int
    correct_attempts: int
    recent_window: tuple[bool, ...]
    first_attempt_at: datetime | None
    last_attempt_at: datetime | None
    distinct_days: int
    days_since_last: float | None
    retention: float
    next_review_at: datetime | None
    is_due: bool


@dataclass(frozen=True)
class StateComparison:
    """Dos estados del mismo objetivo en dos fechas. Ver SPEC §5.1.

    Existe para responder de forma directa la pregunta que el usuario puso como
    requisito: *"¿hace dos semanas estaba mejor que esta semana?"*.

    Attributes:
        objective_id: objetivo comparado.
        earlier: estado en la fecha anterior.
        later: estado en la fecha posterior.
        level_delta: ``later.level - earlier.level``. Positivo = mejoró.
        score_delta: ``later.score - earlier.score``.
        improved: ``score_delta > 0``.
        regressed: ``score_delta < 0``.
    """

    objective_id: str
    earlier: ObjectiveState
    later: ObjectiveState
    level_delta: int
    score_delta: float
    improved: bool
    regressed: bool


@dataclass(frozen=True)
class ProfileSummary:
    """Agregado del perfil en una fecha. Ver SPEC §9.4.

    Attributes:
        profile_id: perfil resumido.
        as_of: fecha de corte.
        total_objectives: objetivos definidos en el perfil.
        by_level: cuántos objetivos hay en cada nivel. Cubre los cinco niveles,
            con 0 donde no haya ninguno.
        assessed_objectives: objetivos con nivel distinto de ``UNASSESSED``.
        unstarted_objectives: objetivos sin ningún intento.
        due_objectives: objetivos vencidos para repaso.
        total_attempts: intentos registrados en todo el perfil hasta ``as_of``.
        mean_score: media aritmética del ``score`` de todos los objetivos.
        coverage: ``assessed_objectives / total_objectives``, en [0.0, 1.0].
    """

    profile_id: str
    as_of: datetime
    total_objectives: int
    by_level: dict[Level, int]
    assessed_objectives: int
    unstarted_objectives: int
    due_objectives: int
    total_attempts: int
    mean_score: float
    coverage: float


@dataclass(frozen=True)
class ConsistencyCheck:
    """Una comprobación individual de consistencia. Ver SPEC §9.5.

    ``expected`` y ``actual`` son **números** (conteos o sumas), no conjuntos.
    Esa es la corrección del fallo 2: comparar pertenencia deja pasar
    duplicados y desajustes de cardinalidad; comparar conteos, no.

    Attributes:
        name: qué se comprobó. Ej. ``"attempt_count"``.
        expected: valor esperado, recalculado desde el historial.
        actual: valor observado en el store.
        passed: ``expected == actual``. Sin tolerancia para enteros.
        detail: contexto legible cuando falla.
    """

    name: str
    expected: float
    actual: float
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class ConsistencyReport:
    """Resultado del chequeo de consistencia. Ver SPEC §8, fallo 2.

    No es un booleano ni una cadena "OK": lleva los números de ambos lados de
    cada comparación, para que un desajuste sea imposible de imprimir como
    correcto.

    ``ok`` se define de forma **positiva**: todos los checks pasaron *y* se
    comprobó al menos un objetivo. No haber encontrado errores porque no se
    comprobó nada **no** es ``ok``.

    Attributes:
        ok: ver arriba.
        checks: cada comparación realizada, con sus números.
        objectives_checked: cuántos objetivos se recorrieron.
        as_of: fecha de corte del chequeo.
    """

    ok: bool
    checks: tuple[ConsistencyCheck, ...]
    objectives_checked: int
    as_of: datetime

    @property
    def failures(self) -> tuple[ConsistencyCheck, ...]:
        """Solo los checks que no pasaron."""
        raise NotImplementedError


@dataclass(frozen=True)
class SessionReport:
    """Qué pasó en una sesión de registro. Ver SPEC §9.6.

    Su razón de ser es el fallo 4: cerrar una sesión sin haber registrado nada
    produce ``status=EMPTY``, un resultado explícito y visible, en vez de un
    silencio indistinguible de "todo bien".

    Attributes:
        session_id: identificador de la sesión.
        started_at: instante de apertura (inyectado).
        ended_at: instante de cierre (inyectado).
        attempts_recorded: cuántos intentos se escribieron.
        objectives_touched: ids de los objetivos con al menos un intento.
        status: ``RECORDED`` o ``EMPTY``.
    """

    session_id: str
    started_at: datetime
    ended_at: datetime | None
    attempts_recorded: int
    objectives_touched: tuple[str, ...]
    status: SessionStatus
