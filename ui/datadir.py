"""Dónde viven los datos: directorio por usuario en la carpeta estándar del SO.

El motor dejó de ser una herramienta personal: otra persona lo instala y sus
datos no pueden acabar dentro del repo clonado. El default relativo (``./data``)
dependía del directorio actual, así que ejecutar la CLI desde otra carpeta
abría un store vacío y parecía que se habían perdido los datos.

Precedencia, de mayor a menor: ``--data DIR`` > ``LEARNING_TRACKER_DATA`` >
default por sistema operativo.

Todo aquí es función pura: la plataforma, el entorno y el ``home`` entran por
parámetro, así que los tests deciden el sistema operativo sin tocar el entorno
real ni el ``HOME`` de quien corre la suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

#: Variable de entorno que gana al default del SO (pero no a ``--data``).
DATA_ENV_VAR = "LEARNING_TRACKER_DATA"

#: Nombre de la carpeta propia dentro del directorio de datos del SO.
APP_DIR_NAME = "learning-tracker"

#: Directorio heredado, relativo al cwd, que se usaba como default hasta ACU-215.
LEGACY_DATA_DIR = "./data"

#: Permisos del directorio de datos: solo su dueño entra (``rwx------``).
DATA_DIR_MODE = 0o700


def default_data_dir(platform: str, environ: Mapping[str, str], home: Path) -> Path:
    """Directorio de datos por defecto, sin mirar ``--data``.

    ``LEARNING_TRACKER_DATA`` gana sobre el default del SO. Si no está, en
    macOS es ``~/Library/Application Support/learning-tracker``; en el resto se
    sigue XDG: ``$XDG_DATA_HOME/learning-tracker`` si la variable está definida
    y no vacía, si no ``~/.local/share/learning-tracker``.

    Args:
        platform: valor de ``sys.platform`` (``"darwin"`` para macOS).
        environ: entorno a consultar (``os.environ`` en producción).
        home: directorio del usuario (``Path.home()`` en producción).
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
    """Aplica la precedencia completa: ``--data`` > entorno > default del SO."""
    if explicit is not None:
        return Path(explicit).expanduser()
    return default_data_dir(platform, environ, home)


def ensure_data_dir(path: Path) -> Path:
    """Crea el directorio (con sus padres) accesible solo por su dueño.

    ``mode`` solo aplica a los directorios que esta llamada crea; si ya existía
    no se tocan sus permisos, porque puede ser un directorio que el usuario
    comparte a propósito. Los JSON de dentro los sigue escribiendo ``store/``
    exactamente igual que antes.
    """
    path.mkdir(mode=DATA_DIR_MODE, parents=True, exist_ok=True)
    return path


def _has_json(path: Path) -> bool:
    try:
        return any(path.glob("*.json"))
    except OSError:
        return False


def migration_notice(cwd: Path, destination: Path) -> str | None:
    """Aviso de migración cuando quedaron datos en el viejo ``./data`` del cwd.

    Devuelve el texto a imprimir por stderr, o ``None`` si no hay nada que
    avisar. Solo avisa cuando el ``./data`` del directorio actual tiene algún
    ``*.json`` y el destino nuevo todavía no tiene ninguno: si el destino ya
    tiene datos, la migración ya se hizo (o hay datos nuevos) y repetir el
    aviso sería ruido.

    Nunca mueve ni copia nada: mover los datos de alguien es suyo, no nuestro.
    El aviso trae el comando exacto, con las rutas ya expandidas.
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
    """Entrecomilla la ruta para el shell solo si hace falta."""
    text = str(path)
    if all(char.isalnum() or char in "-_./~+@:," for char in text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def describe_default(platform: str, environ: Mapping[str, str], home: Path) -> str:
    """Default efectivo, tal como se muestra en el help de ``--data``."""
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
