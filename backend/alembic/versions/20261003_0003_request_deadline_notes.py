"""Add delivery deadline and operator notes to requests."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("deadline", sa.Date(), nullable=True))
    op.add_column("requests", sa.Column("notes", sa.Text(), nullable=True))
    op.execute("UPDATE requests SET deadline = CURRENT_DATE WHERE deadline IS NULL")
    op.alter_column("requests", "deadline", nullable=False)


def downgrade() -> None:
    op.drop_column("requests", "notes")
    op.drop_column("requests", "deadline")
