from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.composition import Container, build_container
from app.core.config import get_settings
from app.interfaces.api.errors import install_error_handlers
from app.interfaces.api.routers import analytics, auth, episodes, health, requests, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
request_log = logging.getLogger("http.request")


def create_app(container: Container | None = None) -> FastAPI:
    settings = container.settings if container else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = container is None
        app.state.container = container or build_container(settings)
        recovery = asyncio.create_task(app.state.container.exports.recover_in_flight())
        try:
            yield
        finally:
            recovery.cancel()
            await asyncio.gather(recovery, return_exceptions=True)
            if owned:
                await app.state.container.engine.dispose()

    app = FastAPI(
        title="Dataset Request Desk API",
        version="1.0.0",
        description="Robot-episode dataset requests: state machine, pessimistic-lock assignment, idempotent import.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_logging(request, call_next):
        started = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            request_log.info(json.dumps({
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code if response is not None else 500,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "user_id": getattr(request.state, "user_id", None),
            }, separators=(",", ":")))
    if container is not None:  # tests use ASGITransport, which does not run lifespan events
        app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens in headers, no cookies => no CSRF surface
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)
    for module in (health, auth, requests, episodes, analytics, users):
        app.include_router(module.router)
    return app


app = create_app()
