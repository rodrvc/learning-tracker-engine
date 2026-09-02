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

from .clock import Clock
from .models import (
    Attempt,
    AttemptKind,
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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

    def session(self, session_id: str | None = None) -> SessionRecorder:
        """Abre una sesión de registro (SPEC §9.6).

        Úsese como context manager. Al cerrarse produce un
        :class:`~core.models.SessionReport`; si no se registró nada, el estado
        es ``EMPTY`` y queda constancia visible de que la sesión pasó en blanco
        (defensa contra el fallo 4).
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def get_state(
        self, objective_id: str, as_of: datetime | None = None
    ) -> ObjectiveState:
        """El estado completo de un objetivo en una fecha. SPEC §1.5."""
        raise NotImplementedError

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
        raise NotImplementedError

    def get_all_states(
        self, as_of: datetime | None = None
    ) -> list[ObjectiveState]:
        """El estado de todos los objetivos del perfil, por ``objective_id``."""
        raise NotImplementedError

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
        raise NotImplementedError

    def get_unstarted(
        self, as_of: datetime | None = None
    ) -> list[ObjectiveState]:
        """Objetivos sin ningún intento hasta ``as_of``.

        Hace visible el material no cubierto, que de otro modo es invisible:
        un objetivo sin intentos no genera ninguna señal por sí solo.
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

    def get_summary(self, as_of: datetime | None = None) -> ProfileSummary:
        """Agregado del perfil en una fecha. SPEC §9.4."""
        raise NotImplementedError

    def get_profile(self) -> Profile:
        """El perfil sobre el que opera este tracker."""
        raise NotImplementedError

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
        raise NotImplementedError

    def rebuild(self, as_of: datetime | None = None) -> int:
        """Recalcula toda proyección derivada desde el historial. SPEC I6.

        Como no se persiste ningún agregado, esto es una operación segura y
        repetible: cualquier caché o índice corrupto se arregla ejecutándola.
        Es la razón por la que el fallo 3 (contadores corrompidos e
        irreversibles) no tiene equivalente aquí.

        Returns:
            Cuántos objetivos se recalcularon.
        """
        raise NotImplementedError
