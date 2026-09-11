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
