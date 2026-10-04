"""Composition root: the ONLY place that knows which concrete implementation backs each port."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.services.analytics_service import AnalyticsService
from app.application.services.auth_service import AuthService
from app.application.services.catalog_service import CatalogService
from app.application.services.episode_service import EpisodeService
from app.application.services.export_service import ExportService
from app.application.services.import_service import ImportService
from app.application.services.request_service import RequestService
from app.application.services.user_service import UserService
from app.core.config import Settings
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.db.uow import SqlAlchemyUnitOfWork
from app.infrastructure.exports.simulator import ExportSimulator
from app.infrastructure.security.passwords import verify_password_async
from app.infrastructure.security.tokens import TokenService


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    auth: AuthService
    requests: RequestService
    episodes: EpisodeService
    exports: ExportService
    imports: ImportService
    analytics: AnalyticsService
    catalog: CatalogService
    users: UserService

    def uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory)


def build_container(
    settings: Settings,
    engine: AsyncEngine | None = None,
    simulator: ExportSimulator | None = None,
) -> Container:
    engine = engine or build_engine(settings)
    session_factory = build_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        auth=AuthService(uow_factory, TokenService(settings), verify_password_async),
        requests=RequestService(uow_factory),
        episodes=EpisodeService(uow_factory),
        exports=ExportService(uow_factory, settings, simulator or ExportSimulator(settings)),
        imports=ImportService(uow_factory, settings),
        analytics=AnalyticsService(uow_factory),
        catalog=CatalogService(uow_factory, settings.catalog_cache_ttl_seconds),
        users=UserService(uow_factory),
    )
