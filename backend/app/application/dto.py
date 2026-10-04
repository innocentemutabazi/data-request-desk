"""Plain data carriers shared by services, ports and the API layer."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from app.domain.enums import ExportStatus, Quality, RequestStatus, UserRole
from app.domain.models import Episode, Request

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller, as seen by the application layer."""

    id: uuid.UUID
    role: UserRole


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: list[T]
    next_cursor: str | None


@dataclass(slots=True)
class RequestView:
    request: Request
    assigned_count: int
    client_name: str
    client_organisation: str | None
    status_history: list["StatusHistoryView"] = field(default_factory=list)


@dataclass(slots=True)
class StatusHistoryView:
    from_status: RequestStatus | None
    to_status: RequestStatus
    changed_by_id: uuid.UUID
    changed_at: datetime
    reason: str | None


@dataclass(slots=True)
class EpisodeView:
    episode: Episode
    assigned_request_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class NewRequest:
    title: str
    task_name: str
    episodes_requested: int
    deadline: date = field(default_factory=date.today)
    notes: str | None = None
    min_quality: Quality | None = None
    recorded_after: datetime | None = None
    recorded_before: datetime | None = None


@dataclass(frozen=True, slots=True)
class RequestFilters:
    status: list[RequestStatus] | None = None
    export_status: list[ExportStatus] | None = None
    client_id: uuid.UUID | None = None  # set by the service for client callers (row-level security)


Availability = Literal["all", "available", "assigned"]


@dataclass(frozen=True, slots=True)
class EpisodeFilters:
    task_name: str | None = None
    qualities: list[Quality] | None = None
    robot_id: str | None = None
    recorded_from: datetime | None = None
    recorded_to: datetime | None = None
    availability: Availability = "all"


@dataclass(slots=True)
class AssignmentResult:
    view: RequestView
    assigned_episode_ids: list[str]
    fully_assigned: bool
    export_scheduled: bool


# ------------------------------------------------------------------ import reporting
@dataclass(slots=True)
class RejectedRow:
    line: int
    reason: str
    detail: str
    raw: str


@dataclass(slots=True)
class DuplicateRow:
    line: int
    episode_id: str
    identical: bool
    note: str


@dataclass(slots=True)
class ImportReport:
    filename: str | None = None
    rows_read: int = 0  # data records, excluding header and fully blank lines
    blank_lines_skipped: int = 0
    inserted: int = 0
    duplicates_identical: int = 0
    duplicates_conflicting: int = 0
    rejected: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    normalizations: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, int] = field(default_factory=dict)
    rejected_samples: list[RejectedRow] = field(default_factory=list)
    duplicate_samples: list[DuplicateRow] = field(default_factory=list)
    duration_ms: int = 0

    SAMPLE_LIMIT = 50

    def reject(self, line: int, reason: str, detail: str, raw: str) -> None:
        self.rejected += 1
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
        if len(self.rejected_samples) < self.SAMPLE_LIMIT:
            self.rejected_samples.append(RejectedRow(line, reason, detail, raw[:300]))

    def duplicate(self, line: int, episode_id: str, identical: bool, note: str) -> None:
        if identical:
            self.duplicates_identical += 1
        else:
            self.duplicates_conflicting += 1
        if len(self.duplicate_samples) < self.SAMPLE_LIMIT:
            self.duplicate_samples.append(DuplicateRow(line, episode_id, identical, note))

    def bump(self, bucket: Literal["normalizations", "warnings"], key: str, n: int = 1) -> None:
        target = getattr(self, bucket)
        target[key] = target.get(key, 0) + n


GroupBy = Literal["task_name", "robot_id", "quality", "operator_name"]
Bucket = Literal["day", "week", "month"]
