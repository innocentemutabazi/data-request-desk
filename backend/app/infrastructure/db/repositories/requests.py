from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import tuple_

from app.application.dto import Page, RequestFilters, RequestView, StatusHistoryView
from app.application.pagination import decode_cursor, encode_cursor, parse_dt, parse_uuid
from app.domain.enums import ExportStatus, RequestStatus
from app.domain.models import Assignment, Request, RequestStatusHistory, User


class SqlRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ------------------------------------------------------------------ basics
    def add(self, request: Request) -> None:
        self._s.add(request)

    async def flush(self) -> None:
        await self._s.flush()

    async def get_for_update(self, request_id: uuid.UUID) -> Request | None:
        """PESSIMISTIC LOCK on the request row.

        Every state transition and every assignment starts here. Because they all queue on this one
        row, "assign an episode" and "deliver" (or two "start"s, or accept vs. reject) are
        serialised: each sees the committed result of the previous one, never a stale snapshot.
        Lock order is always  request row  →  episode rows (sorted), so there is no cycle to deadlock on.
        """
        stmt = select(Request).where(Request.id == request_id).with_for_update()
        return (await self._s.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------------ read models
    @staticmethod
    def _view_select():
        assigned = (
            select(func.count())
            .select_from(Assignment)
            .where(Assignment.request_id == Request.id, Assignment.released_at.is_(None))
            .correlate(Request)
            .scalar_subquery()
        )
        return select(Request, assigned.label("assigned_count"), User.name, User.organisation).join(
            User, User.id == Request.client_id
        )

    async def get_view(self, request_id: uuid.UUID) -> RequestView | None:
        # populate_existing: this session may already hold the row (from the preceding locked read and
        # an UPDATE); overwrite it so server-generated columns such as updated_at are loaded eagerly
        # instead of lazily (a lazy load would raise MissingGreenlet under asyncio).
        stmt = self._view_select().where(Request.id == request_id).execution_options(populate_existing=True)
        row = (await self._s.execute(stmt)).first()
        if row is None:
            return None
        history = list((await self._s.execute(
            select(RequestStatusHistory)
            .where(RequestStatusHistory.request_id == request_id)
            .order_by(RequestStatusHistory.changed_at, RequestStatusHistory.id)
        )).scalars())
        return RequestView(
            row[0], int(row[1]), row[2], row[3],
            [StatusHistoryView(h.from_status, h.to_status, h.changed_by_id, h.changed_at, h.reason) for h in history],
        )

    async def add_status_history(
        self, request_id: uuid.UUID, from_status: RequestStatus | None, to_status: RequestStatus,
        changed_by_id: uuid.UUID, reason: str | None = None,
    ) -> None:
        self._s.add(RequestStatusHistory(
            request_id=request_id, from_status=from_status, to_status=to_status,
            changed_by_id=changed_by_id, reason=reason,
        ))

    async def list_page(self, filters: RequestFilters, limit: int, cursor: str | None) -> Page[RequestView]:
        stmt = self._view_select()
        if filters.client_id:
            stmt = stmt.where(Request.client_id == filters.client_id)
        if filters.status:
            stmt = stmt.where(Request.status.in_(filters.status))
        if filters.export_status:
            stmt = stmt.where(Request.export_status.in_(filters.export_status))
        if cursor:
            created_at, rid = decode_cursor(cursor, arity=2)
            stmt = stmt.where(tuple_(Request.created_at, Request.id) < (parse_dt(created_at), parse_uuid(rid)))
        stmt = stmt.order_by(Request.created_at.desc(), Request.id.desc()).limit(limit + 1)

        rows = (await self._s.execute(stmt)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [RequestView(r[0], int(r[1]), r[2], r[3]) for r in rows]
        next_cursor = (
            encode_cursor(items[-1].request.created_at.isoformat(), str(items[-1].request.id))
            if has_more and items
            else None
        )
        return Page(items, next_cursor)

    async def status_counts(self, client_id: uuid.UUID | None) -> dict[str, int]:
        stmt = select(Request.status, func.count()).group_by(Request.status)
        if client_id:
            stmt = stmt.where(Request.client_id == client_id)
        counts = {status.value: 0 for status in RequestStatus}
        for status, n in (await self._s.execute(stmt)).all():
            counts[getattr(status, "value", status)] = int(n)
        return counts

    # ------------------------------------------------------------------ export bookkeeping
    # Each method is ONE atomic UPDATE ... WHERE <expected state> RETURNING, i.e. a compare-and-set.
    # No read-modify-write in Python, so concurrent workers cannot both "win".
    async def claim_export(self, request_id: uuid.UUID, stale_after_seconds: int) -> int | None:
        """pending -> running, or take over a 'running' export whose heartbeat has gone stale."""
        stale_cutoff = func.now() - timedelta(seconds=stale_after_seconds)
        stmt = (
            update(Request)
            .where(
                Request.id == request_id,
                or_(
                    Request.export_status == ExportStatus.PENDING,
                    and_(Request.export_status == ExportStatus.RUNNING, Request.export_updated_at < stale_cutoff),
                ),
            )
            .values(
                export_status=ExportStatus.RUNNING,
                export_attempts=0,
                export_generation=Request.export_generation + 1,
                export_error=None,
                export_updated_at=func.now(),
            )
            .returning(Request.export_generation)
            .execution_options(synchronize_session=False)
        )
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def begin_export_attempt(self, request_id: uuid.UUID, generation: int) -> int | None:
        stmt = (
            update(Request)
            .where(
                Request.id == request_id,
                Request.export_status == ExportStatus.RUNNING,
                Request.export_generation == generation,
            )
            .values(export_attempts=Request.export_attempts + 1, export_updated_at=func.now())
            .returning(Request.export_attempts)
            .execution_options(synchronize_session=False)
        )
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def heartbeat_export(self, request_id: uuid.UUID, generation: int, *, error: str | None = None) -> None:
        values: dict[str, object] = {"export_updated_at": func.now()}
        if error is not None:
            values["export_error"] = error
        stmt = (
            update(Request)
            .where(
                Request.id == request_id,
                Request.export_status == ExportStatus.RUNNING,
                Request.export_generation == generation,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        await self._s.execute(stmt)

    async def finish_export(
        self, request_id: uuid.UUID, generation: int, *, status: ExportStatus, error: str | None
    ) -> bool:
        stmt = (
            update(Request)
            .where(
                Request.id == request_id,
                Request.export_status == ExportStatus.RUNNING,
                Request.export_generation == generation,
            )
            .values(export_status=status, export_error=error, export_updated_at=func.now())
            .returning(Request.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._s.execute(stmt)).scalar_one_or_none() is not None

    async def reset_failed_export(self, request_id: uuid.UUID) -> bool:
        stmt = (
            update(Request)
            .where(Request.id == request_id, Request.export_status == ExportStatus.FAILED)
            .values(
                export_status=ExportStatus.PENDING,
                export_attempts=0,
                export_generation=Request.export_generation + 1,
                export_error=None,
                export_updated_at=func.now(),
            )
            .returning(Request.id)
            .execution_options(synchronize_session=False)
        )
        return (await self._s.execute(stmt)).scalar_one_or_none() is not None

    async def pending_export_ids(self, stale_after_seconds: int, limit: int = 50) -> list[uuid.UUID]:
        stale_cutoff = func.now() - timedelta(seconds=stale_after_seconds)
        stmt = (
            select(Request.id)
            .where(or_(
                Request.export_status == ExportStatus.PENDING,
                and_(Request.export_status == ExportStatus.RUNNING, Request.export_updated_at < stale_cutoff),
            ))
            .order_by(Request.export_updated_at, Request.id)
            .limit(limit)
        )
        return list((await self._s.execute(stmt)).scalars())
