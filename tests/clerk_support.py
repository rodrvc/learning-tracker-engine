"""Shared helpers for tests that need signed Clerk-style session tokens.

Only the JWKS lookup is faked (``web.auth._jwks_client``); ``jwt.decode`` runs
unmodified, so a wrong signature, issuer or expiry is still caught by the real
verification code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

ISSUER = "https://example-app.clerk.accounts.example"


class StubSigningKey:
    def __init__(self, key):
        self.key = key


class StubJwksClient:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return StubSigningKey(self._public_key)


def bearer(private_key, sub: str, **claims) -> dict[str, str]:
    """An ``Authorization`` header for ``sub``; extra keyword arguments become
    claims (e.g. ``o={"id": "org_1", "rol": "admin"}`` for the v2 shape)."""
    now = datetime.now(timezone.utc)
    payload = {
        "iss": ISSUER,
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **claims,
    }
    return {"Authorization": "Bearer " + jwt.encode(payload, private_key, algorithm="RS256")}
