from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import tuple_

from app.application.dto import EpisodeFilters, EpisodeView, Page
from app.application.pagination import decode_cursor, encode_cursor, parse_dt
from app.domain.criteria import EpisodeCriteria
from app.domain.enums import Quality
from app.domain.models import Assignment, Episode
from app.infrastructure.db.repositories.predicates import active_assignment_exists, episode_predicates

# Preference order when auto-assigning: hand out the best recordings first.
_QUALITY_PREFERENCE = (Quality.GOOD, Quality.USABLE, Quality.BAD)


class SqlEpisodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ------------------------------------------------------------------ writes
    async def insert_ignore(self, rows: Sequence[Mapping[str, object]]) -> set[str]:
        """`INSERT ... ON CONFLICT (episode_id) DO NOTHING RETURNING episode_id`.

        Idempotent by construction: re-running an import inserts nothing new, and two concurrent
        imports of the same file cannot produce duplicates or errors. RETURNING tells us exactly
        which rows were new, so the caller can classify the rest as duplicates.
        """
        if not rows:
            return set()
        # Core rather than ORM: a bulk load needs no per-row identity-map/state tracking. (Benchmarked:
        # throughput is dominated by cleaning + driver + PostgreSQL index maintenance, not this choice.)
        table = Episode.__table__
        stmt = pg_insert(table).on_conflict_do_nothing(index_elements=[table.c.episode_id]).returning(table.c.episode_id)
        result = await self._s.execute(stmt, [dict(r) for r in rows])
        return set(result.scalars().all())

    # ------------------------------------------------------------------ point reads
    async def get_many(self, episode_ids: Collection[str]) -> list[Episode]:
        if not episode_ids:
            return []
        return list((await self._s.execute(select(Episode).where(Episode.episode_id.in_(episode_ids)))).scalars())

    async def task_exists(self, task_name: str) -> bool:
        stmt = select(select(Episode.episode_id).where(Episode.task_name == task_name).limit(1).exists())
        return bool((await self._s.execute(stmt)).scalar())

    async def task_counts(self) -> list[tuple[str, int]]:
        stmt = select(Episode.task_name, func.count()).group_by(Episode.task_name).order_by(Episode.task_name)
        return [(name, int(n)) for name, n in (await self._s.execute(stmt)).all()]

    # ------------------------------------------------------------------ pessimistic locks
    async def lock_many(self, episode_ids: Collection[str]) -> list[Episode]:
        """PESSIMISTIC LOCK: `SELECT ... FOR UPDATE`, ordered by primary key.

        Every code path that locks several episodes does so in the same global order (sorted by
        episode_id). Two operators locking overlapping sets therefore queue up instead of deadlocking.
        """
        if not episode_ids:
            return []
        stmt = (
            select(Episode)
            .where(Episode.episode_id.in_(list(episode_ids)))
            .order_by(Episode.episode_id)
            .with_for_update()
        )
        return list((await self._s.execute(stmt)).scalars())

    async def lock_available_matching(
        self, criteria: EpisodeCriteria, limit: int, exclude: Collection[str]
    ) -> list[Episode]:
        """Claim up to `limit` unassigned matching episodes with `FOR UPDATE SKIP LOCKED`.

        SKIP LOCKED means concurrent operators auto-assigning from the same pool receive *disjoint*
        sets immediately instead of blocking on each other. One query per quality tier keeps every
        probe an equality scan on the (task_name, quality, recorded_at) composite index, walking it
        backwards for newest-first - no sort step over the (potentially huge) candidate set.
        """
        picked: list[Episode] = []
        skip = set(exclude)
        for quality in _QUALITY_PREFERENCE:
            if quality not in criteria.qualities:
                continue
            need = limit - len(picked)
            if need <= 0:
                break
            preds = episode_predicates(
                EpisodeFilters(
                    task_name=criteria.task_name,
                    qualities=[quality],
                    recorded_from=criteria.recorded_after,
                    recorded_to=criteria.recorded_before,
                )
            )
            stmt = select(Episode).where(*preds, ~active_assignment_exists())
            if skip:
                stmt = stmt.where(Episode.episode_id.not_in(skip))
            stmt = (
                stmt.order_by(Episode.recorded_at.desc(), Episode.episode_id.desc())
                .limit(need)
                .with_for_update(skip_locked=True)
            )
            rows = list((await self._s.execute(stmt)).scalars())
            picked.extend(rows)
            skip.update(e.episode_id for e in rows)
        return picked

    # ------------------------------------------------------------------ keyset-paginated listing
    async def list_page(self, filters: EpisodeFilters, limit: int, cursor: str | None) -> Page[EpisodeView]:
        stmt = select(Episode, Assignment.request_id).outerjoin(
            Assignment,
            (Assignment.episode_id == Episode.episode_id) & Assignment.released_at.is_(None),
        )
        stmt = stmt.where(*episode_predicates(filters))
        if filters.availability == "available":
            stmt = stmt.where(Assignment.id.is_(None))
        elif filters.availability == "assigned":
            stmt = stmt.where(Assignment.id.is_not(None))

        if cursor:
            recorded_at, episode_id = decode_cursor(cursor, arity=2)
            stmt = stmt.where(tuple_(Episode.recorded_at, Episode.episode_id) < (parse_dt(recorded_at), episode_id))

        stmt = stmt.order_by(Episode.recorded_at.desc(), Episode.episode_id.desc()).limit(limit + 1)
        rows = (await self._s.execute(stmt)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [EpisodeView(episode=e, assigned_request_id=rid) for e, rid in rows]
        next_cursor = (
            encode_cursor(items[-1].episode.recorded_at.isoformat(), items[-1].episode.episode_id)
            if has_more and items
            else None
        )
        return Page(items, next_cursor)
