"""remind exact

Revision ID: 4d8a2f6c1e57
Revises: 9b3e6d2a8c41
Create Date: 2026-11-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d8a2f6c1e57"
down_revision: str | Sequence[str] | None = "9b3e6d2a8c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("remind_exact", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_column("remind_exact")
