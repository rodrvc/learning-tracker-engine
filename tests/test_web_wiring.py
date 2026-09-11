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

import dataclasses

import pytest
from fastapi.testclient import TestClient

from core.errors import StorageError
from core.models import ObjectiveState, ProfileSummary, StateComparison
from web.app import STORAGE_UNAVAILABLE_DETAIL, create_app
from web.config import DATABASE_URL_VAR, MissingSettingError, Settings
from web import deps
from web.deps import build_resources, close_resources
from web.routers.progress import ObjectiveStateOut, ProfileSummaryOut, StateComparisonOut

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
def test_storage_failure_is_503_and_never_echoes_the_connection_string(
    dead_settings, monkeypatch
):
    """A dead database answers 503, and the answer names nothing.

    Before this handler existed every route answered a dead database with a
    generic 500, discarding the guarantee ``store.postgres`` goes to some
    length to provide. The obvious fix would have been worse than the problem:
    those ``StorageError`` messages interpolate the driver's text, and a
    psycopg connection error embeds host, port, user and database name. So the
    detail is constant and this test pins that it stays constant.
    """
    # How long the pool waits for a connection is irrelevant to what this
    # proves, and at the production value it made this one test fifteen times
    # slower than the slowest of the other five hundred. ``build_resources``
    # reads the module global when it is called, which is inside the lifespan,
    # so patching it here reaches the pool without a parameter nobody asked for.
    monkeypatch.setattr(deps, "POOL_CHECKOUT_TIMEOUT_SECONDS", 0.05)
    with TestClient(create_app(dead_settings), raise_server_exceptions=False) as client:
        for method, path in (
            ("get", "/topics"),
            ("get", "/topics/whatever"),
            ("get", "/topics/whatever/objectives/states"),
            ("get", "/topics/whatever/objectives/due"),
            ("get", "/topics/whatever/objectives/unstarted"),
            ("get", "/topics/whatever/objectives/stale"),
            ("get", "/topics/whatever/summary"),
            (
                "get",
                "/topics/whatever/objectives/whichever/compare"
                "?earlier=2020-01-01T00:00:00Z&later=2020-01-02T00:00:00Z",
            ),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 503, (method, path, response.status_code)
            assert response.json() == {"detail": STORAGE_UNAVAILABLE_DETAIL}
            body = response.text
            for secret in ("leaky_user", "leaky_password", "nowhere", "127.0.0.1:1"):
                assert secret not in body, f"{secret} leaked through {path}"


@pytest.mark.spec
def test_health_reports_unhealthy_when_storage_is_unreachable(dead_settings):
    """The half of the health endpoint that says something is wrong.

    The happy path is covered against a live database in ``tests/test_web.py``.
    This is the branch that matters operationally, and it needs a database that
    does not answer, so it belongs here rather than in a module whose fixture
    demands one.

    It was briefly lost: it lived in the module-scoped file, was deleted rather
    than moved when the database-free tests were split out, and for one commit
    the whole suite stayed green with an endpoint reporting "ok" over dead
    storage (ACU-246 review).
    """
    with TestClient(create_app(dead_settings), raise_server_exceptions=False) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy"}


@pytest.mark.spec
def test_storage_error_handler_is_registered_for_the_engine_exception(dead_settings):
    """The handler is keyed on the engine's own error, not on a driver class.

    Every backend promises `StorageError`; none of them promises a psycopg
    exception. A handler registered on the driver would work today and stop
    working the moment a second backend appears.
    """
    app = create_app(dead_settings)
    assert StorageError in app.exception_handlers


#: A naive `as_of`/`earlier`/`later`, in both the plain-date and the
#: plain-datetime shape an HTML `<input type="date">` or `type="datetime-local">`
#: produces. No database is touched: query parameter validation happens before
#: the endpoint body (and therefore before any store call) runs, so a dead DSN
#: exercises exactly the same validation path as a live one.
NAIVE_CUT_DATE_PATHS = [
    "/topics/whatever/objectives/states?as_of=2026-02-10",
    "/topics/whatever/objectives/states?as_of=2026-02-10T00:00:00",
    "/topics/whatever/objectives/due?as_of=2026-02-10",
    "/topics/whatever/objectives/unstarted?as_of=2026-02-10",
    "/topics/whatever/objectives/stale?as_of=2026-02-10",
    "/topics/whatever/summary?as_of=2026-02-10",
    "/topics/whatever/objectives/whichever/compare"
    "?earlier=2026-02-10&later=2026-02-11T00:00:00Z",
    "/topics/whatever/objectives/whichever/compare"
    "?earlier=2026-02-10T00:00:00Z&later=2026-02-11",
]


@pytest.mark.edge
@pytest.mark.parametrize("path", NAIVE_CUT_DATE_PATHS)
def test_naive_cut_date_is_422_not_500(dead_settings, path):
    """A cut date without a timezone is rejected, not coerced or crashed on.

    Before ``AwareDatetime``, FastAPI parsed a naive value happily and the
    naive/aware comparison inside ``core/leveling.py`` blew up into a 500 —
    on exactly the parameter shape an HTML date input produces, which is the
    first thing a page built on this API would send. Assuming UTC for a
    naive input was rejected as a fix: it would make "was I better two weeks
    ago" depend on server configuration, the same silent reshaping the
    recompute-nothing rule forbids elsewhere in this router.
    """
    with TestClient(create_app(dead_settings), raise_server_exceptions=False) as client:
        response = client.get(path)
    assert response.status_code == 422, (path, response.status_code, response.text)


@pytest.mark.spec
def test_objective_state_out_matches_the_engine_field_for_field():
    """The response model can neither drop nor add a field of `ObjectiveState`.

    This single assertion catches both directions of drift: the engine gains
    a field the API forgets to surface, and the API gains one the engine does
    not have — which is the only way a `streak`/run count could ever sneak
    back into this response (SPEC I10).
    """
    engine_fields = {field.name for field in dataclasses.fields(ObjectiveState)}
    api_fields = set(ObjectiveStateOut.model_fields)
    assert api_fields == engine_fields


@pytest.mark.spec
def test_state_comparison_out_matches_the_engine_field_for_field():
    engine_fields = {field.name for field in dataclasses.fields(StateComparison)}
    api_fields = set(StateComparisonOut.model_fields)
    assert api_fields == engine_fields


@pytest.mark.spec
def test_profile_summary_out_matches_the_engine_field_for_field():
    """Same guarantee as the two checks above, with one deliberate exception:
    `profile_id` is renamed `topic_id` at this router's edge, the one
    vocabulary translation the module docstring documents (matching
    `topics.py`). Every other field must match exactly."""
    engine_fields = {field.name for field in dataclasses.fields(ProfileSummary)}
    api_fields = set(ProfileSummaryOut.model_fields)
    assert api_fields == (engine_fields - {"profile_id"}) | {"topic_id"}
