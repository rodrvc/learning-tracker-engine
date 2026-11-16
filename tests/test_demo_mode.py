"""Demo mode (issue #81) needs no database to be checked: the configuration
rule is the safety property, and the endpoint's wiring with real seeded members
is covered end to end in ``tests/test_seed_demo.py``.
"""

from __future__ import annotations

import pytest

from web.config import (
    AUTH_DISABLED_VAR,
    CLERK_ISSUER_VAR,
    DATABASE_URL_VAR,
    DEMO_MODE_VAR,
    ConfigurationError,
    Settings,
)

_ENV = {DATABASE_URL_VAR: "postgresql://u:p@127.0.0.1:1/x"}


def test_demo_mode_refuses_to_start_with_authentication_on():
    env = {**_ENV, CLERK_ISSUER_VAR: "https://clerk.example", DEMO_MODE_VAR: "true"}
    with pytest.raises(ConfigurationError, match=DEMO_MODE_VAR):
        Settings.from_env(env)


def test_demo_mode_needs_auth_explicitly_off_even_when_built_by_hand():
    with pytest.raises(ConfigurationError):
        Settings(database_url="x", schema=None, host="h", port=1, clerk_issuer="https://c.example", demo_mode=True)


def test_demo_mode_is_off_by_default_and_on_with_auth_disabled():
    assert Settings.from_env({**_ENV, AUTH_DISABLED_VAR: "true"}).demo_mode is False
    assert Settings.from_env({**_ENV, AUTH_DISABLED_VAR: "true", DEMO_MODE_VAR: "true"}).demo_mode is True
