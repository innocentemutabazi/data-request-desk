from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.composition import Container
from app.interfaces.api.deps import get_container

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(c: Container = Depends(get_container)):
    try:
        async with c.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}
