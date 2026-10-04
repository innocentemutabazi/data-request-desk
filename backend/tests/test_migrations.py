"""The Alembic migration and the ORM models must describe the same schema."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from app.domain.models import Base


async def test_no_drift_between_models_and_migrations(engine):
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
        )
    assert diff == [], f"models and migration disagree: {diff}"


async def test_schema_enforces_the_core_invariants(engine):
    async with engine.connect() as conn:
        idx = {r[0]: r[1] for r in await conn.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'"))}
        cks = {r[0] for r in await conn.execute(text("SELECT conname FROM pg_constraint WHERE contype='c'"))}
    active = idx["uq_assignments_active_episode"]
    assert "UNIQUE" in active and "released_at IS NULL" in active  # one ACTIVE claim per episode
    assert "(task_name, quality, recorded_at, episode_id)" in idx["ix_episodes_task_quality_recorded_at"]
    assert "(task_name, duration_seconds, quality)" in idx["ix_episodes_task_duration_quality"]
    assert {"ck_episodes_quality_valid", "ck_episodes_duration_positive", "ck_requests_status_valid",
            "ck_requests_episodes_requested_positive", "ck_users_role_valid"} <= cks
