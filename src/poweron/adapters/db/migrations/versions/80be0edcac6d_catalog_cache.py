"""catalog cache

Revision ID: 80be0edcac6d
Revises: 596efe8ce220
Create Date: 2026-10-17 19:18:56.372517

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "80be0edcac6d"
down_revision: str | Sequence[str] | None = "596efe8ce220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_cache",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("catalog_cache")
