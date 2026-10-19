"""subqueue polls

Revision ID: 3a7c1e9d5b20
Revises: 2262961650af
Create Date: 2026-10-19 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3a7c1e9d5b20"
down_revision: str | Sequence[str] | None = "2262961650af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subqueue_polls",
        sa.Column("cherg_gpv", sa.String(length=32), nullable=False),
        sa.Column("polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cherg_gpv"),
    )


def downgrade() -> None:
    op.drop_table("subqueue_polls")
