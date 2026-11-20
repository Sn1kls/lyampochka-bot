"""feedback messages

Revision ID: 7e4b2c9d1f36
Revises: 5c2d8e4f1a90
Create Date: 2026-11-20 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7e4b2c9d1f36"
down_revision: str | Sequence[str] | None = "5c2d8e4f1a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_messages",
        sa.Column("ref", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("ref"),
    )


def downgrade() -> None:
    op.drop_table("feedback_messages")
