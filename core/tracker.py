"""El motor. Ver SPEC.md §9.4.

:class:`LearningTracker` es la fachada: orquesta store + reloj + cálculo puro.
No contiene reglas de negocio propias — las reglas están en ``leveling`` y
``scheduling``, y su especificación en SPEC §2 y §4.

Dos rasgos del diseño que conviene tener presentes al implementar:

* **Toda consulta acepta ``as_of``.** No existe una consulta "sin tiempo".
  ``as_of=None`` significa "usa ``clock.now()``", y el ``Clock`` lo eligió
  quien construyó el tracker: sigue siendo tiempo inyectado (SPEC I2).
* **Nada se cachea como verdad.** Si se añade una caché por rendimiento, debe
  cumplir I6: borrarla y recalcular produce un estado idéntico.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence
from uuid import uuid4

from .clock import Clock
from .constants import DEFAULT_STALE_DAYS
from .errors import DuplicateAttemptError, InvalidRangeError
from .leveling import compute_state
from .models import (
    Attempt,
    AttemptKind,
    ConsistencyCheck,
    ConsistencyReport,
    Level,
    ObjectiveState,
    Profile,
    ProfileSummary,
    StateComparison,
)
from .session import SessionRecorder
from .storage import AttemptStore, ProfileStore


class LearningTracker:
    """Motor de tracking sobre **un** perfil.

    Multi-perfil se consigue instanciando varios trackers sobre los mismos
    stores: los perfiles están aislados (SPEC I7), así que no se interfieren.

    Args:
        profile_id: perfil sobre el que opera esta instancia.
        profiles: store de perfiles y objetivos.
        attempts: store de intentos (append-only).
        clock: fuente de "ahora" para cuando no se pasa ``as_of`` explícito.
            En tests, un :class:`~core.clock.FixedClock`.
    """

    def __init__(
        self,
        profile_id: str,
        profiles: ProfileStore,
        attempts: AttemptStore,
        clock: Clock,
    ) -> None:
        self._profile_id = profile_id
        self._profiles = profiles
        self._attempts = attempts
        self._clock = clock

    @property
    def profile_id(self) -> str:
        """Perfil sobre el que opera este tracker."""
        return self._profile_id

    @property
    def clock(self) -> Clock:
        """El reloj inyectado, expuesto para colaboradores como ``SessionRecorder``.

        Solo lectura. Sigue siendo I2: el ``Clock`` lo eligió quien construyó
        el tracker; exponerlo no abre ninguna puerta al reloj de sistema.
        """
        return self._clock

    def _resolve(self, as_of: datetime | None) -> datetime:
        """``as_of`` explícito, o ``clock.now()`` si es ``None`` (SPEC §9.4)."""
        return self._clock.now() if as_of is None else as_of

    def _state(self, objective_id: str, as_of: datetime) -> ObjectiveState:
        """Envuelve :func:`compute_state` sobre lo que devuelve el store (I4).

        El corte es por ``at`` (``until=as_of``) y lo aplica el store; el
        tracker no recalcula nada por su cuenta.
        """
        history = self._attempts.list_for_objective(
            self._profile_id, objective_id, until=as_of
        )
        return compute_state(objective_id, history, as_of)

    # ---------------------------------------------------------------- escritura

    def record_attempt(
        self,
        objective_id: str,
        correct: bool,
        at: datetime,
        kind: AttemptKind = AttemptKind.QUIZ,
        confidence: float | None = None,
        note: str | None = None,
        attempt_id: str | None = None,
    ) -> Attempt:
        """Registra un intento con **fecha inyectada**.

        ``at`` es obligatorio y lo aporta quien llama: el motor jamás consulta
        el reloj para fabricarlo (SPEC I2). Es lo que permite a un bot escribir
        la serie "mal, mal, mal, bien, mal" en fechas arbitrarias y verificar la
        evolución sin esperar cinco días.

        El historial es append-only: este método es la **única** vía de entrada
        de datos, y no existe contrapartida para modificar ni borrar (SPEC I1).

        Args:
            objective_id: objetivo evaluado. Debe existir en el perfil.
            correct: acierto o fallo.
            at: cuándo ocurrió, aware. Puede ser anterior a intentos ya
                registrados: insertar fuera de orden es legal (SPEC C4).
            kind: naturaleza de la evidencia.
            confidence: autoevaluación 0.0-1.0. No afecta al nivel en v1.
            note: texto libre.
            attempt_id: id explícito; si es ``None`` se genera uno único.

        Returns:
            El :class:`Attempt` tal como quedó persistido, con su id. Devolver
            el objeto escrito (y no ``None``) es lo que hace que un registro
            fallido sea imposible de confundir con uno exitoso (SPEC I8).

        Raises:
            UnknownObjectiveError: el objetivo no existe. **No se autocrea**
                (SPEC C8).
            DuplicateAttemptError: ese ``attempt_id`` ya existe (SPEC C9).
            InvalidAttemptError: ``at`` naive, o ``confidence`` fuera de rango.
            StorageError: la escritura no se pudo completar.
        """
        # C8: el objetivo debe existir. get_objective lanza si no; jamás se
        # autocrea.
        self._profiles.get_objective(self._profile_id, objective_id)
        if attempt_id is None:
            attempt_id = uuid4().hex
        elif self._attempts.exists(attempt_id):
            # C9: el store también lo rechaza, pero se comprueba aquí para que
            # el contrato no dependa del backend.
            raise DuplicateAttemptError(attempt_id)
        attempt = Attempt(
            attempt_id=attempt_id,
            objective_id=objective_id,
            at=at,
            correct=correct,
            kind=kind,
            confidence=confidence,
            note=note,
            recorded_at=self._clock.now(),
        )
        # I8: si append falla, la excepción se propaga. Nunca se devuelve None.
        return self._attempts.append(self._profile_id, attempt)

    def record_series(
        self,
        objective_id: str,
        results: Sequence[bool],
        start: datetime,
        step: timedelta = timedelta(days=1),
        kind: AttemptKind = AttemptKind.QUIZ,
    ) -> list[Attempt]:
        """Registra una serie deliberada de resultados en fechas espaciadas.

        Atajo pensado para el bot de verificación y para los tests: la serie
        ``[False, False, False, True, False]`` desde una fecha dada reproduce
        exactamente el ejemplo recorrido en SPEC §3.

        Args:
            objective_id: objetivo evaluado.
            results: aciertos/fallos en orden cronológico.
            start: fecha del primer intento, aware.
            step: separación entre intentos consecutivos.
            kind: naturaleza de la evidencia para todos ellos.

        Returns:
            Los intentos creados, en orden.
        """
        return [
            self.record_attempt(
                objective_id, correct=result, at=start + step * index, kind=kind
            )
            for index, result in enumerate(results)
        ]

    def session(self, session_id: str | None = None) -> SessionRecorder:
        """Abre una sesión de registro (SPEC §9.6).

        Úsese como context manager. Al cerrarse produce un
        :class:`~core.models.SessionReport`; si no se registró nada, el estado
        es ``EMPTY`` y queda constancia visible de que la sesión pasó en blanco
        (defensa contra el fallo 4).
        """
        return SessionRecorder(self, session_id=session_id)

    # ---------------------------------------------------------------- consulta

    def get_level(
        self, objective_id: str, as_of: datetime | None = None
    ) -> Level:
        """El nivel de un objetivo en una fecha. SPEC §2.

        Args:
            objective_id: objetivo consultado.
            as_of: fecha de corte; ``None`` usa ``clock.now()``.

        Raises:
            UnknownObjectiveError: si el objetivo no existe en el perfil. Un
                objetivo que existe pero no tiene intentos **no** es un error:
                devuelve ``UNASSESSED`` (SPEC C1).
        """
        return self.get_state(objective_id, as_of).level

    def get_state(
        self, objective_id: str, as_of: datetime | None = None
    ) -> ObjectiveState:
        """El estado completo de un objetivo en una fecha. SPEC §1.5."""
        self._profiles.get_objective(self._profile_id, objective_id)
        return self._state(objective_id, self._resolve(as_of))

    def get_state_at(
        self, objective_id: str, as_of: datetime
    ) -> ObjectiveState:
        """El estado **tal como era** en una fecha pasada. SPEC §5.1.

        Idéntico a :meth:`get_state` salvo que ``as_of`` es obligatorio: existe
        como método propio para que la consulta histórica sea explícita en el
        código que la usa, y no un parámetro que se olvida.

        Garantías (SPEC §5.1):

        * Ignora por completo los intentos con ``at > as_of``.
        * El resultado no cambia por registrar intentos posteriores: lo pasado
          no se reescribe.
        * Es insensible al orden en que se escribieron los intentos.

        Es posible únicamente porque el historial es append-only y el nivel se
        recalcula en cada consulta; un sistema con nivel almacenado no puede
        responder esta pregunta.
        """
        return self.get_state(objective_id, as_of)

    def get_all_states(
        self, as_of: datetime | None = None
    ) -> list[ObjectiveState]:
        """El estado de todos los objetivos del perfil, por ``objective_id``."""
        moment = self._resolve(as_of)
        return [
            self._state(objective.objective_id, moment)
            for objective in self._profiles.list_objectives(self._profile_id)
        ]

    def get_due(
        self, as_of: datetime | None = None, limit: int | None = None
    ) -> list[ObjectiveState]:
        """Qué toca repasar en una fecha. SPEC §5.2.

        Ordenados por urgencia: primero los más vencidos; a igualdad, el
        ``score`` más bajo; a igualdad, ``objective_id`` ascendente. El tercer
        criterio existe para que el orden sea totalmente determinista.

        Los objetivos **sin intentos no aparecen aquí**: usar
        :meth:`get_unstarted`. Mezclar "nunca lo he visto" con "toca repasarlo"
        oculta el material sin cubrir.
        """
        moment = self._resolve(as_of)
        due = [s for s in self.get_all_states(moment) if s.is_due]
        # is_due garantiza next_review_at no nulo. Más vencido = mayor
        # (as_of - next_review_at); se ordena por su negativo ascendente.
        due.sort(
            key=lambda s: (
                -(moment - s.next_review_at),  # type: ignore[operator]
                s.score,
                s.objective_id,
            )
        )
        return due if limit is None else due[:limit]

    def get_unstarted(
        self, as_of: datetime | None = None
    ) -> list[ObjectiveState]:
        """Objetivos sin ningún intento hasta ``as_of``.

        Hace visible el material no cubierto, que de otro modo es invisible:
        un objetivo sin intentos no genera ninguna señal por sí solo.
        """
        return [s for s in self.get_all_states(as_of) if s.total_attempts == 0]

    def get_stale(
        self, as_of: datetime | None = None, days: int | None = None
    ) -> list[ObjectiveState]:
        """Objetivos sin actividad en los últimos ``days`` días.

        Segunda capa de defensa contra el fallo 4: si nadie registra nada, el
        estado no se queda congelado en silencio, sino que los objetivos van
        apareciendo en esta lista. Un sistema que no registra se delata solo.

        Args:
            as_of: fecha de corte; ``None`` usa ``clock.now()``.
            days: umbral de inactividad; ``None`` usa ``DEFAULT_STALE_DAYS``.
        """
        threshold = DEFAULT_STALE_DAYS if days is None else days
        # Solo objetivos con historial: los que nunca tuvieron intentos van en
        # get_unstarted (SPEC §8, fallo 4, capa 2).
        return [
            s
            for s in self.get_all_states(as_of)
            if s.days_since_last is not None and s.days_since_last > threshold
        ]

    def get_timeline(
        self,
        objective_id: str,
        start: datetime,
        end: datetime,
        step: timedelta = timedelta(days=1),
    ) -> list[ObjectiveState]:
        """Serie temporal de estados sobre una rejilla de fechas. SPEC §5.3.

        Es :meth:`get_state_at` en bucle. Existe para que la UI pueda graficar
        la evolución sin reimplementar el corte temporal, que es donde es fácil
        equivocarse.

        Raises:
            InvalidRangeError: si ``start > end`` o ``step <= 0``.
        """
        if start > end:
            raise InvalidRangeError(f"start > end: {start} > {end}")
        if step <= timedelta(0):
            raise InvalidRangeError(f"step debe ser positivo: {step}")
        self._profiles.get_objective(self._profile_id, objective_id)
        states: list[ObjectiveState] = []
        moment = start
        while moment <= end:
            states.append(self._state(objective_id, moment))
            moment += step
        return states

    def compare_states(
        self, objective_id: str, earlier: datetime, later: datetime
    ) -> StateComparison:
        """Compara el objetivo en dos fechas. SPEC §5.1.

        La respuesta directa a *"¿hace dos semanas estaba mejor que esta
        semana?"*: llamar con ``earlier = hoy - 14d`` y ``later = hoy`` y mirar
        ``improved`` / ``regressed``.

        Raises:
            InvalidRangeError: si ``earlier > later``.
        """
        if earlier > later:
            raise InvalidRangeError(f"earlier > later: {earlier} > {later}")
        before = self.get_state(objective_id, earlier)
        after = self.get_state(objective_id, later)
        score_delta = after.score - before.score
        return StateComparison(
            objective_id=objective_id,
            earlier=before,
            later=after,
            level_delta=int(after.level) - int(before.level),
            score_delta=score_delta,
            improved=score_delta > 0,
            regressed=score_delta < 0,
        )

    def get_summary(self, as_of: datetime | None = None) -> ProfileSummary:
        """Agregado del perfil en una fecha. SPEC §9.4."""
        moment = self._resolve(as_of)
        states = self.get_all_states(moment)
        by_level = {level: 0 for level in Level}
        for state in states:
            by_level[state.level] += 1
        total = len(states)
        assessed = total - by_level[Level.UNASSESSED]
        return ProfileSummary(
            profile_id=self._profile_id,
            as_of=moment,
            total_objectives=total,
            by_level=by_level,
            assessed_objectives=assessed,
            unstarted_objectives=sum(1 for s in states if s.total_attempts == 0),
            due_objectives=sum(1 for s in states if s.is_due),
            total_attempts=len(self._attempts.list_all(self._profile_id, until=moment)),
            mean_score=(sum(s.score for s in states) / total) if total else 0.0,
            coverage=(assessed / total) if total else 0.0,
        )

    def get_profile(self) -> Profile:
        """El perfil sobre el que opera este tracker."""
        return self._profiles.get_profile(self._profile_id)

    # ------------------------------------------------------------ verificación

    def check_consistency(
        self, as_of: datetime | None = None
    ) -> ConsistencyReport:
        """Verifica que el store y el recálculo coinciden. SPEC §8, fallo 2.

        Compara **conteos y sumas**, nunca pertenencia a conjuntos (SPEC I9):
        comparar conjuntos deja pasar duplicados y desajustes de cardinalidad,
        que es precisamente cómo el verificador anterior llegó a imprimir
        "OK · consistente" sobre un estado corrupto.

        Comprobaciones mínimas exigidas por el contrato, por objetivo y para el
        perfil entero:

        * número de intentos en el store == número de intentos recalculados;
        * suma de aciertos en el store == suma recalculada;
        * ningún ``attempt_id`` duplicado (se compara ``count`` con el número
          de ids únicos: si difieren, hay duplicados);
        * todo intento apunta a un ``objective_id`` que existe en el perfil.

        Returns:
            Un :class:`ConsistencyReport` con los números de ambos lados de
            cada comparación. ``ok`` es ``True`` solo si todos los checks
            pasaron **y** se comprobó al menos un objetivo: no haber
            encontrado errores por no haber mirado nada no es estar bien.
        """
        moment = self._resolve(as_of)
        profile = self._profiles.get_profile(self._profile_id)
        objectives = self._profiles.list_objectives(self._profile_id)
        # Lado "store": la lectura global del perfil, agrupada por objetivo.
        # Lado "recalculado": compute_state sobre la lectura por objetivo.
        # Son dos caminos de lectura distintos; se comparan sus NUMEROS (I9).
        listed = self._attempts.list_all(self._profile_id, until=moment)
        count_by_objective: dict[str, int] = {}
        correct_by_objective: dict[str, int] = {}
        for attempt in listed:
            count_by_objective[attempt.objective_id] = (
                count_by_objective.get(attempt.objective_id, 0) + 1
            )
            correct_by_objective[attempt.objective_id] = (
                correct_by_objective.get(attempt.objective_id, 0)
                + int(attempt.correct)
            )

        checks: list[ConsistencyCheck] = []

        def add(name: str, expected: float, actual: float, detail: str) -> None:
            checks.append(
                ConsistencyCheck(
                    name=name,
                    expected=expected,
                    actual=actual,
                    passed=expected == actual,
                    detail=detail,
                )
            )

        recalculated_total = 0
        recalculated_correct = 0
        for objective in objectives:
            oid = objective.objective_id
            state = self._state(oid, moment)
            recalculated_total += state.total_attempts
            recalculated_correct += state.correct_attempts
            add(
                "attempt_count",
                state.total_attempts,
                count_by_objective.get(oid, 0),
                f"{oid}: intentos recalculados vs listados en el store",
            )
            add(
                "correct_sum",
                state.correct_attempts,
                correct_by_objective.get(oid, 0),
                f"{oid}: aciertos recalculados vs sumados en el store",
            )

        # Perfil entero.
        add(
            "profile_attempt_count",
            recalculated_total,
            len(listed),
            "suma de intentos recalculados vs list_all del store",
        )
        add(
            "profile_correct_sum",
            recalculated_correct,
            sum(1 for a in listed if a.correct),
            "suma de aciertos recalculados vs list_all del store",
        )
        # count() del store contra su propia lectura completa (sin corte:
        # count no acepta as_of). Detecta un contador que miente.
        everything = self._attempts.list_all(self._profile_id)
        add(
            "store_count",
            len(everything),
            self._attempts.count(self._profile_id),
            "len(list_all) vs count() del store",
        )
        add(
            "unique_attempt_ids",
            len(everything),
            len({a.attempt_id for a in everything}),
            "intentos vs attempt_id únicos: si difieren, hay duplicados",
        )
        add(
            "orphan_attempts",
            0,
            sum(1 for a in everything if a.objective_id not in profile.objectives),
            "intentos cuyo objective_id no existe en el perfil",
        )

        checked = len(objectives)
        return ConsistencyReport(
            ok=checked >= 1 and all(c.passed for c in checks),
            checks=tuple(checks),
            objectives_checked=checked,
            as_of=moment,
        )

    def rebuild(self, as_of: datetime | None = None) -> int:
        """Recalcula toda proyección derivada desde el historial. SPEC I6.

        Como no se persiste ningún agregado, esto es una operación segura y
        repetible: cualquier caché o índice corrupto se arregla ejecutándola.
        Es la razón por la que el fallo 3 (contadores corrompidos e
        irreversibles) no tiene equivalente aquí.

        Returns:
            Cuántos objetivos se recalcularon.
        """
        # No hay caché ni índice que borrar: el estado siempre se deriva del
        # historial (I4). Recalcular todo es la operación completa, y devolver
        # el conteo deja constancia de que se recorrió el perfil entero.
        return len(self.get_all_states(as_of))
