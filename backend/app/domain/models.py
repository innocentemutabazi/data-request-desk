"""Persistent domain entities (SQLAlchemy 2.0 typed mappings).

Pragmatic clean-architecture note: the ORM classes double as domain entities. Anything that needs an
engine, a session or SQL *queries* lives in `infrastructure/`; this module only declares shape and
integrity rules, so the dependency arrow still points inward.

INTEGRITY IS ENFORCED IN THE DATABASE, not merely in Python:
  * one episode ⇢ at most one *active* request      → partial UNIQUE index on assignments
  * enum-like columns                                 → CHECK constraints
  * positive quantities                               → CHECK constraints
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import ExportStatus, Quality, RequestStatus, UserRole

# Deterministic constraint names => Alembic can diff/drop them reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _enum(py_enum: type, name: str, length: int = 20) -> Enum:
    """Store enums as VARCHAR (+ explicit CHECK below) rather than native PG ENUM types.

    Native enums are painful to evolve (ALTER TYPE cannot run inside a transaction on older
    versions and Alembic diffs them poorly). VARCHAR + CHECK is trivially migratable.
    """
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        length=length,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


def _in_list(column: str, enum_cls: type) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum_cls)  # type: ignore[attr-defined]
    return f"{column} IN ({values})"


_NOW = func.now()


# --------------------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in_list("role", UserRole), name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    # Stored lower-cased; uniqueness is therefore case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organisation: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_NOW)


# --------------------------------------------------------------------------------------
# Episodes  (the 5M-row table: keep it narrow and index it for the real access paths)
# --------------------------------------------------------------------------------------
class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint(_in_list("quality", Quality), name="quality_valid"),
        CheckConstraint("duration_seconds > 0", name="duration_positive"),
        # (1) Spec'd composite: equality on task, equality/IN on quality, range + order on time.
        #     `episode_id` is the keyset tie-breaker so pages never need a sort step.
        Index("ix_episodes_task_quality_recorded_at", "task_name", "quality", "recorded_at", "episode_id"),
        # (2) Same idea when quality is unconstrained or is an IN-list (min_quality filters), where
        #     (1) cannot deliver rows already ordered by time.
        Index("ix_episodes_task_recorded_at", "task_name", "recorded_at", "episode_id"),
        # (3) Global newest-first feed and time-range analytics without a task filter.
        Index("ix_episodes_recorded_at_episode_id", "recorded_at", "episode_id"),
        # (4) Covering index for the analytics breakdown (count/percentiles/quality mix per task):
        #     an Index Only Scan with zero heap fetches and the duration already ordered within each
        #     task. Benchmarked at 1M rows: 790 ms -> 150 ms, for only ~7 MB (B-tree deduplication
        #     collapses the very low-cardinality (task, duration, quality) triples).
        Index("ix_episodes_task_duration_quality", "task_name", "duration_seconds", "quality"),
    )

    episode_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    robot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_name: Mapped[str | None] = mapped_column(String(100))
    quality: Mapped[Quality] = mapped_column(_enum(Quality, "episode_quality"), nullable=False)


# --------------------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------------------
class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(_in_list("status", RequestStatus), name="status_valid"),
        CheckConstraint(_in_list("export_status", ExportStatus), name="export_status_valid"),
        CheckConstraint("min_quality IS NULL OR " + _in_list("min_quality", Quality), name="min_quality_valid"),
        CheckConstraint("episodes_requested > 0", name="episodes_requested_positive"),
        CheckConstraint("export_attempts >= 0", name="export_attempts_nonneg"),
        CheckConstraint(
            "recorded_after IS NULL OR recorded_before IS NULL OR recorded_after < recorded_before",
            name="date_window_valid",
        ),
        # Keyset-pagination paths (newest first), scoped the three ways the API lists requests.
        Index("ix_requests_created_at_id", "created_at", "id"),
        Index("ix_requests_client_id_created_at_id", "client_id", "created_at", "id"),
        Index("ix_requests_status_created_at_id", "status", "created_at", "id"),
        # Tiny partial index: lets the export watcher find in-flight work without scanning the table.
        Index(
            "ix_requests_export_in_flight",
            "export_status",
            postgresql_where=text("export_status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    deadline: Mapped[date] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    # What the client wants (selection criteria an assigned episode must satisfy).
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    min_quality: Mapped[Quality | None] = mapped_column(_enum(Quality, "request_min_quality"))
    recorded_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    episodes_requested: Mapped[int] = mapped_column(Integer, nullable=False)

    # Lifecycle.
    status: Mapped[RequestStatus] = mapped_column(
        _enum(RequestStatus, "request_status"),
        nullable=False,
        default=RequestStatus.SUBMITTED,
        server_default=RequestStatus.SUBMITTED.value,
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)

    # Background export tracking (see ExportService for the claim/heartbeat protocol).
    export_status: Mapped[ExportStatus] = mapped_column(
        _enum(ExportStatus, "export_status"),
        nullable=False,
        default=ExportStatus.NOT_STARTED,
        server_default=ExportStatus.NOT_STARTED.value,
    )
    export_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    export_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    export_error: Mapped[str | None] = mapped_column(Text)
    export_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW, onupdate=_NOW
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestStatusHistory(Base):
    """Append-only audit trail for every request status change."""

    __tablename__ = "request_status_history"
    __table_args__ = (Index("ix_request_status_history_request_changed", "request_id", "changed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id"), nullable=False)
    from_status: Mapped[RequestStatus | None] = mapped_column(_enum(RequestStatus, "history_from_status"))
    to_status: Mapped[RequestStatus] = mapped_column(_enum(RequestStatus, "history_to_status"), nullable=False)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_NOW)


# --------------------------------------------------------------------------------------
# Assignments  (episode <-> request, with history)
# --------------------------------------------------------------------------------------
class Assignment(Base):
    """An episode being held for a request.

    `released_at IS NULL` means *active*. A rejected request releases its episodes (the row is kept
    for audit, `released_at` is stamped) so the episode can be offered to someone else - hence
    "belongs to only one request AT A TIME" is a partial unique index, not a plain one.
    """

    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint("released_at IS NULL OR released_at >= assigned_at", name="release_after_assign"),
        # THE invariant. Even if every application-level lock were bypassed, PostgreSQL itself
        # refuses a second active claim on the same episode.
        Index(
            "uq_assignments_active_episode",
            "episode_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        Index("ix_assignments_request_id_episode_id", "request_id", "episode_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id"), nullable=False)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.episode_id"), nullable=False)
    assigned_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=_NOW)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
