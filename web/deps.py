"""Builds the engine's collaborators once per process and injects them.

FastAPI dependencies here read from ``app.state``, populated once at startup
by :func:`build_resources` (called from ``web.app.create_app``'s lifespan) and
never rebuilt per request. In particular the database connection is a pool
(``psycopg_pool.ConnectionPool``) opened once and handed to the stores as
their ``ConnectionProvider`` (see the seam documented in
``store.postgres``): each request still gets its own connection for the
duration of one store operation, borrowed from the pool and returned to it,
rather than a fresh TCP connection to Postgres opened and closed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from psycopg_pool import ConnectionPool

from core.clock import Clock
from core.tracker import LearningTracker
from store import SystemClock
from store.postgres import PostgresAttemptStore, PostgresProfileStore

from .config import Settings

#: How long a health check waits for a pooled connection before giving up.
HEALTH_CHECK_TIMEOUT_SECONDS = 2.0


@dataclass
class Resources:
    """Everything request handlers need, built once at startup."""

    pool: ConnectionPool
    profiles: PostgresProfileStore
    attempts: PostgresAttemptStore
    clock: Clock

    def tracker_for(self, profile_id: str) -> LearningTracker:
        """A ``LearningTracker`` bound to one profile.

        A ``LearningTracker`` holds no connection of its own, only references
        to the shared stores and clock (see ``core.tracker``): building one
        per request is cheap, and it must be per-request because one tracker
        operates on exactly one profile (SPEC section 9.4).
        """
        return LearningTracker(profile_id, self.profiles, self.attempts, self.clock)

    def is_healthy(self) -> bool:
        """Whether storage actually answers, not merely that the process is up."""
        try:
            with self.pool.connection(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as conn:
                conn.execute("SELECT 1")
        except Exception:
            return False
        return True


def build_resources(settings: Settings) -> Resources:
    """Opens the connection pool and wires the stores over it.

    The pool is the ``ConnectionProvider``: stores are constructed with
    ``pool.connection`` directly, not with ``from_dsn`` (which would open and
    close a plain ``psycopg.connect`` per operation). That is the seam ACU-255
    introduced for exactly this caller — see the module docstring of
    ``store.postgres``.
    """
    pool = ConnectionPool(conninfo=settings.database_url, open=True)
    kwargs = {"schema": settings.schema} if settings.schema else {}
    profiles = PostgresProfileStore(pool.connection, **kwargs)
    attempts = PostgresAttemptStore(pool.connection, **kwargs)
    return Resources(pool=pool, profiles=profiles, attempts=attempts, clock=SystemClock())


def close_resources(resources: Resources) -> None:
    """Closes the pool. Called once, on shutdown."""
    resources.pool.close()


def get_resources(request: Request) -> Resources:
    """FastAPI dependency: the resources built at startup for this app."""
    return request.app.state.resources


__all__ = ["Resources", "build_resources", "close_resources", "get_resources"]
