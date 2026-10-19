from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Protocol

from poweron.core.domain.models import (
    Address,
    AlertKind,
    Building,
    City,
    DaySchedule,
    DeliveryTarget,
    OutboxMessage,
    PlannedWork,
    QueuedMessage,
    ScheduleVersion,
    Street,
    Subscription,
)


class SourceError(Exception):
    """The schedule/catalog source failed; services fall back to cached data."""


class SourceUnavailable(SourceError):
    """Network error, timeout, or an error status after retries."""


class SourcePaused(SourceUnavailable):
    """The source failed repeatedly and is not being called for a while."""


class ApiSchemaError(SourceError):
    """The response no longer matches the expected format."""


class DeliveryTargetGone(Exception):
    """The channel will never accept messages for this address again (e.g. bot blocked)."""


class ScheduleSource(Protocol):
    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        """Today's and (if published) tomorrow's schedules for the address, by day."""
        ...


class CatalogSource(Protocol):
    async def cities(self) -> list[City]: ...

    async def streets(self, city_id: int) -> list[Street]: ...

    async def buildings(self, city_id: int, street_id: int) -> list[Building]: ...

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        """All subqueues a building belongs to (a building can have several power sources)."""
        ...


class PlannedWorkSource(Protocol):
    async def planned_works(
        self, city_id: int, street_id: int, after: datetime
    ) -> list[PlannedWork]:
        """Planned works on the street that end after `after`."""
        ...


class Notifier(Protocol):
    async def send(self, address: str, kind: str, payload: Mapping[str, Any]) -> None: ...


class Repository(Protocol):
    async def register_user(
        self, provider: str, external_id: str, channel: str, address: str
    ) -> tuple[int, bool]:
        """Return the user id and whether this call created the user."""
        ...

    async def find_user(self, provider: str, external_id: str) -> int | None: ...

    async def add_subscription(
        self,
        user_id: int,
        label: str,
        city: City,
        street: Street,
        building: Building,
        subqueues: Sequence[str],
        tracked: Sequence[str],
        now: datetime,
    ) -> Subscription: ...

    async def remove_subscription(self, user_id: int, subscription_id: int) -> bool: ...

    async def user_subscriptions(self, user_id: int) -> list[Subscription]: ...

    async def subscription(self, user_id: int, subscription_id: int) -> Subscription | None:
        """Only if it belongs to `user_id`."""
        ...

    async def delete_user(self, user_id: int) -> None:
        """Removes the user with identities, delivery targets, subscriptions and outbox."""
        ...

    async def all_subscriptions(self) -> list[Subscription]: ...

    async def update_settings(
        self, user_id: int, subscription_id: int, changes: Mapping[str, Any]
    ) -> None:
        """Set the given settings columns on the subscription, only if it belongs to `user_id`."""
        ...

    async def stale_subscriptions(self, checked_before: datetime) -> list[Subscription]:
        """Subscriptions whose subqueues were never checked or not since `checked_before`."""
        ...

    async def mark_checked(self, subscription_id: int, now: datetime) -> None: ...

    async def replace_subqueues(
        self,
        subscription_id: int,
        subqueues: Sequence[str],
        tracked: Sequence[str],
        now: datetime,
        messages: list[OutboxMessage],
    ) -> None:
        """Swap the stored queues, mark the subscription checked and enqueue messages atomically."""
        ...

    async def enqueue_messages(self, messages: list[OutboxMessage]) -> int:
        """Enqueue messages, skipping those whose dedupe key is already stored; returns how many were new."""
        ...

    async def last_version_at(self, cherg_gpv: str) -> datetime | None:
        """When the newest stored schedule of the subqueue was fetched."""
        ...

    async def mark_polled(self, cherg_gpv: str, at: datetime) -> None: ...

    async def polled_at(self, cherg_gpv: str) -> datetime | None:
        """When the subqueue was last polled successfully, with or without schedules."""
        ...

    async def latest_schedule_day(self, cherg_gpv: str) -> date | None: ...

    async def latest_version(self, cherg_gpv: str, day: date) -> ScheduleVersion | None: ...

    async def save_version(self, version: ScheduleVersion, messages: list[OutboxMessage]) -> None:
        """Store the version (or mark an identical one as latest) and enqueue messages atomically."""
        ...

    async def due_messages(
        self, now: datetime, limit: int, max_attempts: int
    ) -> list[QueuedMessage]: ...

    async def count_users(self) -> int: ...

    async def snapshot(self) -> bytes:
        """A consistent copy of the whole database, for backups."""
        ...

    async def user_ids_on(self, channel: str) -> list[int]:
        """Users with an active delivery target on `channel`."""
        ...

    async def count_pending_messages(self, max_attempts: int) -> int:
        """Messages not sent and not given up on."""
        ...

    async def delivery_targets(self, user_id: int) -> list[DeliveryTarget]: ...

    async def deactivate_target(self, target_id: int) -> None: ...

    async def mark_sent(self, message_id: int, now: datetime) -> None: ...

    async def mark_failed(self, message_id: int, error: str, retry_at: datetime) -> None: ...

    async def cached_catalog(self, key: str) -> tuple[Any, datetime] | None: ...

    async def store_catalog(self, key: str, value: Any, now: datetime) -> None: ...


class BackupSink(Protocol):
    async def store(self, name: str, content: bytes) -> None:
        """Keep a database backup somewhere off the server; raise if it was not kept."""
        ...


class Heartbeat(Protocol):
    async def beat(self) -> None:
        """Tell an outside monitor the worker is alive; never raises."""
        ...


class AdminAlerter(Protocol):
    async def alert(self, kind: AlertKind, details: str) -> None:
        """Tell the bot owner that something needs attention; `details` is technical, not for users."""
        ...
