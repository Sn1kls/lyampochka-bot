from collections.abc import Sequence
from datetime import datetime

from poweron.core.domain.models import Building, City, Street, Subscription
from poweron.core.ports import Repository

REMINDER_MINUTES = (0, 15, 30, 60)


class NoScheduleForAddress(Exception):
    """Outage schedules do not apply to this building."""


class Subscriptions:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def register(self, provider: str, external_id: str, channel: str, address: str) -> int:
        return await self._repository.register_user(provider, external_id, channel, address)

    async def find_user(self, provider: str, external_id: str) -> int | None:
        return await self._repository.find_user(provider, external_id)

    async def add(
        self,
        user_id: int,
        label: str,
        city: City,
        street: Street,
        building: Building,
        subqueues: Sequence[str],
        tracked: Sequence[str],
        now: datetime,
    ) -> Subscription:
        if not subqueues:
            raise NoScheduleForAddress(building.name)
        if not tracked or not set(tracked) <= set(subqueues):
            raise ValueError("tracked must be a non-empty subset of the building's subqueues")
        return await self._repository.add_subscription(
            user_id, label, city, street, building, subqueues, tracked, now
        )

    async def remove(self, user_id: int, subscription_id: int) -> bool:
        return await self._repository.remove_subscription(user_id, subscription_id)

    async def of_user(self, user_id: int) -> list[Subscription]:
        return await self._repository.user_subscriptions(user_id)

    async def get(self, user_id: int, subscription_id: int) -> Subscription | None:
        return await self._repository.subscription(user_id, subscription_id)

    async def forget(self, user_id: int) -> None:
        await self._repository.delete_user(user_id)

    async def update_settings(
        self,
        user_id: int,
        subscription_id: int,
        *,
        notify_on_update: bool | None = None,
        remind_before_off_min: int | None = None,
        remind_before_on_min: int | None = None,
    ) -> Subscription | None:
        """Change only the given settings of the user's own subscription; None if not theirs."""
        for minutes in (remind_before_off_min, remind_before_on_min):
            if minutes is not None and minutes not in REMINDER_MINUTES:
                raise ValueError(f"reminder minutes must be one of {REMINDER_MINUTES}")
        changes = {
            "notify_on_update": notify_on_update,
            "remind_before_off_min": remind_before_off_min,
            "remind_before_on_min": remind_before_on_min,
        }
        await self._repository.update_settings(
            user_id,
            subscription_id,
            {name: value for name, value in changes.items() if value is not None},
        )
        return await self._repository.subscription(user_id, subscription_id)
