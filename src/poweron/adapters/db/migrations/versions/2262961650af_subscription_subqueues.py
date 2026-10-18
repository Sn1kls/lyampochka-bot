"""subscription subqueues

Revision ID: 2262961650af
Revises: 80be0edcac6d
Create Date: 2026-10-17 20:25:57.484923

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2262961650af"
down_revision: str | Sequence[str] | None = "80be0edcac6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

subscriptions = sa.table("subscriptions", sa.column("id"), sa.column("cherg_gpv"))
subscription_subqueues = sa.table(
    "subscription_subqueues",
    sa.column("subscription_id"),
    sa.column("cherg_gpv"),
    sa.column("notify"),
)


def upgrade() -> None:
    op.create_table(
        "subscription_subqueues",
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("cherg_gpv", sa.String(length=32), nullable=False),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("subscription_id", "cherg_gpv"),
    )
    op.execute(
        sa.insert(subscription_subqueues).from_select(
            ["subscription_id", "cherg_gpv", "notify"],
            sa.select(subscriptions.c.id, subscriptions.c.cherg_gpv, sa.true()),
        )
    )
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_subscriptions_cherg_gpv"))
        batch_op.drop_column("cherg_gpv")


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cherg_gpv", sa.VARCHAR(length=32), nullable=True))
    first_queue = (
        sa.select(sa.func.min(subscription_subqueues.c.cherg_gpv))
        .where(subscription_subqueues.c.subscription_id == subscriptions.c.id)
        .scalar_subquery()
    )
    op.execute(sa.update(subscriptions).values(cherg_gpv=first_queue))
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.alter_column("cherg_gpv", existing_type=sa.VARCHAR(length=32), nullable=False)
        batch_op.create_index(batch_op.f("ix_subscriptions_cherg_gpv"), ["cherg_gpv"], unique=False)
    op.drop_table("subscription_subqueues")
