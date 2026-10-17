from datetime import datetime

from poweron.core.domain.models import Building, City, Street, Subscription
from poweron.core.ports import Repository


class NoScheduleForAddress(Exception):
    """Outage schedules do not apply to this building."""


class Subscriptions:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def register(self, provider: str, external_id: str, channel: str, address: str) -> int:
        return await self._repository.register_user(provider, external_id, channel, address)

    async def add(
        self,
        user_id: int,
        label: str,
        city: City,
        street: Street,
        building: Building,
        now: datetime,
    ) -> Subscription:
        if building.cherg_gpv is None:
            raise NoScheduleForAddress(building.name)
        return await self._repository.add_subscription(user_id, label, city, street, building, now)

    async def remove(self, user_id: int, subscription_id: int) -> bool:
        return await self._repository.remove_subscription(user_id, subscription_id)

    async def list(self, user_id: int) -> list[Subscription]:
        raise NotImplementedError

    async def get(self, user_id: int, subscription_id: int) -> Subscription | None:
        raise NotImplementedError

    async def forget(self, user_id: int) -> None:
        raise NotImplementedError
