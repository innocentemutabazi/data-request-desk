"""Unit of Work: one database transaction + the repositories that share it.

    async with uow_factory() as uow:
        req = await uow.requests.get_for_update(...)   # row lock held until commit/rollback
        ...
        await uow.commit()

Leaving the block without committing rolls back (and therefore releases every row lock).
"""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ResourceBusy
from app.infrastructure.db.repositories.analytics import SqlAnalyticsRepository
from app.infrastructure.db.repositories.assignments import SqlAssignmentRepository
from app.infrastructure.db.repositories.episodes import SqlEpisodeRepository
from app.infrastructure.db.repositories.requests import SqlRequestRepository
from app.infrastructure.db.repositories.users import SqlUserRepository

# 55P03 lock_not_available (our lock_timeout fired) · 40P01 deadlock_detected · 40001 serialization_failure
_RETRYABLE_SQLSTATES = {"55P03", "40P01", "40001"}


def sqlstate_of(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self.session = self._session_factory()
        self.users = SqlUserRepository(self.session)
        self.episodes = SqlEpisodeRepository(self.session)
        self.assignments = SqlAssignmentRepository(self.session)
        self.requests = SqlRequestRepository(self.session)
        self.analytics = SqlAnalyticsRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                await self.session.rollback()
        finally:
            await self.session.close()
        if isinstance(exc, DBAPIError) and sqlstate_of(exc) in _RETRYABLE_SQLSTATES:
            raise ResourceBusy(
                "The resource is being modified by someone else right now. Please retry.",
                sqlstate=sqlstate_of(exc),
            ) from exc

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
