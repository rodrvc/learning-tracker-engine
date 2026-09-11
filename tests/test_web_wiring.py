"""Tests of ``web/`` that need no database at all.

They live apart from ``tests/test_web.py`` because that module's autouse
fixture skips the whole file when Postgres is unreachable, and these three do
not want a database - one of them actively wants there not to be one. Left
there, they skipped locally for a reason that had nothing to do with them
(ACU-246 review).

What they cover is the wiring this layer is responsible for and that no other
test binds: that the pool is the connection provider both stores share, that it
is closed on shutdown, and that a storage failure reaches the caller as a
service-unavailable answer that says nothing about the database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.errors import StorageError
from web.app import STORAGE_UNAVAILABLE_DETAIL, create_app
from web.config import DATABASE_URL_VAR, MissingSettingError, Settings
from web.deps import build_resources, close_resources

#: Syntactically valid, deliberately unreachable, and carrying credentials that
#: must never appear in a response body.
DEAD_DSN = "postgresql://leaky_user:leaky_password@127.0.0.1:1/nowhere"


@pytest.fixture
def dead_settings() -> Settings:
    return Settings(database_url=DEAD_DSN, schema=None, host="127.0.0.1", port=8000)


@pytest.mark.spec
def test_missing_database_url_fails_at_startup_naming_it():
    with pytest.raises(MissingSettingError) as raised:
        Settings.from_env({})
    assert DATABASE_URL_VAR in str(raised.value)


@pytest.mark.spec
def test_both_stores_share_the_pool_and_the_pool_closes_on_shutdown(dead_settings):
    """The headline claim of this layer, which nothing else binds.

    One pool, handed to both stores as their connection provider, closed on
    shutdown. Swapping either store to ``from_dsn`` - a connection opened and
    closed per operation, which is what ACU-255 existed to stop - would leave
    the rest of the suite green.

    No database is needed: opening a pool against an unreachable host does not
    raise, because the pool connects lazily.
    """
    resources = build_resources(dead_settings)
    try:
        assert resources.profiles._connect_fn == resources.pool.connection
        assert resources.attempts._connect_fn == resources.pool.connection
    finally:
        close_resources(resources)
    assert resources.pool.closed


@pytest.mark.spec
def test_storage_failure_is_503_and_never_echoes_the_connection_string(dead_settings):
    """A dead database answers 503, and the answer names nothing.

    Before this handler existed every route answered a dead database with a
    generic 500, discarding the guarantee ``store.postgres`` goes to some
    length to provide. The obvious fix would have been worse than the problem:
    those ``StorageError`` messages interpolate the driver's text, and a
    psycopg connection error embeds host, port, user and database name. So the
    detail is constant and this test pins that it stays constant.
    """
    with TestClient(create_app(dead_settings), raise_server_exceptions=False) as client:
        for method, path in (("get", "/topics"), ("get", "/topics/whatever")):
            response = getattr(client, method)(path)
            assert response.status_code == 503, (method, path, response.status_code)
            assert response.json() == {"detail": STORAGE_UNAVAILABLE_DETAIL}
            body = response.text
            for secret in ("leaky_user", "leaky_password", "nowhere", "127.0.0.1:1"):
                assert secret not in body, f"{secret} leaked through {path}"


@pytest.mark.spec
def test_storage_error_handler_is_registered_for_the_engine_exception(dead_settings):
    """The handler is keyed on the engine's own error, not on a driver class.

    Every backend promises `StorageError`; none of them promises a psycopg
    exception. A handler registered on the driver would work today and stop
    working the moment a second backend appears.
    """
    app = create_app(dead_settings)
    assert StorageError in app.exception_handlers
