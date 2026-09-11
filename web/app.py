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

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import Settings
from .deps import build_resources, close_resources
from .routers import topics


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
        """Reports whether storage actually answers, not merely that the process is up."""
        healthy = app.state.resources.is_healthy()
        return JSONResponse(
            {"status": "ok" if healthy else "unhealthy"},
            status_code=200 if healthy else 503,
        )

    app.include_router(topics.router)
    return app


def main() -> None:
    """Entry point for ``python -m web.app``."""
    import uvicorn

    settings = Settings.from_env(os.environ)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()


__all__ = ["create_app", "main"]
