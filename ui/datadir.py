"""Where the data lives: per-user directory in the standard folder of the OS.

The engine stopped being a personal tool: someone else installs it and their
data cannot end up inside the cloned repo. The relative default (``./data``)
depended on the current directory, so running the CLI from another folder opened
an empty store and it looked like the data had been lost.

Precedence, highest to lowest: ``--data DIR`` > ``LEARNING_TRACKER_DATA`` >
per operating system default.

Everything here is a pure function: the platform, the environment and ``home``
arrive as parameters, so the tests decide the operating system without touching
the real environment or the ``HOME`` of whoever runs the suite.

The text of the migration notice stays in Spanish: the user reads it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

#: Environment variable that beats the OS default (but not ``--data``).
DATA_ENV_VAR = "LEARNING_TRACKER_DATA"

#: Name of our own folder inside the data directory of the OS.
APP_DIR_NAME = "learning-tracker"

#: Legacy directory, relative to the cwd, used as the default in earlier versions.
LEGACY_DATA_DIR = "./data"

#: Permissions of the data directory: only its owner gets in (``rwx------``).
DATA_DIR_MODE = 0o700


def default_data_dir(platform: str, environ: Mapping[str, str], home: Path) -> Path:
    """Default data directory, without looking at ``--data``.

    ``LEARNING_TRACKER_DATA`` beats the OS default. When it is absent, on macOS
    it is ``~/Library/Application Support/learning-tracker``; everywhere else
    XDG is followed: ``$XDG_DATA_HOME/learning-tracker`` when the variable is
    defined and not empty, otherwise ``~/.local/share/learning-tracker``.

    Args:
        platform: value of ``sys.platform`` (``"darwin"`` for macOS).
        environ: environment to query (``os.environ`` in production).
        home: home directory of the user (``Path.home()`` in production).
    """
    override = environ.get(DATA_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    xdg = environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / APP_DIR_NAME
    return home / ".local" / "share" / APP_DIR_NAME


def resolve_data_dir(
    explicit: str | None, platform: str, environ: Mapping[str, str], home: Path
) -> Path:
    """Applies the full precedence: ``--data`` > environment > OS default."""
    if explicit is not None:
        return Path(explicit).expanduser()
    return default_data_dir(platform, environ, home)


def ensure_data_dir(path: Path) -> Path:
    """Creates the directory (with its parents) reachable only by its owner.

    ``mode`` applies only to the directories this call creates; when it already
    existed its permissions are left alone, because it may be a directory the
    user shares on purpose. The JSON files inside are still written by ``store/``
    exactly as before.
    """
    path.mkdir(mode=DATA_DIR_MODE, parents=True, exist_ok=True)
    return path


def _has_json(path: Path) -> bool:
    try:
        return any(path.glob("*.json"))
    except OSError:
        return False


def migration_notice(cwd: Path, destination: Path) -> str | None:
    """Migration notice when data was left in the old ``./data`` of the cwd.

    Returns the text to print to stderr, or ``None`` when there is nothing to
    warn about. It only warns when the ``./data`` of the current directory has
    some ``*.json`` and the new destination has none yet: if the destination
    already holds data, the migration already happened (or there is new data)
    and repeating the notice would be noise.

    It never moves or copies anything: moving someone's data is their call, not
    ours. The notice carries the exact command, with the paths already expanded.
    """
    legacy = (cwd / LEGACY_DATA_DIR).resolve()
    target = destination.resolve()
    if legacy == target:
        return None
    if not _has_json(legacy) or _has_json(target):
        return None
    return (
        f"aviso: hay datos en {legacy} y ahora los datos viven en {target}.\n"
        "No se ha movido nada. Para migrarlos:\n"
        f"  mkdir -p {_quote(target)}\n"
        f"  mv {_quote(legacy)}/*.json {_quote(target)}/\n"
        f"O usa --data {_quote(legacy)} (o {DATA_ENV_VAR}) para seguir donde estan."
    )


def _quote(path: Path) -> str:
    """Quotes the path for the shell only when needed."""
    text = str(path)
    if all(char.isalnum() or char in "-_./~+@:," for char in text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def describe_default(platform: str, environ: Mapping[str, str], home: Path) -> str:
    """Effective default, exactly as shown in the help of ``--data``."""
    if environ.get(DATA_ENV_VAR):
        return f"{default_data_dir(platform, environ, home)} (de {DATA_ENV_VAR})"
    return str(default_data_dir(platform, environ, home))


__all__ = [
    "APP_DIR_NAME",
    "DATA_DIR_MODE",
    "DATA_ENV_VAR",
    "LEGACY_DATA_DIR",
    "default_data_dir",
    "describe_default",
    "ensure_data_dir",
    "migration_notice",
    "resolve_data_dir",
]
