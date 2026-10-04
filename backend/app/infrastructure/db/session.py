from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": "dataset-request-desk",
                # Fail fast instead of queueing forever behind a stuck row lock (surfaced as HTTP 503).
                "lock_timeout": str(settings.db_lock_timeout_ms),
            }
        },
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: services return ORM objects after commit without triggering lazy IO.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
