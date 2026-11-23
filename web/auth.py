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
(``web/config.py``) and off only by ``Settings.auth_disabled``, which the
test suite sets explicitly. Neither set is a configuration error raised at
startup, so this module never sees that state (fail closed, product contract
section 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from store.postgres import LOCAL_USER_ID

#: Clerk signs session tokens with RS256. Pinning the algorithm list is the
#: point of PyJWT's ``algorithms=`` argument: without it, a token that names
#: its own algorithm (including ``none``) would be trusted to say how it
#: should be checked.
ALGORITHMS = ["RS256"]

#: The role that may read an organization's progress (the "teacher" of #75).
ORG_ADMIN_ROLE = "org:admin"

#: Headers that pick a demo identity when - and only when - authentication is
#: off. See :func:`_dev_identity`.
DEV_USER_HEADER = "x-dev-user"
DEV_ORG_HEADER = "x-dev-org"
DEV_ROLE_HEADER = "x-dev-role"
DEV_NAME_HEADER = "x-dev-name"


@dataclass(frozen=True)
class Identity:
    """Who a request is from, as established by this module and nobody else.

    ``user_id`` comes only from the verified session token's ``sub`` claim
    (or is ``LOCAL_USER_ID`` when authentication is off). Routes never read
    it from a path, a query string or a body: every store the request touches
    is bound to this value in ``web/deps.py``.

    ``org_id`` and ``org_role`` are the session's *active organization* and the
    user's role in it, read from the same verified token (``org_role`` always
    carries Clerk's ``org:`` prefix, e.g. ``org:admin``). Both are ``None`` when
    the session has no active organization.
    """

    user_id: str
    org_id: str | None = None
    org_role: str | None = None
    name: str | None = None
    email: str | None = None

    @property
    def is_org_admin(self) -> bool:
        return self.org_id is not None and self.org_role == ORG_ADMIN_ROLE


class SessionError(HTTPException):
    """A request that does not carry a valid Clerk session.

    Always 401: this is "who are you", not "you may not do that". The
    ``detail`` distinguishes an absent token from an expired or otherwise
    invalid one - a silent failure (an expired session quietly returning an
    empty list) is worse than a visible 401 that says so.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=401, detail=detail)


def normalize_role(role: object) -> str | None:
    """Clerk's v2 tokens carry the short role (``admin``), v1 the full key
    (``org:admin``). Everything downstream compares the full key."""
    if not isinstance(role, str) or not role.strip():
        return None
    role = role.strip()
    return role if role.startswith("org:") else f"org:{role}"


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def identity_from_claims(claims: dict) -> Identity:
    """Builds the identity from an already *verified* claim set.

    Both token shapes are read: v2 nests the active organization under ``o``
    (``o.id``, ``o.rol``), v1 uses flat ``org_id`` / ``org_role``. A role with
    no organization is dropped: it would mean nothing.
    """
    org = claims.get("o")
    if isinstance(org, dict):
        org_id, org_role = _text(org.get("id")), normalize_role(org.get("rol"))
    else:
        org_id, org_role = _text(claims.get("org_id")), normalize_role(claims.get("org_role"))
    if org_id is None:
        org_role = None
    return Identity(
        user_id=claims["sub"],
        org_id=org_id,
        org_role=org_role,
        name=_text(claims.get("name")),
        email=_text(claims.get("email")),
    )


def _dev_identity(request: Request) -> Identity:
    """A demo identity chosen by request headers, for showing the teacher view
    without Clerk. Reached only from the authentication-off branch of
    :func:`require_session` (``auth_disabled``): with an issuer configured these headers are never
    read, so they cannot be used to claim an identity on a real deployment.
    """
    headers = request.headers
    user = _text(headers.get(DEV_USER_HEADER))
    if user is None:
        return Identity(user_id=LOCAL_USER_ID)
    org = _text(headers.get(DEV_ORG_HEADER))
    return Identity(
        user_id=user,
        org_id=org,
        org_role=normalize_role(headers.get(DEV_ROLE_HEADER)) if org else None,
        name=_text(headers.get(DEV_NAME_HEADER)),
    )


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


def require_session(request: Request) -> Identity:
    """FastAPI dependency: raises unless the request carries a valid Clerk
    session for the configured issuer, and returns who it is from.

    With ``auth_disabled`` set it returns the one implicit local user (or a
    demo identity named by ``X-Dev-*`` headers, see :func:`_dev_identity`)
    without reading the ``Authorization`` header at all, which is how the
    suite and a single-user install keep working. When
    ``clerk_authorized_parties`` is configured, the token's ``azp`` must be
    one of them: every product shares one Clerk instance, so otherwise a
    token minted for another product's origin would pass.

    Reads ``request.app.state.settings`` rather than taking ``Settings`` as
    a parameter so it can be attached to a router with a plain
    ``Depends(require_session)``, the same shape every other dependency in
    this codebase uses (``web/deps.py``'s ``get_resources``).
    """
    settings = request.app.state.settings
    if settings.auth_disabled:
        return _dev_identity(request)
    issuer = settings.clerk_issuer
    token = _bearer_token(request.headers.get("authorization"))
    client = _jwks_client(issuer)
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        # Without ``require`` a token from this issuer carrying no ``exp`` verifies and never expires.
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise SessionError("session expired") from exc
    except jwt.PyJWTError as exc:
        raise SessionError("invalid session") from exc
    parties = settings.clerk_authorized_parties
    if parties and claims.get("azp") not in parties:
        raise SessionError("invalid session")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise SessionError("invalid session")
    return identity_from_claims({**claims, "sub": subject})


__all__ = [
    "Identity",
    "ORG_ADMIN_ROLE",
    "SessionError",
    "identity_from_claims",
    "normalize_role",
    "require_session",
]
