from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
)


class UtcDateTime(TypeDecorator[datetime]):
    """Aware UTC datetimes on every backend; SQLite would otherwise return naive values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        return None if value is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def user_fk() -> Column[int]:
    return Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("created_at", UtcDateTime, nullable=False, default=utc_now),
    Column("timezone", String(64), nullable=False, default="Europe/Kyiv"),
    Column("locale", String(8), nullable=False, default="uk"),
)

identities = Table(
    "identities",
    metadata,
    Column("id", Integer, primary_key=True),
    user_fk(),
    Column("provider", String(32), nullable=False),
    Column("external_id", String(128), nullable=False),
    Column("created_at", UtcDateTime, nullable=False, default=utc_now),
    UniqueConstraint("provider", "external_id"),
)

delivery_targets = Table(
    "delivery_targets",
    metadata,
    Column("id", Integer, primary_key=True),
    user_fk(),
    Column("channel", String(32), nullable=False),
    Column("address", String(256), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", UtcDateTime, nullable=False, default=utc_now),
    UniqueConstraint("channel", "address"),
)

subscriptions = Table(
    "subscriptions",
    metadata,
    Column("id", Integer, primary_key=True),
    user_fk(),
    Column("label", String(64), nullable=False),
    Column("city_id", Integer, nullable=False),
    Column("city_name", String(128), nullable=False),
    Column("street_id", Integer, nullable=False),
    Column("street_name", String(128), nullable=False),
    Column("building_id", Integer, nullable=False),
    Column("building_name", String(64), nullable=False),
    Column("notify_on_update", Boolean, nullable=False, default=True),
    Column("remind_before_off_min", Integer, nullable=False, default=30),
    Column("remind_before_on_min", Integer, nullable=False, default=0),
    Column("created_at", UtcDateTime, nullable=False, default=utc_now),
    Column("cherg_checked_at", UtcDateTime),
)

subscription_subqueues = Table(
    "subscription_subqueues",
    metadata,
    Column(
        "subscription_id",
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("cherg_gpv", String(32), primary_key=True),
    Column("notify", Boolean, nullable=False, default=True),
)

schedule_versions = Table(
    "schedule_versions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("cherg_gpv", String(32), nullable=False),
    Column("date_graph", Date, nullable=False),
    Column("date_create", UtcDateTime, nullable=False),
    Column("data_hash", String(64), nullable=False),
    Column("slots", JSON, nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
    UniqueConstraint("cherg_gpv", "date_graph", "data_hash"),
    Index("ix_schedule_versions_latest", "cherg_gpv", "date_graph", "fetched_at"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", Integer, primary_key=True),
    user_fk(),
    Column("kind", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("dedupe_key", String(256), nullable=False, unique=True),
    Column("created_at", UtcDateTime, nullable=False, default=utc_now),
    Column("sent_at", UtcDateTime),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text),
    Column("next_attempt_at", UtcDateTime),
    Index("ix_outbox_pending", "sent_at", "next_attempt_at"),
)

subqueue_polls = Table(
    "subqueue_polls",
    metadata,
    Column("cherg_gpv", String(32), primary_key=True),
    Column("polled_at", UtcDateTime, nullable=False),
)

catalog_cache = Table(
    "catalog_cache",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", JSON, nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
)
