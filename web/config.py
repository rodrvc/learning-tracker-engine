"""Settings for the web backend, read once from the environment.

Nothing here defaults to a path, a profile name or anything else that would
only work on the machine of whoever built this: the repository is public, so a
missing required setting fails loudly at startup, naming exactly what is
missing, instead of falling back to a value that happens to work for one
person.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

#: DSN of the PostgreSQL database the engine's stores read and write.
DATABASE_URL_VAR = "LEARNING_TRACKER_DATABASE_URL"

#: Schema the tables live in. Optional: falls back to the store's own default
#: (``"learning"``, see ``store.postgres.DEFAULT_SCHEMA``) when unset.
SCHEMA_VAR = "LEARNING_TRACKER_SCHEMA"

#: Host the HTTP server binds to.
HOST_VAR = "LEARNING_TRACKER_WEB_HOST"

#: Port the HTTP server binds to.
PORT_VAR = "LEARNING_TRACKER_WEB_PORT"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class MissingSettingError(RuntimeError):
    """A required environment variable is absent.

    Raised at startup, before the application accepts any request, naming the
    exact variable that must be set.
    """

    def __init__(self, var_name: str) -> None:
        super().__init__(
            f"missing required environment variable: {var_name}"
        )
        self.var_name = var_name


@dataclass(frozen=True)
class Settings:
    """Every environment-derived setting the web backend needs.

    Attributes:
        database_url: DSN passed to ``psycopg``/the connection pool.
        schema: Postgres schema the engine's tables live in.
        host: interface the HTTP server binds to.
        port: TCP port the HTTP server binds to.
    """

    database_url: str
    schema: str | None
    host: str
    port: int

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Settings":
        """Builds the settings from an environment mapping.

        Args:
            environ: environment to read (``os.environ`` in production; a
                plain ``dict`` in tests, so no test needs to touch the real
                process environment).

        Raises:
            MissingSettingError: ``LEARNING_TRACKER_DATABASE_URL`` is absent
                or empty. There is no default: a database is not something
                this codebase can guess and it must never point at a
                personal machine by accident.
        """
        database_url = environ.get(DATABASE_URL_VAR)
        if not database_url:
            raise MissingSettingError(DATABASE_URL_VAR)
        schema = environ.get(SCHEMA_VAR) or None
        host = environ.get(HOST_VAR) or DEFAULT_HOST
        raw_port = environ.get(PORT_VAR)
        if raw_port:
            try:
                port = int(raw_port)
            except ValueError as exc:
                raise ValueError(
                    f"{PORT_VAR} must be an integer, got {raw_port!r}"
                ) from exc
        else:
            port = DEFAULT_PORT
        return cls(database_url=database_url, schema=schema, host=host, port=port)


__all__ = [
    "DATABASE_URL_VAR",
    "SCHEMA_VAR",
    "HOST_VAR",
    "PORT_VAR",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MissingSettingError",
    "Settings",
]
