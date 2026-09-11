"""Validates a Clerk session, as a FastAPI dependency.

The engine never learns a login exists: this module is pure web layer, wired
onto routers in ``web/app.py`` via ``Depends``, and nothing under ``core/``
imports it or anything from it.

Verification is signature-plus-claims against Clerk's JWKS (its signing keys,
published at ``<issuer>/.well-known/jwks.json`` and public by design), using
``PyJWT`` rather than a hand-rolled decode: a validator that reads a token
without checking its signature is worse than none, because it looks like
protection while checking nothing.

Authentication is switched on by configuring ``Settings.clerk_issuer``
(``web/config.py``) and switched off by leaving it unset - which is the
default everywhere the test suite runs, so 661 pre-existing tests keep
talking to the API with no notion of a session.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

#: Clerk signs session tokens with RS256. Pinning the algorithm list is the
#: point of PyJWT's ``algorithms=`` argument: without it, a token that names
#: its own algorithm (including ``none``) would be trusted to say how it
#: should be checked.
ALGORITHMS = ["RS256"]


class SessionError(HTTPException):
    """A request that does not carry a valid Clerk session.

    Always 401: this is "who are you", not "you may not do that". The
    ``detail`` distinguishes an absent token from an expired or otherwise
    invalid one - a silent failure (an expired session quietly returning an
    empty list) is worse than a visible 401 that says so.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=401, detail=detail)


@lru_cache(maxsize=8)
def _jwks_client(issuer: str) -> PyJWKClient:
    """One cached client per issuer: it keeps Clerk's signing keys around
    instead of fetching the public JWKS over the network on every request."""
    return PyJWKClient(f"{issuer}/.well-known/jwks.json")


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise SessionError("missing session")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise SessionError("missing session")
    return token


def require_session(request: Request) -> None:
    """FastAPI dependency: raises unless the request carries a valid Clerk
    session for the configured issuer.

    A no-op - returns without reading the ``Authorization`` header at all -
    when ``clerk_issuer`` is unset, which is how the suite and any
    single-user deployment that never configured Clerk keep working exactly
    as they did before this module existed.

    Reads ``request.app.state.settings`` rather than taking ``Settings`` as
    a parameter so it can be attached to a router with a plain
    ``Depends(require_session)``, the same shape every other dependency in
    this codebase uses (``web/deps.py``'s ``get_resources``).
    """
    issuer = request.app.state.settings.clerk_issuer
    if not issuer:
        return
    token = _bearer_token(request.headers.get("authorization"))
    client = _jwks_client(issuer)
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        # Without ``require`` a token from this issuer carrying no ``exp`` verifies and never expires.
        jwt.decode(token, signing_key.key, algorithms=ALGORITHMS, issuer=issuer, options={"require": ["exp"]})
    except jwt.ExpiredSignatureError as exc:
        raise SessionError("session expired") from exc
    except jwt.PyJWTError as exc:
        raise SessionError("invalid session") from exc


__all__ = ["SessionError", "require_session"]
