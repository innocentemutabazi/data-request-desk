"""Ports: what the application layer needs from persistence.

Services depend on these Protocols only. `infrastructure/db` provides the SQLAlchemy/PostgreSQL
implementations; tests can provide fakes. This is the dependency-inversion seam of the codebase.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from datetime import datetime
from typing import Protocol, Self

from app.application.dto import (
    Bucket,
    EpisodeFilters,
    EpisodeView,
    GroupBy,
    Page,
    RequestFilters,
    RequestView,
    TokenClaims,
)
from app.domain.criteria import EpisodeCriteria
from app.domain.enums import ExportStatus, RequestStatus
from app.domain.models import Episode, Request, User


class UserRepository(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...
    async def insert_ignore(self, rows: Sequence[Mapping[str, object]]) -> int: ...
    async def list_page(self, limit: int = 200) -> list[User]: ...
    async def add(self, user: User) -> None: ...


class EpisodeRepository(Protocol):
    async def insert_ignore(self, rows: Sequence[Mapping[str, object]]) -> set[str]:
        """INSERT ... ON CONFLICT DO NOTHING. Returns the ids that were actually inserted."""

    async def get_many(self, episode_ids: Collection[str]) -> list[Episode]: ...

    async def lock_many(self, episode_ids: Collection[str]) -> list[Episode]:
        """SELECT ... FOR UPDATE in a deterministic (sorted) order to rule out lock-order deadlocks."""

    async def lock_available_matching(
        self, criteria: EpisodeCriteria, limit: int, exclude: Collection[str]
    ) -> list[Episode]:
        """Unassigned, matching episodes locked with FOR UPDATE SKIP LOCKED."""

    async def list_page(self, filters: EpisodeFilters, limit: int, cursor: str | None) -> Page[EpisodeView]: ...

    async def task_exists(self, task_name: str) -> bool: ...

    async def task_counts(self) -> list[tuple[str, int]]: ...


class AssignmentRepository(Protocol):
    async def count_active(self, request_id: uuid.UUID) -> int: ...
    async def active_episode_ids(self, episode_ids: Collection[str]) -> set[str]: ...
    async def add_many(self, request_id: uuid.UUID, episode_ids: Sequence[str], assigned_by: uuid.UUID) -> None: ...
    async def release_all(self, request_id: uuid.UUID, at: datetime) -> int: ...
    async def list_episodes_page(self, request_id: uuid.UUID, limit: int, cursor: str | None) -> Page[EpisodeView]: ...


class RequestRepository(Protocol):
    def add(self, request: Request) -> None: ...
    async def flush(self) -> None: ...
    async def get_for_update(self, request_id: uuid.UUID) -> Request | None:
        """SELECT ... FOR UPDATE on the request row. The linchpin of every state change."""

    async def get_view(self, request_id: uuid.UUID) -> RequestView | None: ...
    async def add_status_history(
        self, request_id: uuid.UUID, from_status: RequestStatus | None, to_status: RequestStatus,
        changed_by_id: uuid.UUID, reason: str | None = None,
    ) -> None: ...
    async def list_page(self, filters: RequestFilters, limit: int, cursor: str | None) -> Page[RequestView]: ...
    async def status_counts(self, client_id: uuid.UUID | None) -> dict[str, int]: ...

    # --- export bookkeeping (atomic compare-and-set; safe under concurrency) ---
    async def claim_export(self, request_id: uuid.UUID, stale_after_seconds: int) -> int | None: ...
    async def begin_export_attempt(self, request_id: uuid.UUID, generation: int) -> int | None: ...
    async def heartbeat_export(self, request_id: uuid.UUID, generation: int, *, error: str | None = None) -> None: ...
    async def finish_export(
        self, request_id: uuid.UUID, generation: int, *, status: ExportStatus, error: str | None
    ) -> bool: ...
    async def reset_failed_export(self, request_id: uuid.UUID) -> bool: ...
    async def pending_export_ids(self, stale_after_seconds: int, limit: int = 50) -> list[uuid.UUID]: ...


class AnalyticsRepository(Protocol):
    async def overview(self, recorded_from: datetime | None = None, recorded_to: datetime | None = None) -> dict[str, object]: ...
    async def episode_breakdown(
        self, group_by: GroupBy, filters: EpisodeFilters
    ) -> list[dict[str, object]]: ...
    async def episode_timeseries(
        self, bucket: Bucket, filters: EpisodeFilters, per_robot: bool = False
    ) -> list[dict[str, object]]: ...
    async def request_funnel(self, submitted_from: datetime | None = None, submitted_to: datetime | None = None) -> dict[str, object]: ...
    async def top_good_tasks(
        self, limit: int = 5, recorded_from: datetime | None = None, recorded_to: datetime | None = None
    ) -> list[dict[str, object]]: ...


class TokenPort(Protocol):
    @property
    def expires_in_seconds(self) -> int: ...
    def issue(self, user: User) -> str: ...
    def decode(self, token: str) -> TokenClaims: ...


# (plain_password, stored_hash_or_None) -> is_valid. Must take constant time even when hash is None.
PasswordVerifier = Callable[[str, str | None], Awaitable[bool]]


class UnitOfWork(Protocol):
    users: UserRepository
    episodes: EpisodeRepository
    assignments: AssignmentRepository
    requests: RequestRepository
    analytics: AnalyticsRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


__all__ = [
    "AnalyticsRepository",
    "AssignmentRepository",
    "EpisodeRepository",
    "PasswordVerifier",
    "RequestRepository",
    "RequestStatus",
    "TokenPort",
    "UnitOfWork",
    "UserRepository",
]
