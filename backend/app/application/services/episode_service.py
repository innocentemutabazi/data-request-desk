from __future__ import annotations

from collections.abc import Callable

from app.application.dto import Actor, EpisodeFilters, EpisodeView, Page
from app.application.pagination import clamp_limit
from app.application.ports import UnitOfWork
from app.domain.errors import PermissionDenied


class EpisodeService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    async def list(self, actor: Actor, filters: EpisodeFilters, limit: int, cursor: str | None) -> Page[EpisodeView]:
        if not actor.role.is_staff:
            raise PermissionDenied("Browsing the episode inventory is limited to operators and admins.")
        async with self._uow() as uow:
            return await uow.episodes.list_page(filters, clamp_limit(limit), cursor)
