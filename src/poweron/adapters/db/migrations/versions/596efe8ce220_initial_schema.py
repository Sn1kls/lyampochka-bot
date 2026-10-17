"""initial schema

Revision ID: 596efe8ce220
Revises:
Create Date: 2026-10-17 18:53:02.341844

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "596efe8ce220"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedule_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cherg_gpv", sa.String(length=32), nullable=False),
        sa.Column("date_graph", sa.Date(), nullable=False),
        sa.Column("date_create", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cherg_gpv", "date_graph", "data_hash"),
    )
    with op.batch_alter_table("schedule_versions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_schedule_versions_latest", ["cherg_gpv", "date_graph", "fetched_at"], unique=False
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "delivery_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "address"),
    )
    op.create_table(
        "identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_id"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.create_index("ix_outbox_pending", ["sent_at", "next_attempt_at"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("city_name", sa.String(length=128), nullable=False),
        sa.Column("street_id", sa.Integer(), nullable=False),
        sa.Column("street_name", sa.String(length=128), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=False),
        sa.Column("building_name", sa.String(length=64), nullable=False),
        sa.Column("cherg_gpv", sa.String(length=32), nullable=False),
        sa.Column("notify_on_update", sa.Boolean(), nullable=False),
        sa.Column("remind_before_off_min", sa.Integer(), nullable=False),
        sa.Column("remind_before_on_min", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cherg_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_subscriptions_cherg_gpv"), ["cherg_gpv"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_subscriptions_cherg_gpv"))

    op.drop_table("subscriptions")
    with op.batch_alter_table("outbox", schema=None) as batch_op:
        batch_op.drop_index("ix_outbox_pending")

    op.drop_table("outbox")
    op.drop_table("identities")
    op.drop_table("delivery_targets")
    op.drop_table("users")
    with op.batch_alter_table("schedule_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_schedule_versions_latest")

    op.drop_table("schedule_versions")
