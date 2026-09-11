"""Application factory: assembles the FastAPI app and mounts routers.

Local development::

    LEARNING_TRACKER_DATABASE_URL=postgresql://learning_tracker:learning_tracker@localhost:5433/learning_tracker \\
        python -m web.app

or, with ``uvicorn`` directly (equivalent, ``--factory`` calls
:func:`create_app` itself so settings are read at server start, not at
import time)::

    LEARNING_TRACKER_DATABASE_URL=... uvicorn web.app:create_app --factory
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from content.errors import StorageError as ContentStorageError
from core.errors import StorageError

from .auth import require_session
from .config import MissingSettingError, Settings
from .deps import build_resources, close_resources
from .routers import material, practice, progress, topics

logger = logging.getLogger(__name__)

#: The front end lives entirely in ``webui/``, a sibling of this package, and
#: is mounted as plain static files - no templates, no server-side rendering.
#: Removing the front end is deleting that folder and the one ``app.mount``
#: call below.
WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"

#: What a caller is told when storage fails. Deliberately constant.
#:
#: ``store.postgres`` interpolates the driver's own text into its
#: ``StorageError`` messages, and a psycopg connection error embeds the host,
#: the port, the user and the database name. Returning ``str(exc)`` here would
#: publish all of that to anyone who can reach the API, so the detail is fixed
#: and the exception goes to the log instead.
STORAGE_UNAVAILABLE_DETAIL = "storage is unavailable"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Builds the FastAPI application.

    Args:
        settings: explicit settings, mainly for tests. ``None`` reads them
            from ``os.environ``, failing loudly (see
            ``web.config.MissingSettingError``) when something required is
            absent.
    """
    resolved = settings if settings is not None else Settings.from_env(os.environ)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.resources = build_resources(resolved)
        try:
            yield
        finally:
            close_resources(app.state.resources)

    app = FastAPI(title="Learning Tracker API", lifespan=lifespan)
    app.state.settings = resolved

    @app.get("/health")
    def health() -> JSONResponse:
        """Reports whether storage actually answers, not merely that the process is up.

        Deliberately outside ``require_session``: whatever probes this (a
        deploy platform, an uptime check) has no Clerk session and no way to
        get one, so gating it on authentication would not make it more
        secure, only useless for the one thing it exists to answer.
        """
        healthy = app.state.resources.is_healthy()
        return JSONResponse(
            {"status": "ok" if healthy else "unhealthy"},
            status_code=200 if healthy else 503,
        )

    @app.get("/auth/config")
    def auth_config() -> JSONResponse:
        """What the browser needs to start a Clerk session, and nothing it
        does not need: no secret ever lives on this path. Also outside
        ``require_session`` on purpose - a page cannot sign in to learn how
        to sign in."""
        return JSONResponse(
            {
                "enabled": resolved.clerk_issuer is not None,
                "publishableKey": resolved.clerk_publishable_key,
                # Not a secret: it is the same public URL a browser would
                # otherwise have to be told out of band, and it is where the
                # front end fetches Clerk's own script from (webui/js/auth.js).
                "issuer": resolved.clerk_issuer,
            }
        )

    @app.exception_handler(StorageError)
    @app.exception_handler(ContentStorageError)
    def storage_unavailable(request: Request, exc: Exception) -> JSONResponse:
        """Turns a storage failure into 503 instead of an opaque 500.

        ``store.postgres`` goes to some length to guarantee that every failure
        to reach the database surfaces as ``StorageError`` rather than a leaked
        driver exception, and ``content.postgres`` makes the same guarantee
        with its own ``StorageError`` class (the two packages do not share
        exception hierarchies, so both are registered here). Without this
        handler the web layer threw that guarantee away one level up: every
        route answered a dead database with a generic 500 and a traceback in
        the log, which tells a caller nothing and an operator little.

        503 is the honest code: the service cannot serve the request now and
        the caller may retry.
        """
        logger.exception("storage failure serving %s %s", request.method, request.url.path)
        return JSONResponse({"detail": STORAGE_UNAVAILABLE_DETAIL}, status_code=503)

    # Every data route requires a session (a no-op check while
    # `clerk_issuer` is unset, see `web/auth.py`); `/health` and
    # `/auth/config` above are registered directly on `app` and so never
    # pick this up.
    session_required = [Depends(require_session)]
    app.include_router(topics.router, dependencies=session_required)
    app.include_router(material.router, dependencies=session_required)
    app.include_router(practice.router, dependencies=session_required)
    app.include_router(progress.router, dependencies=session_required)
    # Registered last: a Mount only ever answers a request no router above
    # already matched, so the API keeps owning its paths and this is purely
    # the fallback that serves the page and its assets.
    app.mount("/", StaticFiles(directory=WEBUI_DIR, html=True), name="webui")
    return app


def main() -> None:
    """Entry point for ``python -m web.app``.

    A missing setting exits with a single line rather than a traceback. This is
    the first thing an operator meets on a deploy with an unset variable, and a
    stack trace makes them hunt for the one line that matters.
    """
    import uvicorn

    try:
        settings = Settings.from_env(os.environ)
    except MissingSettingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()


__all__ = ["create_app", "main"]
