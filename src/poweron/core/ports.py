from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Protocol

from poweron.core.domain.models import (
    Address,
    Building,
    City,
    DaySchedule,
    DeliveryTarget,
    OutboxMessage,
    QueuedMessage,
    ScheduleVersion,
    Street,
    Subscription,
)


class SourceError(Exception):
    """The schedule/catalog source failed; services fall back to cached data."""


class SourceUnavailable(SourceError):
    """Network error, timeout, or an error status after retries."""


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


class Notifier(Protocol):
    async def send(self, address: str, kind: str, payload: Mapping[str, Any]) -> None: ...


class Repository(Protocol):
    async def register_user(
        self, provider: str, external_id: str, channel: str, address: str
    ) -> int: ...

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

    async def last_polled_at(self, cherg_gpv: str) -> datetime | None: ...

    async def latest_version(self, cherg_gpv: str, day: date) -> ScheduleVersion | None: ...

    async def save_version(self, version: ScheduleVersion, messages: list[OutboxMessage]) -> None:
        """Store the version (or mark an identical one as latest) and enqueue messages atomically."""
        ...

    async def due_messages(
        self, now: datetime, limit: int, max_attempts: int
    ) -> list[QueuedMessage]: ...

    async def delivery_targets(self, user_id: int) -> list[DeliveryTarget]: ...

    async def deactivate_target(self, target_id: int) -> None: ...

    async def mark_sent(self, message_id: int, now: datetime) -> None: ...

    async def mark_failed(self, message_id: int, error: str, retry_at: datetime) -> None: ...

    async def cached_catalog(self, key: str) -> tuple[Any, datetime] | None: ...

    async def store_catalog(self, key: str, value: Any, now: datetime) -> None: ...
