"""Tests of ``web/auth.py`` (ACU-278): the on/off switch, and validation of a
session against Clerk's JWKS.

No live Postgres is needed, for the same reason as ``tests/test_web_wiring.py``:
``require_session`` runs before a route body touches storage, so a dead DSN
tells apart a 401 (rejected before the route ran) from a 503 (reached the
route, then hit a dead database) without a real database anywhere.

Every "valid token" test signs its own JWT with a throwaway RSA key generated
in this module and monkeypatches ``web.auth._jwks_client`` to hand back that
key instead of fetching Clerk's real JWKS - the network call is faked, but
``jwt.decode`` itself runs unmodified, so a wrong signature, issuer or
expiry is caught by the real verification code, not by a test that manufactures
the exception it then asserts on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from web.app import create_app
from web.config import (
    AUTH_DISABLED_VAR,
    CLERK_AUTHORIZED_PARTIES_VAR,
    CLERK_ISSUER_VAR,
    DATABASE_URL_VAR,
    ConfigurationError,
    Settings,
)
import web.app as app_module
import web.auth as auth_module

DEAD_DSN = "postgresql://nobody:nobody@127.0.0.1:1/nowhere"
ISSUER = "https://example-app.clerk.accounts.example"


def _settings(**overrides) -> Settings:
    # Auth off unless a test configures an issuer: the explicit switch, since
    # leaving both unset is now a configuration error (fail closed).
    overrides.setdefault("auth_disabled", not overrides.get("clerk_issuer"))
    return Settings(
        database_url=DEAD_DSN, schema=None, host="127.0.0.1", port=8000, **overrides
    )


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


class _StubSigningKey:
    def __init__(self, key):
        self.key = key


class _StubJwksClient:
    """Stands in for ``jwt.PyJWKClient``: same one method this module calls,
    backed by the test's own key instead of a network fetch."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return _StubSigningKey(self._public_key)


def _token(private_key, *, issuer=ISSUER, expires_delta=timedelta(minutes=5), **extra) -> str:
    now = datetime.now(timezone.utc)
    claims = {"iss": issuer, "sub": "user_123", "iat": now, "exp": now + expires_delta}
    claims.update(extra)
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.fixture
def stub_jwks(monkeypatch, keypair):
    """Routes ``_jwks_client(ISSUER)`` to the test's own key, whatever
    issuer string a given test signs its token with - a mismatched issuer
    must be rejected by ``jwt.decode``'s own ``issuer=`` check, not by the
    lookup never finding a client."""
    _, public_key = keypair
    monkeypatch.setattr(auth_module, "_jwks_client", lambda issuer: _StubJwksClient(public_key))


@pytest.mark.spec
def test_auth_disabled_switch_lets_every_route_answer_with_no_token():
    """The explicit off switch, which the rest of the suite relies on."""
    settings = _settings()
    assert settings.clerk_issuer is None
    assert settings.auth_disabled is True
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics")
    # No 401: the dead DSN is reached and answers 503, proving the request
    # was never stopped for lack of a session.
    assert response.status_code == 503


@pytest.mark.spec
def test_from_env_issuer_actually_enables_auth_and_reaches_the_config_endpoint():
    """The one link every test above skips by building `Settings` by hand."""
    env = {
        "LEARNING_TRACKER_DATABASE_URL": DEAD_DSN,
        "LEARNING_TRACKER_CLERK_ISSUER": ISSUER + "/",
        "LEARNING_TRACKER_CLERK_PUBLISHABLE_KEY": "pk_test_x",
    }
    settings = Settings.from_env(env)
    assert settings.clerk_issuer == ISSUER  # trailing slash stripped
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        assert client.get("/topics").status_code == 401
        assert client.get("/auth/config").json()["publishableKey"] == "pk_test_x"


@pytest.mark.spec
def test_health_and_auth_config_never_require_a_session():
    settings = _settings(clerk_issuer=ISSUER, clerk_publishable_key="pk_test_x")
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        health = client.get("/health")
        config = client.get("/auth/config")
    assert health.status_code in (200, 503)
    assert config.status_code == 200
    assert config.json() == {
        "enabled": True,
        "publishableKey": "pk_test_x",
        "issuer": ISSUER,
    }


@pytest.mark.spec
def test_auth_config_reports_disabled_with_no_publishable_key_when_off():
    with TestClient(create_app(_settings()), raise_server_exceptions=False) as client:
        response = client.get("/auth/config")
    assert response.json() == {"enabled": False, "publishableKey": None, "issuer": None}


@pytest.mark.spec
def test_missing_authorization_header_is_401():
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics")
    assert response.status_code == 401
    assert response.json() == {"detail": "missing session"}


@pytest.mark.spec
@pytest.mark.parametrize(
    "header",
    ["not-a-bearer-token", "Bearer", "Basic dXNlcjpwYXNz"],
)
def test_malformed_authorization_header_is_401(header):
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json() == {"detail": "missing session"}


@pytest.mark.spec
def test_valid_session_reaches_the_route_past_auth(stub_jwks, keypair):
    """Proves auth actually lets a good token through, rather than every
    path merely happening to 401: a live signature that verifies still hits
    the dead database and comes back 503, not 401."""
    private_key, _ = keypair
    settings = _settings(clerk_issuer=ISSUER)
    token = _token(private_key)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503


@pytest.mark.spec
def test_expired_session_says_so_not_a_generic_rejection(stub_jwks, keypair):
    """A silent failure is worse than a visible one: an expired session must
    not read like an empty list, or like any other 401."""
    private_key, _ = keypair
    token = _token(private_key, expires_delta=timedelta(minutes=-5))
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "session expired"}


@pytest.mark.edge
def test_token_signed_by_a_different_key_is_rejected(stub_jwks):
    """The signature check is real: a token that is well-formed and claims
    the right issuer, but was never signed by Clerk's key, must still fail."""
    forger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(forger)
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid session"}


@pytest.mark.edge
def test_token_for_a_different_issuer_is_rejected(stub_jwks, keypair):
    private_key, _ = keypair
    token = _token(private_key, issuer="https://someone-elses-app.clerk.accounts.dev")
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid session"}


@pytest.mark.spec
def test_no_issuer_and_no_switch_refuses_to_start():
    """Fail closed: a deploy that forgot the issuer must not serve anyone."""
    with pytest.raises(ConfigurationError, match=CLERK_ISSUER_VAR):
        Settings.from_env({DATABASE_URL_VAR: DEAD_DSN})
    with pytest.raises(ConfigurationError):
        Settings(database_url=DEAD_DSN, schema=None, host="127.0.0.1", port=8000)


@pytest.mark.spec
def test_issuer_and_switch_together_is_a_configuration_error():
    env = {DATABASE_URL_VAR: DEAD_DSN, CLERK_ISSUER_VAR: ISSUER, AUTH_DISABLED_VAR: "true"}
    with pytest.raises(ConfigurationError, match=AUTH_DISABLED_VAR):
        Settings.from_env(env)


@pytest.mark.spec
@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", " Yes "])
def test_auth_disabled_switch_accepts_the_contract_spellings(value):
    settings = Settings.from_env({DATABASE_URL_VAR: DEAD_DSN, AUTH_DISABLED_VAR: value})
    assert settings.auth_disabled is True


@pytest.mark.edge
@pytest.mark.parametrize("value", ["false", "0", "no"])
def test_auth_disabled_switch_off_still_requires_an_issuer(value):
    with pytest.raises(ConfigurationError, match=CLERK_ISSUER_VAR):
        Settings.from_env({DATABASE_URL_VAR: DEAD_DSN, AUTH_DISABLED_VAR: value})


@pytest.mark.edge
def test_auth_disabled_switch_rejects_an_ambiguous_value():
    with pytest.raises(ConfigurationError, match=AUTH_DISABLED_VAR):
        Settings.from_env({DATABASE_URL_VAR: DEAD_DSN, AUTH_DISABLED_VAR: "enabled"})


@pytest.mark.spec
def test_main_exits_with_one_line_on_a_configuration_error(monkeypatch, capsys):
    monkeypatch.setattr("os.environ", {DATABASE_URL_VAR: DEAD_DSN})
    # `--migrate` included: the config check must come before the database
    # is touched (the DSN is dead, so a migration attempt would not exit 2).
    with pytest.raises(SystemExit) as raised:
        app_module.main(["--migrate"])
    assert raised.value.code == 2
    assert capsys.readouterr().err.startswith("error: authentication is not configured")


@pytest.mark.spec
def test_authorized_parties_are_parsed_from_a_comma_separated_list():
    env = {
        DATABASE_URL_VAR: DEAD_DSN,
        CLERK_ISSUER_VAR: ISSUER,
        CLERK_AUTHORIZED_PARTIES_VAR: "https://a.example/, https://b.example ,,",
    }
    settings = Settings.from_env(env)
    assert settings.clerk_authorized_parties == ("https://a.example", "https://b.example")


@pytest.mark.spec
def test_token_with_an_authorized_azp_reaches_the_route(stub_jwks, keypair):
    private_key, _ = keypair
    token = _token(private_key, azp="https://learning.example")
    settings = _settings(clerk_issuer=ISSUER, clerk_authorized_parties=("https://learning.example",))
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503  # past auth, into the dead database


@pytest.mark.edge
@pytest.mark.parametrize("azp", ["https://other-product.example", None])
def test_token_minted_for_another_origin_is_rejected(stub_jwks, keypair, azp):
    """One Clerk instance serves every product: a token for another
    product's origin, or one with no `azp` at all, must not get in."""
    private_key, _ = keypair
    token = _token(private_key, azp=azp)
    settings = _settings(clerk_issuer=ISSUER, clerk_authorized_parties=("https://learning.example",))
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid session"}


@pytest.mark.edge
def test_token_without_sub_is_rejected(stub_jwks, keypair):
    private_key, _ = keypair
    token = _token(private_key, sub=None)
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/topics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.spec
def test_all_four_data_routers_require_a_session():
    """Every router registered with `session_required` in `web/app.py`, not
    just the one (`topics`) the tests above happen to exercise."""
    settings = _settings(clerk_issuer=ISSUER)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        for method, path in (
            ("get", "/topics"),
            ("get", "/topics/t1/material"),
            ("get", "/topics/t1/practice/next"),
            ("get", "/topics/t1/summary"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 401, (method, path, response.status_code)
