"""Analytics as pure SQL aggregations.

Nothing here materialises episode rows in Python: PostgreSQL returns one row per group
(count / sum / avg / percentile_cont) and that is all that crosses the wire.
"""

from __future__ import annotations

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dto import Bucket, EpisodeFilters, GroupBy
from app.domain.enums import Quality, RequestStatus
from app.domain.models import Assignment, Episode, Request, RequestStatusHistory
from app.infrastructure.db.repositories.predicates import episode_predicates

_GROUP_COLUMNS = {
    "task_name": Episode.task_name,
    "robot_id": Episode.robot_id,
    "quality": Episode.quality,
    "operator_name": Episode.operator_name,
}
# Whitelisted literals only (never user input) - interpolated because date_trunc's unit must be a
# constant for the SELECT list and GROUP BY expression to be recognised as identical by PostgreSQL.
_BUCKET_LITERALS = {"day": "'day'", "week": "'week'", "month": "'month'"}


def _pct3(value_expr):
    """p50/p90/p95 via one percentile_cont call that returns a float[] (compact; benchmarked as
    equal in speed to three separate calls - PostgreSQL shares the sort either way)."""
    return func.percentile_cont(literal_column("ARRAY[0.5, 0.9, 0.95]")).within_group(value_expr)


def _r(v: float | None, digits: int = 1) -> float | None:
    return None if v is None else round(float(v), digits)


class SqlAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def overview(self, recorded_from=None, recorded_to=None) -> dict[str, object]:
        episode_filters = []
        if recorded_from is not None:
            episode_filters.append(Episode.recorded_at >= recorded_from)
        if recorded_to is not None:
            episode_filters.append(Episode.recorded_at < recorded_to)
        totals = (
            await self._s.execute(
                select(
                    func.count().label("episodes"),
                    func.coalesce(func.sum(Episode.duration_seconds), 0).label("total_seconds"),
                    func.avg(Episode.duration_seconds).label("avg_seconds"),
                    func.count().filter(Episode.quality == Quality.GOOD).label("good"),
                    func.count().filter(Episode.quality == Quality.USABLE).label("usable"),
                    func.count().filter(Episode.quality == Quality.BAD).label("bad"),
                ).where(*episode_filters)
            )
        ).one()
        assigned = (
            await self._s.execute(
                select(func.count())
                .select_from(Assignment)
                .join(Episode, Episode.episode_id == Assignment.episode_id)
                .where(Assignment.released_at.is_(None), *episode_filters)
            )
        ).scalar_one()
        return {
            "episodes_total": int(totals.episodes),
            "episodes_assigned": int(assigned),
            "episodes_available": int(totals.episodes) - int(assigned),
            "total_duration_seconds": int(totals.total_seconds),
            "avg_duration_seconds": _r(totals.avg_seconds),
            "quality": {"good": int(totals.good), "usable": int(totals.usable), "bad": int(totals.bad)},
        }

    async def episode_breakdown(self, group_by: GroupBy, filters: EpisodeFilters) -> list[dict[str, object]]:
        key = _GROUP_COLUMNS[group_by]
        dur = Episode.duration_seconds
        stmt = (
            select(
                key.label("key"),
                func.count().label("episodes"),
                func.sum(dur).label("total_duration_seconds"),
                func.avg(dur).label("avg_duration_seconds"),
                func.min(dur).label("min_duration_seconds"),
                func.max(dur).label("max_duration_seconds"),
                _pct3(dur).label("pcts"),
                func.count().filter(Episode.quality == Quality.GOOD).label("good"),
                func.count().filter(Episode.quality == Quality.USABLE).label("usable"),
                func.count().filter(Episode.quality == Quality.BAD).label("bad"),
            )
            .where(*episode_predicates(filters))
            .group_by(key)
            .order_by(func.count().desc(), key)
        )
        out: list[dict[str, object]] = []
        for r in (await self._s.execute(stmt)).all():
            p50, p90, p95 = (r.pcts or [None, None, None])
            out.append(
                {
                    "key": None if r.key is None else str(getattr(r.key, "value", r.key)),
                    "episodes": int(r.episodes),
                    "total_duration_seconds": int(r.total_duration_seconds),
                    "avg_duration_seconds": _r(r.avg_duration_seconds),
                    "min_duration_seconds": int(r.min_duration_seconds),
                    "max_duration_seconds": int(r.max_duration_seconds),
                    "p50_duration_seconds": _r(p50),
                    "p90_duration_seconds": _r(p90),
                    "p95_duration_seconds": _r(p95),
                    "quality": {"good": int(r.good), "usable": int(r.usable), "bad": int(r.bad)},
                }
            )
        return out

    async def episode_timeseries(
        self, bucket: Bucket, filters: EpisodeFilters, per_robot: bool = False
    ) -> list[dict[str, object]]:
        unit = _BUCKET_LITERALS[bucket]
        bucket_expr = func.date_trunc(literal_column(unit), func.timezone("UTC", Episode.recorded_at))
        dimensions = [bucket_expr.label("bucket")]
        group_by = [bucket_expr]
        if per_robot:
            dimensions.append(Episode.robot_id.label("robot_id"))
            group_by.append(Episode.robot_id)
        stmt = (
            select(
                *dimensions,
                func.count().label("episodes"),
                func.sum(Episode.duration_seconds).label("total_duration_seconds"),
            )
            .where(*episode_predicates(filters))
            .group_by(*group_by)
            .order_by(*group_by)
        )
        return [
            {
                "bucket": r.bucket.date().isoformat(),
                **({"robot_id": r.robot_id} if per_robot else {}),
                "episodes": int(r.episodes),
                "total_duration_seconds": int(r.total_duration_seconds),
            }
            for r in (await self._s.execute(stmt)).all()
        ]

    async def request_funnel(self, submitted_from=None, submitted_to=None) -> dict[str, object]:
        submitted_at = (
            select(func.min(RequestStatusHistory.changed_at))
            .where(
                RequestStatusHistory.request_id == Request.id,
                RequestStatusHistory.to_status == RequestStatus.SUBMITTED,
            )
            .correlate(Request)
            .scalar_subquery()
        )
        request_filters = []
        if submitted_from is not None:
            request_filters.append(submitted_at >= submitted_from)
        if submitted_to is not None:
            request_filters.append(submitted_at < submitted_to)
        counts = {s.value: 0 for s in RequestStatus}
        count_stmt = select(Request.status, func.count()).where(*request_filters).group_by(Request.status)
        for status, n in (await self._s.execute(count_stmt)).all():
            counts[str(getattr(status, "value", status))] = int(n)

        hours = func.extract("epoch", Request.delivered_at - submitted_at) / 3600.0
        pcts = (
            await self._s.execute(
                select(func.percentile_cont(literal_column("ARRAY[0.5, 0.9]")).within_group(hours)).where(
                    Request.delivered_at.is_not(None), *request_filters
                )
            )
        ).scalar_one_or_none()
        p50, p90 = pcts if pcts else (None, None)
        decided = counts["accepted"] + counts["rejected"]
        return {
            "by_status": counts,
            "acceptance_rate": round(counts["accepted"] / decided, 3) if decided else None,
            "turnaround_hours_p50": _r(p50, 2),
            "turnaround_hours_p90": _r(p90, 2),
        }

    async def top_good_tasks(self, limit: int = 5, recorded_from=None, recorded_to=None) -> list[dict[str, object]]:
        filters = [Episode.quality == Quality.GOOD]
        if recorded_from is not None:
            filters.append(Episode.recorded_at >= recorded_from)
        if recorded_to is not None:
            filters.append(Episode.recorded_at < recorded_to)
        stmt = (
            select(Episode.task_name, func.count().label("episodes"))
            .where(*filters)
            .group_by(Episode.task_name)
            .order_by(func.count().desc(), Episode.task_name)
            .limit(limit)
        )
        return [{"task_name": name, "episodes": int(count)} for name, count in (await self._s.execute(stmt)).all()]
