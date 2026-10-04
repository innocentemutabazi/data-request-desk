from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile

from app.application.dto import Actor, Availability, EpisodeFilters
from app.composition import Container
from app.domain.enums import Quality
from app.domain.errors import InvalidImportFile, PayloadTooLarge
from app.interfaces.api.deps import STAFF, current_actor, get_container, require_roles
from app.interfaces.api.schemas import (
    EpisodeOut,
    ImportReportOut,
    PageOut,
    TaskCount,
    to_episode_out,
    to_import_report_out,
)

router = APIRouter(tags=["episodes"])


@router.post("/episodes/import", response_model=ImportReportOut)
async def import_episodes(
    file: UploadFile,
    actor: Actor = Depends(require_roles(*STAFF)),
    c: Container = Depends(get_container),
):
    """Upload `episodes.csv`. Idempotent (ON CONFLICT DO NOTHING); returns a full cleaning report."""
    if file.size is not None and file.size > c.settings.max_import_bytes:
        raise PayloadTooLarge(f"File exceeds the {c.settings.max_import_bytes // (1024 * 1024)} MiB limit.")
    if file.filename and not file.filename.lower().endswith((".csv", ".txt")):
        raise InvalidImportFile("Upload a .csv file.")
    # utf-8-sig strips a BOM; errors="replace" lets bad bytes surface as per-row rejections
    # instead of aborting a multi-million-row import on row 4,000,000.
    text = io.TextIOWrapper(file.file, encoding="utf-8-sig", errors="replace", newline="")
    try:
        report = await c.imports.import_csv(text, file.filename)
    finally:
        text.detach()  # don't let the wrapper close the upload's underlying file
    c.catalog.invalidate()
    return to_import_report_out(report)


@router.get("/episodes", response_model=PageOut[EpisodeOut])
async def list_episodes(
    task_name: str | None = None,
    quality: list[Quality] | None = Query(None),
    robot_id: str | None = None,
    recorded_from: datetime | None = Query(None, description="inclusive"),
    recorded_to: datetime | None = Query(None, description="exclusive"),
    availability: Availability = "all",
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    actor: Actor = Depends(require_roles(*STAFF)),
    c: Container = Depends(get_container),
):
    """Newest first, keyset-paginated: cost per page is constant no matter how deep you scroll."""
    filters = EpisodeFilters(
        task_name=" ".join(task_name.split()).lower() if task_name else None,
        qualities=quality,
        robot_id=robot_id.strip().lower() if robot_id else None,
        recorded_from=recorded_from,
        recorded_to=recorded_to,
        availability=availability,
    )
    page = await c.episodes.list(actor, filters, limit, cursor)
    return PageOut[EpisodeOut](
        items=[to_episode_out(v.episode, v.assigned_request_id) for v in page.items], next_cursor=page.next_cursor
    )


@router.get("/catalog/tasks", response_model=list[TaskCount], tags=["catalog"])
async def catalog_tasks(_: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    """Distinct task names with episode counts (cached) - feeds the request form."""
    return [TaskCount(task_name=name, episodes=n) for name, n in await c.catalog.tasks()]
