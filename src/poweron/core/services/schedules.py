from datetime import date, datetime, timedelta

from poweron.core.domain.models import KYIV, DayView, NextEvent, SlotState
from poweron.core.domain.schedule import merge, parse_slots
from poweron.core.ports import Repository


class Schedules:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def day(self, user_id: int, subscription_id: int, day: date) -> DayView | None:
        subscription = await self._repository.subscription(user_id, subscription_id)
        if subscription is None:
            return None
        version = await self._repository.latest_version(subscription.cherg_gpv, day)
        if version is None:
            return None
        return DayView(
            day=day,
            intervals=parse_slots(version.slots, day),
            published_at=version.created_at,
            checked_at=version.fetched_at,
        )

    async def next_event(
        self, user_id: int, subscription_id: int, now: datetime
    ) -> NextEvent | None:
        today = now.astimezone(KYIV).date()
        views = [
            await self.day(user_id, subscription_id, day)
            for day in (today, today + timedelta(days=1))
        ]
        intervals = merge(interval for view in views if view for interval in view.intervals)
        was_outage = None
        for interval in intervals:
            is_outage = interval.state is not SlotState.ON
            if interval.start > now and was_outage is not None and is_outage != was_outage:
                return NextEvent(at=interval.start, power_on=not is_outage)
            was_outage = is_outage
        return None
