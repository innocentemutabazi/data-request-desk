"""Pydantic v2 wire models. Kept separate from ORM entities so the API contract can evolve alone."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.application.dto import ImportReport, RequestView
from app.core.config import Settings
from app.domain.enums import ExportStatus, Quality, RequestStatus, UserRole
from app.domain.models import Episode
from app.domain.state_machine import available_targets

T = TypeVar("T")


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageOut(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(None, description="Opaque keyset cursor; null on the last page.")


# ---------------------------------------------------------------- auth
class UserOut(Orm):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    organisation: str | None = None
    is_active: bool = True


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: UserRole
    organisation: str | None = Field(None, max_length=200)


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------- requests
class RequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    task_name: str = Field(min_length=1, max_length=200)
    episodes_requested: int = Field(ge=1, le=100_000)
    deadline: date = Field(default_factory=date.today)
    notes: str | None = Field(None, max_length=5000)
    min_quality: Quality | None = None
    recorded_after: datetime | None = None
    recorded_before: datetime | None = None


class ExportOut(BaseModel):
    status: ExportStatus
    attempts: int
    max_attempts: int
    error: str | None
    updated_at: datetime | None


class RequestOut(BaseModel):
    id: uuid.UUID
    title: str
    deadline: date
    notes: str | None
    task_name: str
    min_quality: Quality | None
    recorded_after: datetime | None
    recorded_before: datetime | None
    episodes_requested: int
    assigned_count: int
    status: RequestStatus
    client_id: uuid.UUID
    client_name: str
    client_organisation: str | None
    operator_id: uuid.UUID | None
    decision_reason: str | None
    export: ExportOut | None = Field(None, description="Operator-facing; omitted for clients.")
    available_transitions: list[RequestStatus]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    delivered_at: datetime | None
    decided_at: datetime | None
    status_history: list[StatusHistoryOut]


class StatusHistoryOut(BaseModel):
    from_status: RequestStatus | None
    to_status: RequestStatus
    changed_by_id: uuid.UUID
    changed_at: datetime
    reason: str | None


def to_request_out(view: RequestView, role: UserRole, settings: Settings) -> RequestOut:
    r = view.request
    export = (
        ExportOut(
            status=r.export_status,
            attempts=r.export_attempts,
            max_attempts=settings.export_max_attempts,
            error=r.export_error,
            updated_at=r.export_updated_at,
        )
        if role.is_staff
        else None
    )
    return RequestOut(
        id=r.id, title=r.title, deadline=r.deadline, notes=r.notes, task_name=r.task_name, min_quality=r.min_quality,
        recorded_after=r.recorded_after, recorded_before=r.recorded_before,
        episodes_requested=r.episodes_requested, assigned_count=view.assigned_count,
        status=r.status, client_id=r.client_id, client_name=view.client_name,
        client_organisation=view.client_organisation, operator_id=r.operator_id,
        decision_reason=r.decision_reason, export=export,
        available_transitions=available_targets(r.status, role),
        created_at=r.created_at, updated_at=r.updated_at, started_at=r.started_at,
        delivered_at=r.delivered_at, decided_at=r.decided_at,
        status_history=[StatusHistoryOut.model_validate(h, from_attributes=True) for h in view.status_history],
    )


class RejectIn(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class AssignIn(BaseModel):
    episode_ids: list[str] = Field(min_length=1, max_length=1000)


class AutoAssignIn(BaseModel):
    count: int | None = Field(None, ge=1, le=100_000, description="Defaults to everything still missing.")


class AssignmentOut(BaseModel):
    request: RequestOut
    assigned_episode_ids: list[str]
    fully_assigned: bool
    export_scheduled: bool


# ---------------------------------------------------------------- episodes
class EpisodeOut(Orm):
    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str | None
    quality: Quality
    assigned_request_id: uuid.UUID | None = None


def to_episode_out(episode: Episode, assigned_request_id: uuid.UUID | None) -> EpisodeOut:
    return EpisodeOut(
        episode_id=episode.episode_id, robot_id=episode.robot_id, task_name=episode.task_name,
        recorded_at=episode.recorded_at, duration_seconds=episode.duration_seconds,
        operator_name=episode.operator_name, quality=episode.quality, assigned_request_id=assigned_request_id,
    )


class RejectedRowOut(BaseModel):
    line: int
    reason: str
    detail: str
    raw: str


class DuplicateRowOut(BaseModel):
    line: int
    episode_id: str
    identical: bool
    note: str


class ImportReportOut(BaseModel):
    filename: str | None
    rows_read: int
    blank_lines_skipped: int
    inserted: int
    duplicates_identical: int
    duplicates_conflicting: int
    rejected: int
    rejected_by_reason: dict[str, int]
    normalizations: dict[str, int]
    warnings: dict[str, int]
    rejected_samples: list[RejectedRowOut]
    duplicate_samples: list[DuplicateRowOut]
    duration_ms: int


def to_import_report_out(r: ImportReport) -> ImportReportOut:
    return ImportReportOut(
        filename=r.filename, rows_read=r.rows_read, blank_lines_skipped=r.blank_lines_skipped,
        inserted=r.inserted, duplicates_identical=r.duplicates_identical,
        duplicates_conflicting=r.duplicates_conflicting, rejected=r.rejected,
        rejected_by_reason=r.rejected_by_reason, normalizations=r.normalizations, warnings=r.warnings,
        rejected_samples=[RejectedRowOut(**asdict(s)) for s in r.rejected_samples],
        duplicate_samples=[DuplicateRowOut(**asdict(s)) for s in r.duplicate_samples],
        duration_ms=r.duration_ms,
    )


# ---------------------------------------------------------------- analytics / catalog
class QualityMix(BaseModel):
    good: int
    usable: int
    bad: int


class RequestFunnel(BaseModel):
    by_status: dict[str, int]
    acceptance_rate: float | None
    turnaround_hours_p50: float | None
    turnaround_hours_p90: float | None


class OverviewOut(BaseModel):
    episodes_total: int
    episodes_assigned: int
    episodes_available: int
    total_duration_seconds: int
    avg_duration_seconds: float | None
    quality: QualityMix
    requests: RequestFunnel
    top_good_tasks: list[TaskCount]


class BreakdownRow(BaseModel):
    key: str | None
    episodes: int
    total_duration_seconds: int
    avg_duration_seconds: float | None
    min_duration_seconds: int
    max_duration_seconds: int
    p50_duration_seconds: float | None
    p90_duration_seconds: float | None
    p95_duration_seconds: float | None
    quality: QualityMix


class TimeseriesPoint(BaseModel):
    bucket: str
    robot_id: str | None = None
    episodes: int
    total_duration_seconds: int


class TaskCount(BaseModel):
    task_name: str
    episodes: int
