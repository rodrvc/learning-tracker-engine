"""Tests of the ``webui/`` static mount (ACU-265): the app serves the front
end's files, and doing so never shadows the API.

No database is needed, the same reasoning as ``test_web_wiring.py``: building
resources against an unreachable DSN does not raise, because the pool
connects lazily.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.app import create_app
from web.config import Settings

DEAD_DSN = "postgresql://nobody:nobody@127.0.0.1:1/nowhere"


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url=DEAD_DSN, schema=None, host="127.0.0.1", port=8000)


@pytest.mark.spec
def test_root_serves_the_webui_index(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Learning Tracker" in response.text


@pytest.mark.spec
def test_root_serves_the_api_client_as_javascript(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/js/api.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


@pytest.mark.spec
def test_static_mount_does_not_shadow_the_api_routes(settings):
    """Registered after the routers, ``/topics`` still resolves as the JSON
    API, not as a 404 from the static handler looking for a file by that
    name. The dead DSN turns the call into a 503 rather than a real answer,
    which is itself proof the request reached the topics router at all."""
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.spec
def test_missing_file_is_a_plain_404_not_a_crash(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/does-not-exist.js")
    assert response.status_code == 404


@pytest.mark.spec
def test_trailing_slash_on_an_api_route_is_404_not_redirected(settings):
    """A real trade-off, pinned rather than left as an accident.

    Starlette's ``redirect_slashes`` (``/topics/`` -> 307 to ``/topics``)
    only fires when *no* route matches at all; ``Mount("/", ...)`` always
    matches, so it wins before that fallback runs and ``/topics/`` now gets
    ``StaticFiles``' own 404 instead of a redirect into the topics router.
    Accepted because no documented URL here (``INTEGRATION.md``, ``README.md``,
    the routers' own docstrings) is written with a trailing slash, and the
    front end itself never produces one - a caller who does type it gets a
    plain 404, not a silent failure, and it is not worth a route in front of
    the mount to preserve a convenience nothing relies on.
    """
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics/", follow_redirects=False)
    assert response.status_code == 404
