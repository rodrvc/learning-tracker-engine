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

#: The port a platform such as Railway injects. Read when ``PORT_VAR`` is
#: unset, so a deploy needs no product-specific port setting (product
#: contract, section 5).
PLATFORM_PORT_VAR = "PORT"

#: Clerk's issuer / frontend API for this instance, e.g.
#: ``https://example-app.clerk.accounts.example``. Set it and every request to
#: the API (except ``/health`` and ``/auth/config``, see ``web/app.py``) must
#: carry a Clerk session token that verifies against this issuer's JWKS.
#:
#: Authentication fails closed (product contract, section 2): leaving this
#: unset is a configuration error unless ``AUTH_DISABLED_VAR`` says, in so
#: many words, that authentication is meant to be off. A deploy that simply
#: forgot the issuer must refuse to start, not serve everyone's data to
#: anyone.
CLERK_ISSUER_VAR = "LEARNING_TRACKER_CLERK_ISSUER"

#: The explicit off switch for authentication, for local development and
#: single-user installs. ``true``/``1``/``yes`` turns it on; setting it
#: together with an issuer is a configuration error, since the two disagree
#: about whether sessions are checked.
AUTH_DISABLED_VAR = "LEARNING_TRACKER_AUTH_DISABLED"

#: Comma-separated origins accepted in a session token's ``azp`` claim, e.g.
#: ``https://learning.acuarialabs.cl``. Every Acuaria product shares one Clerk
#: instance, so without this a token minted for another product's origin
#: would be accepted here. Unset means ``azp`` is not checked.
CLERK_AUTHORIZED_PARTIES_VAR = "LEARNING_TRACKER_CLERK_AUTHORIZED_PARTIES"

#: Clerk's publishable key, handed to the browser so it can start a session.
#: Not a secret - Clerk documents it as safe to ship to a client - but kept
#: out of the repository like every other setting here, since it is specific
#: to one Clerk instance. Read only to serve it from ``GET /auth/config``;
#: the web layer never inspects it itself.
CLERK_PUBLISHABLE_KEY_VAR = "LEARNING_TRACKER_CLERK_PUBLISHABLE_KEY"

#: Turns the instance into a demo environment: a visible banner in the UI and
#: a persona switcher grouped by organization (``web/demo.py``). Only valid
#: with authentication off - the personas are impersonated through the
#: ``X-Dev-*`` headers, which exist only in that mode - so combining it with a
#: Clerk issuer is a configuration error and the app refuses to start.
DEMO_MODE_VAR = "LEARNING_TRACKER_DEMO_MODE"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


_TRUE_VALUES = frozenset({"true", "1", "yes"})
_FALSE_VALUES = frozenset({"", "false", "0", "no"})


class ConfigurationError(RuntimeError):
    """The environment describes a configuration the application refuses to
    run with. Raised at startup, before any request is accepted."""


class MissingSettingError(ConfigurationError):
    """A required environment variable is absent.

    Raised at startup, before the application accepts any request, naming the
    exact variable that must be set.
    """

    def __init__(self, var_name: str) -> None:
        super().__init__(
            f"missing required environment variable: {var_name}"
        )
        self.var_name = var_name


def _parse_flag(var_name: str, raw: str | None) -> bool:
    """A boolean switch. Anything that is not clearly on or off is an error
    rather than a guess: ``enabled`` read as off would be a quiet surprise."""
    value = (raw or "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"{var_name} must be one of true/1/yes or false/0/no, got {raw!r}"
    )


@dataclass(frozen=True)
class Settings:
    """Every environment-derived setting the web backend needs.

    Attributes:
        database_url: DSN passed to ``psycopg``/the connection pool.
        schema: Postgres schema the engine's tables live in.
        host: interface the HTTP server binds to.
        port: TCP port the HTTP server binds to.
        clerk_issuer: Clerk issuer to validate sessions against, or ``None``
            when ``auth_disabled`` is set.
        clerk_publishable_key: Clerk publishable key served to the browser,
            or ``None``.
        auth_disabled: authentication explicitly switched off. Exactly one
            of this and ``clerk_issuer`` must be set; the constructor
            enforces it, so no code path can end up with neither.
        clerk_authorized_parties: origins accepted in the ``azp`` claim;
            empty means ``azp`` is not checked.
        demo_mode: show the demo banner and persona switcher. Requires
            ``auth_disabled``; the constructor enforces it.
    """

    database_url: str
    schema: str | None
    host: str
    port: int
    clerk_issuer: str | None = None
    clerk_publishable_key: str | None = None
    auth_disabled: bool = False
    clerk_authorized_parties: tuple[str, ...] = ()
    demo_mode: bool = False

    def __post_init__(self) -> None:
        # Checked here rather than only in ``from_env`` so a hand-built
        # ``Settings`` cannot fail open either.
        if self.auth_disabled and self.clerk_issuer:
            raise ConfigurationError(
                f"{AUTH_DISABLED_VAR} and {CLERK_ISSUER_VAR} are both set: "
                "unset one of them"
            )
        if not self.auth_disabled and not self.clerk_issuer:
            raise ConfigurationError(
                f"authentication is not configured: set {CLERK_ISSUER_VAR}, "
                f"or set {AUTH_DISABLED_VAR}=true to run without it"
            )
        if self.demo_mode and not self.auth_disabled:
            raise ConfigurationError(
                f"{DEMO_MODE_VAR} needs {AUTH_DISABLED_VAR}=true: the demo personas "
                "are impersonated without a session, which must never be possible "
                "with authentication on"
            )

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
            ConfigurationError: authentication is neither configured nor
                explicitly disabled, or is both; or a value is malformed.
        """
        database_url = environ.get(DATABASE_URL_VAR)
        if not database_url:
            raise MissingSettingError(DATABASE_URL_VAR)
        schema = environ.get(SCHEMA_VAR) or None
        host = environ.get(HOST_VAR) or DEFAULT_HOST
        port_var = PORT_VAR if environ.get(PORT_VAR) else PLATFORM_PORT_VAR
        raw_port = environ.get(port_var)
        if raw_port:
            try:
                port = int(raw_port)
            except ValueError as exc:
                raise ConfigurationError(
                    f"{port_var} must be an integer, got {raw_port!r}"
                ) from exc
        else:
            port = DEFAULT_PORT
        auth_disabled = _parse_flag(AUTH_DISABLED_VAR, environ.get(AUTH_DISABLED_VAR))
        authorized_parties = tuple(
            party.strip().rstrip("/")
            for party in (environ.get(CLERK_AUTHORIZED_PARTIES_VAR) or "").split(",")
            if party.strip()
        )
        clerk_issuer = environ.get(CLERK_ISSUER_VAR) or None
        if clerk_issuer:
            # A trailing slash would build a JWKS URL with a doubled slash
            # (``.dev//.well-known/...``); stripping it here is one place
            # instead of every caller that appends a path to the issuer.
            clerk_issuer = clerk_issuer.rstrip("/")
        clerk_publishable_key = environ.get(CLERK_PUBLISHABLE_KEY_VAR) or None
        return cls(
            database_url=database_url,
            schema=schema,
            host=host,
            port=port,
            clerk_issuer=clerk_issuer,
            clerk_publishable_key=clerk_publishable_key,
            auth_disabled=auth_disabled,
            clerk_authorized_parties=authorized_parties,
            demo_mode=_parse_flag(DEMO_MODE_VAR, environ.get(DEMO_MODE_VAR)),
        )


__all__ = [
    "DATABASE_URL_VAR",
    "SCHEMA_VAR",
    "HOST_VAR",
    "PORT_VAR",
    "PLATFORM_PORT_VAR",
    "CLERK_ISSUER_VAR",
    "CLERK_PUBLISHABLE_KEY_VAR",
    "AUTH_DISABLED_VAR",
    "DEMO_MODE_VAR",
    "CLERK_AUTHORIZED_PARTIES_VAR",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "ConfigurationError",
    "MissingSettingError",
    "Settings",
]
