"""One error envelope for the whole API:  {"error": {"code", "message", "details"}}."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain import errors as e

log = logging.getLogger(__name__)

# Most specific first: resolved by walking the exception's MRO.
_STATUS: dict[type[Exception], int] = {
    e.InvalidCursor: 400,
    e.InvalidImportFile: 400,
    e.NotFound: 404,
    e.AuthenticationFailed: 401,
    e.PermissionDenied: 403,
    e.Conflict: 409,
    e.ValidationFailed: 422,
    e.PayloadTooLarge: 413,
    e.ResourceBusy: 503,
}


def _status_for(exc: Exception) -> int:
    for cls in type(exc).__mro__:
        if cls in _STATUS:
            return _STATUS[cls]
    return 400


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(e.DomainError)
    async def _domain(_: Request, exc: e.DomainError) -> JSONResponse:
        status = _status_for(exc)
        headers: dict[str, str] = {}
        if status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        if status == 503:
            headers["Retry-After"] = "1"
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(_body("validation_failed", "The request is invalid.", {"fields": fields}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled API exception", exc_info=exc)
        return JSONResponse(
            _body("internal_error", "An unexpected server error occurred."),
            status_code=500,
        )
