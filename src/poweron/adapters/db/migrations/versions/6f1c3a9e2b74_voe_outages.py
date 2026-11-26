"""voe outages

Revision ID: 6f1c3a9e2b74
Revises: 4d8a2f6c1e57
Create Date: 2026-11-26 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6f1c3a9e2b74"
down_revision: str | Sequence[str] | None = "4d8a2f6c1e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voe_outages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("settlement_id", sa.Integer(), nullable=False),
        sa.Column("street_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("building_names", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voe_outages_street", "voe_outages", ["settlement_id", "street_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_voe_outages_street", table_name="voe_outages")
    op.drop_table("voe_outages")
