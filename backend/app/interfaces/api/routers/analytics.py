from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.application.dto import Actor, Bucket, EpisodeFilters, GroupBy
from app.composition import Container
from app.domain.enums import Quality
from app.domain.errors import ValidationFailed
from app.interfaces.api.deps import STAFF, get_container, require_roles
from app.interfaces.api.schemas import BreakdownRow, OverviewOut, TimeseriesPoint

router = APIRouter(prefix="/analytics", tags=["analytics"])
_staff = require_roles(*STAFF)


def _filters(
    task_name: str | None = None,
    quality: list[Quality] | None = Query(None),
    robot_id: str | None = None,
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
) -> EpisodeFilters:
    for name, value in (("recorded_from", recorded_from), ("recorded_to", recorded_to)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValidationFailed(f"{name} must include a timezone.")
    if recorded_from is not None and recorded_to is not None and recorded_from >= recorded_to:
        raise ValidationFailed(
            "recorded_from must be earlier than recorded_to.",
            recorded_from=recorded_from.isoformat(),
            recorded_to=recorded_to.isoformat(),
        )
    return EpisodeFilters(
        task_name=" ".join(task_name.split()).lower() if task_name else None,
        qualities=quality,
        robot_id=robot_id.strip().lower() if robot_id else None,
        recorded_from=recorded_from,
        recorded_to=recorded_to,
    )


@router.get("/overview", response_model=OverviewOut)
async def overview(
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    filters = _filters(recorded_from=recorded_from, recorded_to=recorded_to)
    return await c.analytics.overview(actor, filters.recorded_from, filters.recorded_to)


@router.get("/episodes/breakdown", response_model=list[BreakdownRow])
async def breakdown(
    group_by: GroupBy = "task_name",
    filters: EpisodeFilters = Depends(_filters),
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    """count / total / avg / min / max / p50 / p90 / p95 duration per group - all computed in PostgreSQL."""
    return await c.analytics.breakdown(actor, group_by, filters)


@router.get(
    "/episodes/timeseries",
    response_model=list[TimeseriesPoint],
    response_model_exclude_none=True,
)
async def timeseries(
    bucket: Bucket = "day",
    per_robot: bool = Query(False, description="Return one row per day and robot."),
    filters: EpisodeFilters = Depends(_filters),
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    return await c.analytics.timeseries(actor, bucket, filters, per_robot)
