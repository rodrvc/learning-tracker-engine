"""CLI de visualización del progreso. Único punto del proyecto con libertad de diseño.

Solo biblioteca estándar (``argparse``). Regla estructural: para todo lo que
sea nivel, estado o repaso, ``ui/`` consume **exclusivamente** la API pública
de :class:`~core.tracker.LearningTracker`. No recalcula niveles, no importa
``core.leveling`` ni ``core.scheduling`` y no lee intentos del
``AttemptStore`` por su cuenta: hacerlo abriría una puerta trasera a I4. El
``ProfileStore`` sí se usa directamente para crear perfiles y objetivos, que
no es cálculo.

El tiempo se inyecta (SPEC I2): :func:`run` recibe un ``Clock``; si no se
pasa ninguno se usa :class:`store.SystemClock`, y **solo** ``ui/`` lo
instancia. ``--as-of`` fija la fecha de consulta; si falta, ``clock.now()``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence, TextIO

from core.clock import Clock
from core.errors import TrackerError, UnknownProfileError
from core.models import (
    AttemptKind,
    ConsistencyReport,
    Level,
    Objective,
    ObjectiveState,
    Profile,
    ProfileSummary,
    StateComparison,
)
from core.tracker import LearningTracker
from store import JsonAttemptStore, JsonProfileStore, SystemClock

#: Códigos de salida. 1 se reserva a ``check`` con ``ok=False``.
EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_ERROR = 2

PROFILES_FILE = "profiles.json"
ATTEMPTS_FILE = "attempts.json"
DEFAULT_DATA_DIR = "./data"

#: Comandos que no operan sobre un perfil concreto (no exigen ``--profile``).
_PROFILE_FREE_COMMANDS = frozenset({"profile"})


class UsageError(Exception):
    """Argumentos inválidos. Se imprime en stderr y termina con código 2."""


class _Parser(argparse.ArgumentParser):
    """``ArgumentParser`` que no escribe en ``sys.stderr`` ni llama a ``exit``.

    Los errores de uso se convierten en :class:`UsageError` para que
    :func:`run` los enrute al ``stderr`` inyectado.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(f"{self.format_usage().rstrip()}\n{self.prog}: {message}")


# ------------------------------------------------------------------ parseo


def parse_iso(raw: str, name: str = "fecha") -> datetime:
    """Parsea una fecha ISO 8601. Una fecha sin zona horaria se asume UTC.

    Se acepta el sufijo ``Z`` (Python 3.10 no lo entiende en
    ``fromisoformat``). La asunción de UTC es una comodidad de la CLI: el motor
    exige fechas aware (SPEC §1.3) y la CLI se lo garantiza.
    """
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise UsageError(f"{name} no es ISO 8601 válido: {raw!r}") from None
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"debe ser un entero positivo: {raw!r}")
    return value


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"no puede ser negativo: {raw!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser completo (opciones globales + subcomandos)."""
    parser = _Parser(
        prog="learning-tracker",
        description="Visualización del progreso de aprendizaje (SPEC.md §5).",
    )
    parser.add_argument(
        "--data",
        default=DEFAULT_DATA_DIR,
        metavar="DIR",
        help=f"directorio de los stores JSON (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--profile",
        metavar="ID",
        help="perfil sobre el que operar (obligatorio salvo en 'profile')",
    )
    parser.add_argument(
        "--as-of",
        metavar="ISO8601",
        help="fecha de consulta; si falta se usa el reloj",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMANDO")
    sub.required = True

    # profile create|list
    p_profile = sub.add_parser("profile", help="gestión de perfiles")
    profile_sub = p_profile.add_subparsers(dest="profile_command", metavar="ACCION")
    profile_sub.required = True
    p_create = profile_sub.add_parser("create", help="crea un perfil nuevo")
    p_create.add_argument("profile_id", metavar="ID")
    p_create.add_argument("--name", required=True, help="nombre legible")
    profile_sub.add_parser("list", help="lista los perfiles existentes")

    # objective add
    p_objective = sub.add_parser("objective", help="gestión de objetivos")
    objective_sub = p_objective.add_subparsers(dest="objective_command", metavar="ACCION")
    objective_sub.required = True
    p_add = objective_sub.add_parser("add", help="añade (o reemplaza) un objetivo")
    p_add.add_argument("objective_id", metavar="OBJECTIVE_ID")
    p_add.add_argument("--title", required=True, help="descripción legible")
    p_add.add_argument("--domain", default=None, help="agrupación opcional")
    p_add.add_argument("--weight", type=float, default=1.0, help="peso informativo")

    sub.add_parser("objectives", help="lista los objetivos del perfil con su nivel")

    # record
    p_record = sub.add_parser("record", help="registra un intento (fecha inyectada)")
    p_record.add_argument("objective_id", metavar="OBJECTIVE_ID")
    result = p_record.add_mutually_exclusive_group(required=True)
    result.add_argument("--correct", action="store_true", help="acierto")
    result.add_argument("--wrong", action="store_true", help="fallo")
    p_record.add_argument(
        "--at", metavar="ISO8601", help="cuándo ocurrió; default: --as-of o el reloj"
    )
    p_record.add_argument(
        "--kind",
        choices=[k.value for k in AttemptKind],
        default=AttemptKind.QUIZ.value,
        help="naturaleza de la evidencia",
    )
    p_record.add_argument("--confidence", type=float, default=None, help="0.0-1.0")
    p_record.add_argument("--note", default=None, help="texto libre")
    p_record.add_argument("--id", dest="attempt_id", default=None, help="attempt_id explícito")

    # consultas
    p_state = sub.add_parser("state", help="estado completo de un objetivo")
    p_state.add_argument("objective_id", metavar="OBJECTIVE_ID")

    p_due = sub.add_parser("due", help="qué toca repasar, por urgencia")
    p_due.add_argument("--limit", type=_positive_int, default=None, metavar="N")

    sub.add_parser("unstarted", help="objetivos sin ningún intento")

    p_stale = sub.add_parser("stale", help="objetivos sin actividad reciente")
    p_stale.add_argument("--days", type=_non_negative_int, default=None, metavar="N")

    sub.add_parser("summary", help="agregado del perfil")

    p_timeline = sub.add_parser("timeline", help="serie temporal de un objetivo")
    p_timeline.add_argument("objective_id", metavar="OBJECTIVE_ID")
    p_timeline.add_argument("--start", required=True, metavar="ISO8601")
    p_timeline.add_argument("--end", required=True, metavar="ISO8601")
    p_timeline.add_argument("--step-days", type=_positive_int, default=1, metavar="N")

    p_compare = sub.add_parser("compare", help="compara el objetivo en dos fechas")
    p_compare.add_argument("objective_id", metavar="OBJECTIVE_ID")
    p_compare.add_argument("--earlier", required=True, metavar="ISO8601")
    p_compare.add_argument("--later", required=True, metavar="ISO8601")

    sub.add_parser("check", help="chequeo de consistencia (exit 1 si falla)")

    return parser


# ------------------------------------------------------------------ formato


def _fmt_dt(moment: datetime | None) -> str:
    return "-" if moment is None else moment.isoformat()


def _fmt_float(value: float | None, digits: int = 4) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _fmt_bool(value: bool) -> str:
    return "si" if value else "no"


def _fmt_window(window: Sequence[bool]) -> str:
    """Ventana reciente, del más antiguo al más reciente: ``+`` acierto, ``-`` fallo."""
    return "".join("+" if hit else "-" for hit in window) or "-"


def _fmt_level(level: Level) -> str:
    return f"{level.name} ({int(level)})"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Tabla de texto plano con columnas de ancho fijo, separadas por dos espacios."""
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()
    rule = "  ".join("-" * w for w in widths)
    body = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        for row in rows
    ]
    return "\n".join([line, rule, *body])


def _kv(pairs: Sequence[tuple[str, str]]) -> str:
    width = max(len(key) for key, _ in pairs)
    return "\n".join(f"{key.ljust(width)}  {value}" for key, value in pairs)


_STATE_HEADERS = ("objective_id", "level", "score", "attempts", "correct", "window", "last_attempt_at", "next_review_at", "due")


def _state_row(state: ObjectiveState) -> tuple[str, ...]:
    return (
        state.objective_id,
        state.level.name,
        _fmt_float(state.score),
        str(state.total_attempts),
        str(state.correct_attempts),
        _fmt_window(state.recent_window),
        _fmt_dt(state.last_attempt_at),
        _fmt_dt(state.next_review_at),
        _fmt_bool(state.is_due),
    )


def _states_table(states: Sequence[ObjectiveState]) -> str:
    return _table(_STATE_HEADERS, [_state_row(s) for s in states])


def format_state(state: ObjectiveState) -> str:
    return _kv(
        [
            ("objective_id", state.objective_id),
            ("as_of", _fmt_dt(state.as_of)),
            ("level", _fmt_level(state.level)),
            ("score", _fmt_float(state.score)),
            ("total_attempts", str(state.total_attempts)),
            ("correct_attempts", str(state.correct_attempts)),
            ("recent_window", _fmt_window(state.recent_window)),
            ("first_attempt_at", _fmt_dt(state.first_attempt_at)),
            ("last_attempt_at", _fmt_dt(state.last_attempt_at)),
            ("distinct_days", str(state.distinct_days)),
            ("days_since_last", _fmt_float(state.days_since_last, 2)),
            ("retention", _fmt_float(state.retention)),
            ("next_review_at", _fmt_dt(state.next_review_at)),
            ("is_due", _fmt_bool(state.is_due)),
        ]
    )


def format_summary(summary: ProfileSummary) -> str:
    head = _kv(
        [
            ("profile_id", summary.profile_id),
            ("as_of", _fmt_dt(summary.as_of)),
            ("total_objectives", str(summary.total_objectives)),
            ("assessed_objectives", str(summary.assessed_objectives)),
            ("unstarted_objectives", str(summary.unstarted_objectives)),
            ("due_objectives", str(summary.due_objectives)),
            ("total_attempts", str(summary.total_attempts)),
            ("mean_score", _fmt_float(summary.mean_score)),
            ("coverage", _fmt_float(summary.coverage)),
        ]
    )
    levels = _table(
        ("level", "objectives"),
        [(_fmt_level(level), str(summary.by_level.get(level, 0))) for level in Level],
    )
    return f"{head}\n\n{levels}"


def format_comparison(comparison: StateComparison) -> str:
    earlier, later = comparison.earlier, comparison.later
    rows = [
        ("as_of", _fmt_dt(earlier.as_of), _fmt_dt(later.as_of)),
        ("level", _fmt_level(earlier.level), _fmt_level(later.level)),
        ("score", _fmt_float(earlier.score), _fmt_float(later.score)),
        ("total_attempts", str(earlier.total_attempts), str(later.total_attempts)),
        ("correct_attempts", str(earlier.correct_attempts), str(later.correct_attempts)),
        ("recent_window", _fmt_window(earlier.recent_window), _fmt_window(later.recent_window)),
        ("is_due", _fmt_bool(earlier.is_due), _fmt_bool(later.is_due)),
    ]
    if comparison.improved:
        verdict = "MEJORO"
    elif comparison.regressed:
        verdict = "EMPEORO"
    else:
        verdict = "SIN CAMBIO"
    tail = _kv(
        [
            ("level_delta", f"{comparison.level_delta:+d}"),
            ("score_delta", f"{comparison.score_delta:+.4f}"),
            ("verdict", verdict),
        ]
    )
    return f"objective_id  {comparison.objective_id}\n\n" + _table(
        ("field", "earlier", "later"), rows
    ) + f"\n\n{tail}"


def format_check(report: ConsistencyReport) -> str:
    rows = [
        (
            check.name,
            _fmt_float(check.expected, 0),
            _fmt_float(check.actual, 0),
            "PASS" if check.passed else "FAIL",
            check.detail or "",
        )
        for check in report.checks
    ]
    table = _table(("check", "expected", "actual", "result", "detail"), rows)
    status = "OK" if report.ok else "FALLO"
    footer = _kv(
        [
            ("as_of", _fmt_dt(report.as_of)),
            ("objectives_checked", str(report.objectives_checked)),
            ("failures", str(len(report.failures))),
            ("status", status),
        ]
    )
    return f"{table}\n\n{footer}"


# ------------------------------------------------------------------ contexto


@dataclass
class Context:
    """Todo lo que necesita un comando: stores, reloj, fecha de corte y salida."""

    args: argparse.Namespace
    profiles: JsonProfileStore
    attempts: JsonAttemptStore
    clock: Clock
    as_of: datetime | None
    out: TextIO

    def moment(self) -> datetime:
        """``--as-of`` o ``clock.now()``: una sola noción de "ahora" por invocación."""
        return self.clock.now() if self.as_of is None else self.as_of

    def tracker(self) -> LearningTracker:
        if not self.args.profile:
            raise UsageError("--profile es obligatorio para este comando")
        return LearningTracker(
            self.args.profile, self.profiles, self.attempts, self.clock
        )

    def write(self, text: str) -> None:
        self.out.write(text.rstrip("\n") + "\n")


# ------------------------------------------------------------------ comandos


def _cmd_profile(ctx: Context) -> int:
    args = ctx.args
    if args.profile_command == "create":
        try:
            ctx.profiles.get_profile(args.profile_id)
        except UnknownProfileError:
            pass
        else:
            raise UsageError(f"el perfil {args.profile_id!r} ya existe")
        profile = ctx.profiles.save_profile(
            Profile(profile_id=args.profile_id, name=args.name)
        )
        ctx.write(f"perfil creado: {profile.profile_id} ({profile.name})")
        return EXIT_OK
    profiles = ctx.profiles.list_profiles()
    ctx.write(
        _table(
            ("profile_id", "name", "objectives"),
            [(p.profile_id, p.name, str(len(p.objectives))) for p in profiles],
        )
    )
    return EXIT_OK


def _cmd_objective(ctx: Context) -> int:
    args = ctx.args
    if not args.profile:
        raise UsageError("--profile es obligatorio para este comando")
    objective = Objective(
        objective_id=args.objective_id,
        title=args.title,
        domain=args.domain,
        weight=args.weight,
    )
    ctx.profiles.upsert_objectives(args.profile, [objective])
    ctx.write(f"objetivo guardado: {args.profile}/{objective.objective_id}")
    return EXIT_OK


def _cmd_objectives(ctx: Context) -> int:
    tracker = ctx.tracker()
    catalog = ctx.profiles.list_objectives(tracker.profile_id)
    states = {s.objective_id: s for s in tracker.get_all_states(ctx.moment())}
    rows = []
    for objective in catalog:
        state = states[objective.objective_id]
        rows.append(
            (
                objective.objective_id,
                objective.title,
                objective.domain or "-",
                _fmt_float(objective.weight, 2),
                state.level.name,
                _fmt_float(state.score),
                str(state.total_attempts),
                _fmt_bool(state.is_due),
            )
        )
    ctx.write(
        _table(
            ("objective_id", "title", "domain", "weight", "level", "score", "attempts", "due"),
            rows,
        )
    )
    return EXIT_OK


def _cmd_record(ctx: Context) -> int:
    args = ctx.args
    tracker = ctx.tracker()
    at = ctx.moment() if args.at is None else parse_iso(args.at, "--at")
    attempt = tracker.record_attempt(
        args.objective_id,
        correct=bool(args.correct),
        at=at,
        kind=AttemptKind(args.kind),
        confidence=args.confidence,
        note=args.note,
        attempt_id=args.attempt_id,
    )
    ctx.write(
        _kv(
            [
                ("attempt_id", attempt.attempt_id),
                ("objective_id", attempt.objective_id),
                ("at", _fmt_dt(attempt.at)),
                ("correct", _fmt_bool(attempt.correct)),
                ("kind", attempt.kind.value),
                ("confidence", _fmt_float(attempt.confidence, 2)),
                ("note", attempt.note or "-"),
            ]
        )
    )
    return EXIT_OK


def _cmd_state(ctx: Context) -> int:
    state = ctx.tracker().get_state(ctx.args.objective_id, ctx.moment())
    ctx.write(format_state(state))
    return EXIT_OK


def _cmd_due(ctx: Context) -> int:
    states = ctx.tracker().get_due(ctx.moment(), limit=ctx.args.limit)
    ctx.write(_states_table(states) if states else "nada pendiente de repaso")
    return EXIT_OK


def _cmd_unstarted(ctx: Context) -> int:
    states = ctx.tracker().get_unstarted(ctx.moment())
    if not states:
        ctx.write("todos los objetivos tienen al menos un intento")
        return EXIT_OK
    ctx.write(_table(("objective_id",), [(s.objective_id,) for s in states]))
    return EXIT_OK


def _cmd_stale(ctx: Context) -> int:
    states = ctx.tracker().get_stale(ctx.moment(), days=ctx.args.days)
    if not states:
        ctx.write("ningun objetivo estancado")
        return EXIT_OK
    rows = [
        (
            s.objective_id,
            s.level.name,
            _fmt_float(s.score),
            _fmt_dt(s.last_attempt_at),
            _fmt_float(s.days_since_last, 1),
        )
        for s in states
    ]
    ctx.write(
        _table(("objective_id", "level", "score", "last_attempt_at", "days_since_last"), rows)
    )
    return EXIT_OK


def _cmd_summary(ctx: Context) -> int:
    ctx.write(format_summary(ctx.tracker().get_summary(ctx.moment())))
    return EXIT_OK


def _cmd_timeline(ctx: Context) -> int:
    args = ctx.args
    states = ctx.tracker().get_timeline(
        args.objective_id,
        start=parse_iso(args.start, "--start"),
        end=parse_iso(args.end, "--end"),
        step=timedelta(days=args.step_days),
    )
    rows = [
        (
            _fmt_dt(s.as_of),
            s.level.name,
            _fmt_float(s.score),
            str(s.total_attempts),
            _fmt_window(s.recent_window),
            _fmt_bool(s.is_due),
        )
        for s in states
    ]
    ctx.write(f"objective_id  {args.objective_id}\n\n" + _table(
        ("as_of", "level", "score", "attempts", "window", "due"), rows
    ))
    return EXIT_OK


def _cmd_compare(ctx: Context) -> int:
    args = ctx.args
    comparison = ctx.tracker().compare_states(
        args.objective_id,
        earlier=parse_iso(args.earlier, "--earlier"),
        later=parse_iso(args.later, "--later"),
    )
    ctx.write(format_comparison(comparison))
    return EXIT_OK


def _cmd_check(ctx: Context) -> int:
    report = ctx.tracker().check_consistency(ctx.moment())
    ctx.write(format_check(report))
    return EXIT_OK if report.ok else EXIT_CHECK_FAILED


_COMMANDS: dict[str, Callable[[Context], int]] = {
    "profile": _cmd_profile,
    "objective": _cmd_objective,
    "objectives": _cmd_objectives,
    "record": _cmd_record,
    "state": _cmd_state,
    "due": _cmd_due,
    "unstarted": _cmd_unstarted,
    "stale": _cmd_stale,
    "summary": _cmd_summary,
    "timeline": _cmd_timeline,
    "compare": _cmd_compare,
    "check": _cmd_check,
}


# ------------------------------------------------------------------ entrada


def run(
    argv: Sequence[str],
    stdout: TextIO,
    stderr: TextIO | None = None,
    clock: Clock | None = None,
) -> int:
    """Ejecuta la CLI con salida y reloj inyectados. Devuelve el código de salida.

    Nunca deja escapar un traceback: los errores de dominio
    (:class:`~core.errors.TrackerError`) y de uso se imprimen en ``stderr`` y
    devuelven 2. ``check`` con ``ok=False`` devuelve 1.

    Args:
        argv: argumentos sin el nombre del programa.
        stdout: dónde escribir la salida normal.
        stderr: dónde escribir los errores; ``None`` usa ``sys.stderr``.
        clock: fuente de "ahora"; ``None`` usa :class:`store.SystemClock`.
    """
    err = sys.stderr if stderr is None else stderr
    try:
        args = build_parser().parse_args(list(argv))
        if args.command not in _PROFILE_FREE_COMMANDS and not args.profile:
            raise UsageError("--profile es obligatorio para este comando")
        data = Path(args.data)
        ctx = Context(
            args=args,
            profiles=JsonProfileStore(data / PROFILES_FILE),
            attempts=JsonAttemptStore(data / ATTEMPTS_FILE),
            clock=SystemClock() if clock is None else clock,
            as_of=None if args.as_of is None else parse_iso(args.as_of, "--as-of"),
            out=stdout,
        )
        return _COMMANDS[args.command](ctx)
    except UsageError as exc:
        err.write(f"error: {exc}\n")
        return EXIT_ERROR
    except TrackerError as exc:
        err.write(f"error: {type(exc).__name__}: {exc}\n")
        return EXIT_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada real: ``sys.argv``, ``sys.stdout`` y el reloj de sistema."""
    return run(sys.argv[1:] if argv is None else argv, sys.stdout, sys.stderr)


__all__ = ["build_parser", "main", "run", "parse_iso", "UsageError"]
