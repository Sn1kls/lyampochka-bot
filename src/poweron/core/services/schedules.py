from datetime import date, datetime

from poweron.core.domain.models import DayView, NextEvent
from poweron.core.ports import Repository


class Schedules:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def day(self, user_id: int, subscription_id: int, day: date) -> DayView | None:
        raise NotImplementedError

    async def next_event(
        self, user_id: int, subscription_id: int, now: datetime
    ) -> NextEvent | None:
        raise NotImplementedError
