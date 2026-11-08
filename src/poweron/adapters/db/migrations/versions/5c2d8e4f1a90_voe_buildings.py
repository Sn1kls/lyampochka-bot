"""voe buildings

Revision ID: 5c2d8e4f1a90
Revises: 3a7c1e9d5b20
Create Date: 2026-11-08 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c2d8e4f1a90"
down_revision: str | Sequence[str] | None = "3a7c1e9d5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voe_buildings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("settlement_id", sa.Integer(), nullable=False),
        sa.Column("district", sa.String(length=64), nullable=False),
        sa.Column("settlement", sa.String(length=128), nullable=False),
        sa.Column("street_id", sa.Integer(), nullable=False),
        sa.Column("street", sa.String(length=128), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=False),
        sa.Column("building", sa.String(length=64), nullable=False),
        sa.Column("cherg_gpv", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voe_buildings_street", "voe_buildings", ["settlement_id", "street_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_voe_buildings_street", table_name="voe_buildings")
    op.drop_table("voe_buildings")
