"""Tests de ``ui/`` (CLI) contra la API pública de ``LearningTracker``.

Convenciones:

* ``spec``: cada subcomando produce lo que el motor responde (SPEC §5, §9.4)
  y ``--as-of`` respeta la garantía temporal de §5.1.
* ``invariant``: la restricción estructural de ``ui/`` (no recalcula, no lee
  intentos por su cuenta) protege I4 e I2.

Todo corre con :func:`ui.cli.run` sobre ``tmp_path`` como ``--data``, con un
``FixedClock`` inyectado y capturando ``stdout`` en memoria: sin subprocesos,
sin reloj de sistema, sin dependencias de cuándo se ejecuta la suite.
"""

from __future__ import annotations

import ast
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.clock import FixedClock
from ui import cli
from ui.cli import EXIT_CHECK_FAILED, EXIT_ERROR, EXIT_OK, run

UI_DIR = Path(cli.__file__).resolve().parent
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
PROFILE = "ai-103"


def _iso(day: int, hour: int = 10) -> str:
    return f"2026-01-{day:02d}T{hour:02d}:00:00Z"


class Cli:
    """Invoca ``run`` con un ``--data`` fijo y devuelve ``(code, stdout, stderr)``."""

    def __init__(self, data: Path, clock: FixedClock) -> None:
        self.data = data
        self.clock = clock

    def __call__(self, *argv: str, profile: str | None = PROFILE) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        prefix = ["--data", str(self.data)]
        if profile is not None:
            prefix += ["--profile", profile]
        code = run([*prefix, *argv], out, err, clock=self.clock)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv: str, **kwargs: object) -> str:
        code, out, err = self(*argv, **kwargs)  # type: ignore[arg-type]
        assert code == EXIT_OK, err
        return out


@pytest.fixture
def cli_(tmp_path: Path) -> Cli:
    return Cli(tmp_path / "data", FixedClock(NOW))


@pytest.fixture
def seeded(cli_: Cli) -> Cli:
    """Perfil con dos objetivos y la serie de SPEC §3 en ``D3.2``: mal×3, bien, mal."""
    cli_.ok("profile", "create", PROFILE, "--name", "AI-103", profile=None)
    cli_.ok("objective", "add", "D3.2", "--title", "Content understanding", "--domain", "D3")
    cli_.ok("objective", "add", "D1.1", "--title", "Basics", "--weight", "2")
    for day, flag in enumerate([False, False, False, True, False], start=1):
        cli_.ok("record", "D3.2", "--correct" if flag else "--wrong", "--at", _iso(day))
    return cli_


# --------------------------------------------------------------- perfiles y objetivos


@pytest.mark.spec
def test_profile_create_and_list(cli_: Cli) -> None:
    out = cli_.ok("profile", "create", PROFILE, "--name", "AI-103", profile=None)
    assert "perfil creado: ai-103 (AI-103)" in out
    listing = cli_.ok("profile", "list", profile=None)
    assert PROFILE in listing and "AI-103" in listing
    assert (cli_.data / cli.PROFILES_FILE).exists()


@pytest.mark.spec
def test_profile_create_twice_is_an_error_and_keeps_objectives(cli_: Cli) -> None:
    cli_.ok("profile", "create", PROFILE, "--name", "AI-103", profile=None)
    cli_.ok("objective", "add", "D3.2", "--title", "x")
    code, _, err = cli_("profile", "create", PROFILE, "--name", "otro", profile=None)
    assert code == EXIT_ERROR and "ya existe" in err
    assert "D3.2" in cli_.ok("objectives")


@pytest.mark.spec
def test_objective_add_requires_existing_profile(cli_: Cli) -> None:
    code, _, err = cli_("objective", "add", "D3.2", "--title", "x")
    assert code == EXIT_ERROR
    assert "UnknownProfileError" in err


@pytest.mark.spec
def test_objectives_lists_catalog_with_level_from_tracker(seeded: Cli) -> None:
    out = seeded.ok("--as-of", _iso(6), "objectives")
    lines = out.splitlines()
    assert lines[0].split() == [
        "objective_id", "title", "domain", "weight", "level", "score", "attempts", "due",
    ]
    d11 = next(line for line in lines if line.startswith("D1.1"))
    d32 = next(line for line in lines if line.startswith("D3.2"))
    assert "UNASSESSED" in d11 and "2.00" in d11
    assert "Content understanding" in d32 and "D3" in d32 and " 5 " in d32


# --------------------------------------------------------------- record


@pytest.mark.spec
def test_record_prints_persisted_attempt_and_uses_kind_confidence_note(seeded: Cli) -> None:
    out = seeded.ok(
        "record", "D1.1", "--correct", "--at", _iso(9), "--kind", "lab",
        "--confidence", "0.75", "--note", "primer lab", "--id", "att-1",
    )
    assert "attempt_id    att-1" in out
    assert "at            2026-01-09T10:00:00+00:00" in out
    assert "kind          lab" in out
    assert "confidence    0.75" in out
    assert "note          primer lab" in out


@pytest.mark.spec
def test_record_without_at_uses_injected_clock(seeded: Cli) -> None:
    out = seeded.ok("record", "D1.1", "--wrong")
    assert f"at            {NOW.isoformat()}" in out


@pytest.mark.spec
def test_record_without_at_uses_as_of_when_given(seeded: Cli) -> None:
    out = seeded.ok("--as-of", _iso(20), "record", "D1.1", "--wrong")
    assert "at            2026-01-20T10:00:00+00:00" in out


@pytest.mark.spec
def test_record_naive_at_is_assumed_utc(seeded: Cli) -> None:
    out = seeded.ok("record", "D1.1", "--wrong", "--at", "2026-01-09T10:00:00")
    assert "2026-01-09T10:00:00+00:00" in out


# --------------------------------------------------------------- consultas


@pytest.mark.spec
def test_state_shows_full_objective_state_without_streak(seeded: Cli) -> None:
    out = seeded.ok("--as-of", _iso(6), "state", "D3.2")
    assert "objective_id      D3.2" in out
    assert "as_of             2026-01-06T10:00:00+00:00" in out
    assert "total_attempts    5" in out
    assert "correct_attempts  1" in out
    assert "recent_window     ---+-" in out
    assert "first_attempt_at  2026-01-01T10:00:00+00:00" in out
    assert "last_attempt_at   2026-01-05T10:00:00+00:00" in out
    assert "distinct_days     5" in out
    assert "level             WEAK (1)" in out
    assert "is_due            si" in out
    assert "streak" not in out  # I10


@pytest.mark.spec
def test_due_orders_by_urgency_and_respects_limit(seeded: Cli) -> None:
    seeded.ok("record", "D1.1", "--correct", "--at", _iso(4))
    out = seeded.ok("--as-of", _iso(10), "due")
    ids = [line.split()[0] for line in out.splitlines()[2:]]
    # D1.1 vence antes (un acierto el día 4 -> repaso día 5) que D3.2 (fallo día 5 -> día 6).
    assert ids == ["D1.1", "D3.2"]
    limited = seeded.ok("--as-of", _iso(10), "due", "--limit", "1")
    assert [line.split()[0] for line in limited.splitlines()[2:]] == ["D1.1"]


@pytest.mark.spec
def test_due_excludes_unstarted_and_unstarted_lists_them(seeded: Cli) -> None:
    due = seeded.ok("--as-of", _iso(10), "due")
    assert "D1.1" not in due
    unstarted = seeded.ok("--as-of", _iso(10), "unstarted")
    assert unstarted.splitlines()[2:] == ["D1.1"]


@pytest.mark.spec
def test_due_empty_message(seeded: Cli) -> None:
    out = seeded.ok("--as-of", _iso(5, hour=11), "due")
    assert out.strip() == "nada pendiente de repaso"


@pytest.mark.spec
def test_stale_uses_days_threshold(seeded: Cli) -> None:
    quiet = seeded.ok("--as-of", _iso(10), "stale", "--days", "10")
    assert quiet.strip() == "ningun objetivo estancado"
    out = seeded.ok("--as-of", _iso(30), "stale", "--days", "10")
    rows = out.splitlines()[2:]
    assert [r.split()[0] for r in rows] == ["D3.2"]
    assert "2026-01-05T10:00:00+00:00" in rows[0]


@pytest.mark.spec
def test_summary_reports_counts_and_by_level(seeded: Cli) -> None:
    out = seeded.ok("--as-of", _iso(6), "summary")
    assert "profile_id            ai-103" in out
    assert "total_objectives      2" in out
    assert "assessed_objectives   1" in out
    assert "unstarted_objectives  1" in out
    assert "due_objectives        1" in out
    assert "total_attempts        5" in out
    assert "coverage              0.5000" in out
    assert "UNASSESSED (0)  1" in out
    assert "WEAK (1)        1" in out


@pytest.mark.spec
def test_timeline_one_row_per_grid_point(seeded: Cli) -> None:
    out = seeded.ok(
        "timeline", "D3.2", "--start", "2026-01-01T12:00:00Z",
        "--end", "2026-01-07T12:00:00Z", "--step-days", "2",
    )
    rows = out.splitlines()[4:]
    assert [r.split()[0] for r in rows] == [
        "2026-01-01T12:00:00+00:00",
        "2026-01-03T12:00:00+00:00",
        "2026-01-05T12:00:00+00:00",
        "2026-01-07T12:00:00+00:00",
    ]
    assert [r.split()[3] for r in rows] == ["1", "3", "5", "5"]


@pytest.mark.spec
def test_compare_reports_improvement(seeded: Cli) -> None:
    seeded.ok("record", "D3.2", "--correct", "--at", _iso(6))
    seeded.ok("record", "D3.2", "--correct", "--at", _iso(7))
    out = seeded.ok("compare", "D3.2", "--earlier", _iso(3, 12), "--later", _iso(7, 12))
    assert "verdict      MEJORO" in out
    assert "score_delta  +" in out
    assert "total_attempts    3                          7" in out


@pytest.mark.spec
def test_compare_reverse_range_is_domain_error(seeded: Cli) -> None:
    code, _, err = seeded("compare", "D3.2", "--earlier", _iso(7), "--later", _iso(3))
    assert code == EXIT_ERROR and "InvalidRangeError" in err


# --------------------------------------------------------------- §5.1 garantía temporal


@pytest.mark.spec
def test_as_of_state_in_the_past_does_not_change_after_later_attempts(seeded: Cli) -> None:
    """SPEC §5.1: lo pasado no se reescribe. El estado en una fecha pasada es
    idéntico antes y después de registrar intentos posteriores."""
    before = seeded.ok("--as-of", _iso(3, 12), "state", "D3.2")
    seeded.ok("record", "D3.2", "--correct", "--at", _iso(20))
    seeded.ok("record", "D3.2", "--correct", "--at", _iso(21))
    after = seeded.ok("--as-of", _iso(3, 12), "state", "D3.2")
    assert before == after
    assert "total_attempts    3" in after
    # Y la consulta sin --as-of (reloj inyectado, marzo) sí ve los nuevos.
    assert "total_attempts    7" in seeded.ok("state", "D3.2")


@pytest.mark.spec
def test_as_of_applies_to_every_query(seeded: Cli) -> None:
    assert "total_attempts        0" in seeded.ok("--as-of", "2025-12-31", "summary")
    assert seeded.ok("--as-of", "2025-12-31", "unstarted").splitlines()[2:] == ["D1.1", "D3.2"]


@pytest.mark.spec
def test_as_of_invalid_iso_is_usage_error(seeded: Cli) -> None:
    code, _, err = seeded("--as-of", "ayer", "summary")
    assert code == EXIT_ERROR and "ISO 8601" in err


# --------------------------------------------------------------- check y exit codes


@pytest.mark.spec
def test_check_ok_exits_zero(seeded: Cli) -> None:
    code, out, _ = seeded("check")
    assert code == EXIT_OK
    assert "status              OK" in out
    assert "FAIL" not in out


@pytest.mark.spec
def test_check_without_objectives_is_not_ok(cli_: Cli) -> None:
    """``ok`` es positivo: no haber mirado nada no es estar bien (SPEC §9.5)."""
    cli_.ok("profile", "create", PROFILE, "--name", "vacío", profile=None)
    code, out, _ = cli_("check")
    assert code == EXIT_CHECK_FAILED
    assert "objectives_checked  0" in out
    assert "status              FALLO" in out


@pytest.mark.spec
def test_check_detects_orphan_attempts_in_store(seeded: Cli) -> None:
    path = seeded.data / cli.ATTEMPTS_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    orphan = dict(document["attempts"][0])
    orphan["attempt_id"] = "huerfano"
    orphan["objective_id"] = "NO-EXISTE"
    document["attempts"].append(orphan)
    path.write_text(json.dumps(document), encoding="utf-8")
    code, out, _ = seeded("check")
    assert code == EXIT_CHECK_FAILED
    assert "orphan_attempts" in out and "FAIL" in out
    assert "status              FALLO" in out


@pytest.mark.spec
@pytest.mark.parametrize(
    "argv, error",
    [
        (["state", "NOPE"], "UnknownObjectiveError"),
        (["record", "NOPE", "--correct"], "UnknownObjectiveError"),
        (["record", "D3.2", "--correct", "--confidence", "1.5"], "InvalidAttemptError"),
        (["record", "D3.2", "--correct", "--at", "2026-13-40"], "ISO 8601"),
        (["timeline", "D3.2", "--start", _iso(9), "--end", _iso(1)], "InvalidRangeError"),
    ],
)
def test_domain_errors_exit_two_without_traceback(seeded: Cli, argv: list[str], error: str) -> None:
    code, out, err = seeded(*argv)
    assert code == EXIT_ERROR
    assert error in err
    assert "Traceback" not in err
    assert out == ""


@pytest.mark.spec
def test_duplicate_attempt_id_exits_two(seeded: Cli) -> None:
    seeded.ok("record", "D1.1", "--correct", "--id", "dup")
    code, _, err = seeded("record", "D1.1", "--wrong", "--id", "dup")
    assert code == EXIT_ERROR and "DuplicateAttemptError" in err


@pytest.mark.spec
def test_storage_error_exits_two(seeded: Cli) -> None:
    (seeded.data / cli.ATTEMPTS_FILE).write_text("{esto no es json", encoding="utf-8")
    code, _, err = seeded("summary")
    assert code == EXIT_ERROR and "StorageError" in err


@pytest.mark.spec
def test_missing_profile_option_is_usage_error(seeded: Cli) -> None:
    code, _, err = seeded("summary", profile=None)
    assert code == EXIT_ERROR and "--profile" in err


@pytest.mark.spec
def test_unknown_profile_exits_two(cli_: Cli) -> None:
    code, _, err = cli_("summary")
    assert code == EXIT_ERROR and "UnknownProfileError" in err


@pytest.mark.spec
def test_argparse_errors_go_to_injected_stderr(cli_: Cli) -> None:
    code, out, err = cli_("record", "D3.2")  # falta --correct/--wrong
    assert code == EXIT_ERROR and "--correct" in err and out == ""
    code, _, err = cli_("inexistente")
    assert code == EXIT_ERROR and "inexistente" in err


@pytest.mark.spec
def test_main_uses_sys_stdout(seeded: Cli, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "SystemClock", lambda: seeded.clock)
    code = cli.main(["--data", str(seeded.data), "--profile", PROFILE, "state", "D3.2"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "objective_id      D3.2" in captured.out
    assert f"as_of             {NOW.isoformat()}" in captured.out


# --------------------------------------------------------------- restricción estructural


ALLOWED_PROJECT_IMPORTS = {
    "core.tracker", "core.session", "core.models", "core.errors", "core.clock", "store",
}
FORBIDDEN_IMPORTS = {"core.leveling", "core.scheduling", "core.constants", "store.memory", "store.json_store"}
FORBIDDEN_ATTRS = {"list_for_objective", "list_all"}


def _imports(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # import relativo dentro de ui/
                names.add("ui")
            else:
                names.add(node.module or "")
    return names


@pytest.mark.invariant
def test_ui_only_uses_the_public_tracker_api() -> None:
    """``ui/`` no recalcula ni lee intentos por su cuenta (I4 por la puerta de atrás)."""
    stdlib = set(sys.stdlib_module_names)
    for source in UI_DIR.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for name in _imports(tree):
            root = name.split(".")[0]
            if root in stdlib or root == "ui":
                continue
            assert name in ALLOWED_PROJECT_IMPORTS, f"{source.name} importa {name}"
            assert name not in FORBIDDEN_IMPORTS, f"{source.name} importa {name}"
        attrs = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert not attrs & FORBIDDEN_ATTRS, f"{source.name} lee intentos del store"


@pytest.mark.invariant
def test_ui_never_calls_datetime_now_directly() -> None:
    """I2: el reloj real entra solo por ``SystemClock`` (de ``store``), inyectable."""
    for source in UI_DIR.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "datetime.now(" not in text and "utcnow(" not in text, source.name
