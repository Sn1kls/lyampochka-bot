import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Row, and_, delete, event, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from poweron.adapters.db.tables import (
    catalog_cache,
    delivery_targets,
    identities,
    outbox,
    schedule_versions,
    subscriptions,
    users,
)
from poweron.core.domain.models import (
    Address,
    Building,
    City,
    DeliveryTarget,
    MessageKind,
    OutboxMessage,
    QueuedMessage,
    ScheduleVersion,
    Street,
    Subscription,
)

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).parent / "migrations"


def create_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    return config


def run_migrations(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def _enable_sqlite_foreign_keys(connection: Any, _record: Any) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class SqlRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def register_user(
        self, provider: str, external_id: str, channel: str, address: str
    ) -> int:
        async with self._engine.begin() as connection:
            user_id = await connection.scalar(
                select(identities.c.user_id).where(
                    identities.c.provider == provider, identities.c.external_id == external_id
                )
            )
            if user_id is None:
                user_id = await connection.scalar(users.insert().returning(users.c.id))
                await connection.execute(
                    identities.insert().values(
                        user_id=user_id, provider=provider, external_id=external_id
                    )
                )
            target = (
                await connection.execute(
                    select(delivery_targets.c.id, delivery_targets.c.user_id).where(
                        delivery_targets.c.channel == channel,
                        delivery_targets.c.address == address,
                    )
                )
            ).first()
            if target is None:
                await connection.execute(
                    delivery_targets.insert().values(
                        user_id=user_id, channel=channel, address=address
                    )
                )
            elif target.user_id == user_id:
                await connection.execute(
                    update(delivery_targets)
                    .where(delivery_targets.c.id == target.id)
                    .values(is_active=True)
                )
            else:
                logger.warning(
                    "delivery target on channel %s already belongs to another user; not rebinding",
                    channel,
                )
            return int(user_id)

    async def add_subscription(
        self,
        user_id: int,
        label: str,
        city: City,
        street: Street,
        building: Building,
        now: datetime,
    ) -> Subscription:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                subscriptions.insert()
                .values(
                    user_id=user_id,
                    label=label,
                    city_id=city.id,
                    city_name=city.name,
                    street_id=street.id,
                    street_name=street.name,
                    building_id=building.id,
                    building_name=building.name,
                    cherg_gpv=building.cherg_gpv,
                    created_at=now,
                )
                .returning(*subscriptions.c)
            )
            return _subscription(result.one())

    async def remove_subscription(self, user_id: int, subscription_id: int) -> bool:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                delete(subscriptions).where(
                    subscriptions.c.id == subscription_id, subscriptions.c.user_id == user_id
                )
            )
            return result.rowcount > 0

    async def user_subscriptions(self, user_id: int) -> list[Subscription]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(subscriptions)
                .where(subscriptions.c.user_id == user_id)
                .order_by(subscriptions.c.id)
            )
            return [_subscription(row) for row in result]

    async def subscription(self, user_id: int, subscription_id: int) -> Subscription | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(subscriptions).where(
                        subscriptions.c.id == subscription_id, subscriptions.c.user_id == user_id
                    )
                )
            ).first()
            return None if row is None else _subscription(row)

    async def delete_user(self, user_id: int) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(delete(users).where(users.c.id == user_id))

    async def all_subscriptions(self) -> list[Subscription]:
        async with self._engine.connect() as connection:
            result = await connection.execute(select(subscriptions).order_by(subscriptions.c.id))
            return [_subscription(row) for row in result]

    async def last_polled_at(self, cherg_gpv: str) -> datetime | None:
        async with self._engine.connect() as connection:
            polled_at: datetime | None = await connection.scalar(
                select(func.max(schedule_versions.c.fetched_at)).where(
                    schedule_versions.c.cherg_gpv == cherg_gpv
                )
            )
            return polled_at

    async def latest_version(self, cherg_gpv: str, day: date) -> ScheduleVersion | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(schedule_versions)
                    .where(
                        schedule_versions.c.cherg_gpv == cherg_gpv,
                        schedule_versions.c.date_graph == day,
                    )
                    .order_by(schedule_versions.c.fetched_at.desc())
                    .limit(1)
                )
            ).first()
            return None if row is None else _version(row)

    async def save_version(self, version: ScheduleVersion, messages: list[OutboxMessage]) -> None:
        async with self._engine.begin() as connection:
            same_version = and_(
                schedule_versions.c.cherg_gpv == version.cherg_gpv,
                schedule_versions.c.date_graph == version.day,
                schedule_versions.c.data_hash == version.data_hash,
            )
            existing = await connection.scalar(select(schedule_versions.c.id).where(same_version))
            if existing is None:
                await connection.execute(
                    schedule_versions.insert().values(
                        cherg_gpv=version.cherg_gpv,
                        date_graph=version.day,
                        date_create=version.created_at,
                        data_hash=version.data_hash,
                        slots=version.slots,
                        fetched_at=version.fetched_at,
                    )
                )
            else:
                await connection.execute(
                    update(schedule_versions)
                    .where(schedule_versions.c.id == existing)
                    .values(fetched_at=version.fetched_at, date_create=version.created_at)
                )
            for message in messages:
                await _enqueue(connection, message)

    async def due_messages(
        self, now: datetime, limit: int, max_attempts: int
    ) -> list[QueuedMessage]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(outbox)
                .where(
                    outbox.c.sent_at.is_(None),
                    outbox.c.attempts < max_attempts,
                    or_(outbox.c.next_attempt_at.is_(None), outbox.c.next_attempt_at <= now),
                )
                .order_by(outbox.c.id)
                .limit(limit)
            )
            return [_queued_message(row) for row in result]

    async def delivery_targets(self, user_id: int) -> list[DeliveryTarget]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                select(delivery_targets).where(
                    delivery_targets.c.user_id == user_id, delivery_targets.c.is_active
                )
            )
            return [DeliveryTarget(row.id, row.channel, row.address) for row in result]

    async def deactivate_target(self, target_id: int) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(delivery_targets)
                .where(delivery_targets.c.id == target_id)
                .values(is_active=False)
            )

    async def mark_sent(self, message_id: int, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(outbox).where(outbox.c.id == message_id).values(sent_at=now)
            )

    async def mark_failed(self, message_id: int, error: str, retry_at: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(outbox)
                .where(outbox.c.id == message_id)
                .values(
                    attempts=outbox.c.attempts + 1,
                    last_error=error[:1000],
                    next_attempt_at=retry_at,
                )
            )

    async def cached_catalog(self, key: str) -> tuple[Any, datetime] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(select(catalog_cache).where(catalog_cache.c.key == key))
            ).first()
            return None if row is None else (row.value, row.fetched_at)

    async def store_catalog(self, key: str, value: Any, now: datetime) -> None:
        async with self._engine.begin() as connection:
            exists = await connection.scalar(select(func.count()).where(catalog_cache.c.key == key))
            if exists:
                await connection.execute(
                    update(catalog_cache)
                    .where(catalog_cache.c.key == key)
                    .values(value=value, fetched_at=now)
                )
            else:
                await connection.execute(
                    catalog_cache.insert().values(key=key, value=value, fetched_at=now)
                )


async def _enqueue(connection: AsyncConnection, message: OutboxMessage) -> None:
    duplicate = await connection.scalar(
        select(func.count()).where(outbox.c.dedupe_key == message.dedupe_key)
    )
    if not duplicate:
        await connection.execute(
            outbox.insert().values(
                user_id=message.user_id,
                kind=message.kind,
                payload=message.payload,
                dedupe_key=message.dedupe_key,
            )
        )


def _subscription(row: Row[Any]) -> Subscription:
    return Subscription(
        id=row.id,
        user_id=row.user_id,
        label=row.label,
        address=Address(row.city_id, row.street_id, row.building_name),
        city_name=row.city_name,
        street_name=row.street_name,
        building_id=row.building_id,
        cherg_gpv=row.cherg_gpv,
        notify_on_update=row.notify_on_update,
        remind_before_off_min=row.remind_before_off_min,
        remind_before_on_min=row.remind_before_on_min,
        created_at=row.created_at,
    )


def _version(row: Row[Any]) -> ScheduleVersion:
    return ScheduleVersion(
        cherg_gpv=row.cherg_gpv,
        day=row.date_graph,
        created_at=row.date_create,
        data_hash=row.data_hash,
        slots=row.slots,
        fetched_at=row.fetched_at,
    )


def _queued_message(row: Row[Any]) -> QueuedMessage:
    message = OutboxMessage(
        user_id=row.user_id,
        kind=MessageKind(row.kind),
        payload=row.payload,
        dedupe_key=row.dedupe_key,
    )
    return QueuedMessage(id=row.id, attempts=row.attempts, message=message)
