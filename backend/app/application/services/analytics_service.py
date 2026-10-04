from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.application.dto import Actor, Bucket, EpisodeFilters, GroupBy
from app.application.ports import UnitOfWork
from app.domain.errors import PermissionDenied


class AnalyticsService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    @staticmethod
    def _staff(actor: Actor) -> None:
        if not actor.role.is_staff:
            raise PermissionDenied("Analytics are available to operators and admins only.")

    async def overview(
        self, actor: Actor, recorded_from: datetime | None = None, recorded_to: datetime | None = None
    ) -> dict[str, object]:
        self._staff(actor)
        async with self._uow() as uow:
            return {
                **await uow.analytics.overview(recorded_from, recorded_to),
                "requests": await uow.analytics.request_funnel(recorded_from, recorded_to),
                "top_good_tasks": await uow.analytics.top_good_tasks(5, recorded_from, recorded_to),
            }

    async def breakdown(self, actor: Actor, group_by: GroupBy, filters: EpisodeFilters) -> list[dict[str, object]]:
        self._staff(actor)
        async with self._uow() as uow:
            return await uow.analytics.episode_breakdown(group_by, filters)

    async def timeseries(
        self, actor: Actor, bucket: Bucket, filters: EpisodeFilters, per_robot: bool = False
    ) -> list[dict[str, object]]:
        self._staff(actor)
        async with self._uow() as uow:
            return await uow.analytics.episode_timeseries(bucket, filters, per_robot)
