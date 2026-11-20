"""feedback source message

Revision ID: 9b3e6d2a8c41
Revises: 7e4b2c9d1f36
Create Date: 2026-11-20 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b3e6d2a8c41"
down_revision: str | Sequence[str] | None = "7e4b2c9d1f36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feedback_messages", sa.Column("source_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("feedback_messages") as batch:
        batch.drop_column("source_message_id")
