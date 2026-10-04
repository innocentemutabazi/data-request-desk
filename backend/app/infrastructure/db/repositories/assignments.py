from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import tuple_

from app.application.dto import EpisodeView, Page
from app.application.pagination import decode_cursor, encode_cursor, parse_dt
from app.domain.errors import EpisodesAlreadyAssigned
from app.domain.models import Assignment, Episode


class SqlAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def count_active(self, request_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Assignment)
            .where(Assignment.request_id == request_id, Assignment.released_at.is_(None))
        )
        return int((await self._s.execute(stmt)).scalar_one())

    async def active_episode_ids(self, episode_ids: Collection[str]) -> set[str]:
        if not episode_ids:
            return set()
        stmt = select(Assignment.episode_id).where(
            Assignment.episode_id.in_(list(episode_ids)), Assignment.released_at.is_(None)
        )
        return set((await self._s.execute(stmt)).scalars())

    async def add_many(self, request_id: uuid.UUID, episode_ids: Sequence[str], assigned_by: uuid.UUID) -> None:
        """Insert active assignments.

        The application-level checks (row locks + `active_episode_ids`) make a conflict here
        practically impossible; the partial UNIQUE index is the last line of defence, and if it ever
        fires we translate it into the same domain error rather than leaking a 500.
        """
        rows = [{"request_id": request_id, "episode_id": e, "assigned_by_id": assigned_by} for e in episode_ids]
        try:
            await self._s.execute(insert(Assignment), rows)
            await self._s.flush()
        except IntegrityError as exc:
            if "uq_assignments_active_episode" in str(exc.orig):
                raise EpisodesAlreadyAssigned(
                    "One or more episodes were assigned to another request at the same moment.",
                ) from exc
            raise

    async def release_all(self, request_id: uuid.UUID, at: datetime) -> int:
        stmt = (
            update(Assignment)
            .where(Assignment.request_id == request_id, Assignment.released_at.is_(None))
            .values(released_at=at)
            .execution_options(synchronize_session=False)
        )
        return int((await self._s.execute(stmt)).rowcount or 0)

    async def list_episodes_page(self, request_id: uuid.UUID, limit: int, cursor: str | None) -> Page[EpisodeView]:
        stmt = (
            select(Episode)
            .join(Assignment, Assignment.episode_id == Episode.episode_id)
            .where(Assignment.request_id == request_id, Assignment.released_at.is_(None))
        )
        if cursor:
            recorded_at, episode_id = decode_cursor(cursor, arity=2)
            stmt = stmt.where(tuple_(Episode.recorded_at, Episode.episode_id) < (parse_dt(recorded_at), episode_id))
        stmt = stmt.order_by(Episode.recorded_at.desc(), Episode.episode_id.desc()).limit(limit + 1)
        rows = list((await self._s.execute(stmt)).scalars())
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [EpisodeView(episode=e, assigned_request_id=request_id) for e in rows]
        next_cursor = (
            encode_cursor(rows[-1].recorded_at.isoformat(), rows[-1].episode_id) if has_more and rows else None
        )
        return Page(items, next_cursor)
