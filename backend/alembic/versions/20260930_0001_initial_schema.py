"""initial schema: users, episodes, requests, assignments

Revision ID: 0001
Revises:
Create Date: 2026-09-30

Hand-authored (then verified against the models by tests/test_migrations.py) so that every
constraint and index - especially the partial ones - is explicit and reviewable.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    # ---------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("organisation", sa.String(length=200), nullable=True),
        sa.Column("role", sa.Enum("admin", "operator", "client", name="user_role", native_enum=False, length=20, create_constraint=False), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.CheckConstraint("role IN ('admin', 'operator', 'client')", name=op.f("ck_users_role_valid")),
    )

    # ------------------------------------------------------------- episodes
    op.create_table(
        "episodes",
        sa.Column("episode_id", sa.String(length=64), nullable=False),
        sa.Column("robot_id", sa.String(length=64), nullable=False),
        sa.Column("task_name", sa.String(length=200), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("operator_name", sa.String(length=100), nullable=True),
        sa.Column("quality", sa.Enum("good", "usable", "bad", name="episode_quality", native_enum=False, length=20, create_constraint=False), nullable=False),
        sa.PrimaryKeyConstraint("episode_id", name=op.f("pk_episodes")),
        sa.CheckConstraint("quality IN ('good', 'usable', 'bad')", name=op.f("ck_episodes_quality_valid")),
        sa.CheckConstraint("duration_seconds > 0", name=op.f("ck_episodes_duration_positive")),
    )
    op.create_index("ix_episodes_task_quality_recorded_at", "episodes", ["task_name", "quality", "recorded_at", "episode_id"])
    op.create_index("ix_episodes_task_recorded_at", "episodes", ["task_name", "recorded_at", "episode_id"])
    op.create_index("ix_episodes_recorded_at_episode_id", "episodes", ["recorded_at", "episode_id"])
    op.create_index("ix_episodes_task_duration_quality", "episodes", ["task_name", "duration_seconds", "quality"])

    # ------------------------------------------------------------- requests
    op.create_table(
        "requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("task_name", sa.String(length=200), nullable=False),
        sa.Column("min_quality", sa.Enum("good", "usable", "bad", name="request_min_quality", native_enum=False, length=20, create_constraint=False), nullable=True),
        sa.Column("recorded_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("episodes_requested", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("submitted", "in_progress", "delivered", "accepted", "rejected", name="request_status", native_enum=False, length=20, create_constraint=False), server_default="submitted", nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("export_status", sa.Enum("not_started", "pending", "running", "succeeded", "failed", name="export_status", native_enum=False, length=20, create_constraint=False), server_default="not_started", nullable=False),
        sa.Column("export_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("export_error", sa.Text(), nullable=True),
        sa.Column("export_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], name=op.f("fk_requests_client_id_users")),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], name=op.f("fk_requests_operator_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
        sa.CheckConstraint("status IN ('submitted', 'in_progress', 'delivered', 'accepted', 'rejected')", name=op.f("ck_requests_status_valid")),
        sa.CheckConstraint("export_status IN ('not_started', 'pending', 'running', 'succeeded', 'failed')", name=op.f("ck_requests_export_status_valid")),
        sa.CheckConstraint("min_quality IS NULL OR min_quality IN ('good', 'usable', 'bad')", name=op.f("ck_requests_min_quality_valid")),
        sa.CheckConstraint("episodes_requested > 0", name=op.f("ck_requests_episodes_requested_positive")),
        sa.CheckConstraint("export_attempts >= 0", name=op.f("ck_requests_export_attempts_nonneg")),
        sa.CheckConstraint("recorded_after IS NULL OR recorded_before IS NULL OR recorded_after < recorded_before", name=op.f("ck_requests_date_window_valid")),
    )
    op.create_index("ix_requests_created_at_id", "requests", ["created_at", "id"])
    op.create_index("ix_requests_client_id_created_at_id", "requests", ["client_id", "created_at", "id"])
    op.create_index("ix_requests_status_created_at_id", "requests", ["status", "created_at", "id"])
    op.create_index(
        "ix_requests_export_in_flight",
        "requests",
        ["export_status"],
        postgresql_where=sa.text("export_status IN ('pending', 'running')"),
    )

    # ---------------------------------------------------- request status history
    op.create_table(
        "request_status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.Enum("submitted", "in_progress", "delivered", "accepted", "rejected", name="history_from_status", native_enum=False, length=20, create_constraint=False), nullable=True),
        sa.Column("to_status", sa.Enum("submitted", "in_progress", "delivered", "accepted", "rejected", name="history_to_status", native_enum=False, length=20, create_constraint=False), nullable=False),
        sa.Column("changed_by_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name=op.f("fk_request_status_history_request_id_requests")),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], name=op.f("fk_request_status_history_changed_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_status_history")),
    )
    op.create_index("ix_request_status_history_request_changed", "request_status_history", ["request_id", "changed_at"])

    # ---------------------------------------------------------- assignments
    op.create_table(
        "assignments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.String(length=64), nullable=False),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name=op.f("fk_assignments_request_id_requests")),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.episode_id"], name=op.f("fk_assignments_episode_id_episodes")),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], name=op.f("fk_assignments_assigned_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignments")),
        sa.CheckConstraint("released_at IS NULL OR released_at >= assigned_at", name=op.f("ck_assignments_release_after_assign")),
    )
    # One ACTIVE claim per episode, enforced by PostgreSQL itself.
    op.create_index(
        "uq_assignments_active_episode",
        "assignments",
        ["episode_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_index("ix_assignments_request_id_episode_id", "assignments", ["request_id", "episode_id"])


def downgrade() -> None:
    op.drop_table("assignments")
    op.drop_table("request_status_history")
    op.drop_table("requests")
    op.drop_table("episodes")
    op.drop_table("users")
