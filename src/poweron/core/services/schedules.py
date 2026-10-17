from datetime import date, datetime, timedelta

from poweron.core.domain.models import KYIV, DayView, Interval, NextEvent, SlotState, Subscription
from poweron.core.domain.schedule import merge, parse_slots
from poweron.core.ports import Repository


class Schedules:
    """Callers pass a subscription they have already checked belongs to the user."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def day(self, subscription: Subscription, day: date) -> DayView | None:
        version = await self._repository.latest_version(subscription.cherg_gpv, day)
        if version is None:
            return None
        return DayView(
            day=day,
            intervals=parse_slots(version.slots, day),
            published_at=version.created_at,
            checked_at=version.fetched_at,
        )

    async def next_event(self, subscription: Subscription, now: datetime) -> NextEvent | None:
        """Next change between power and outage (switching counts as outage); unknown is skipped."""
        today = now.astimezone(KYIV).date()
        views = [await self.day(subscription, day) for day in (today, today + timedelta(days=1))]
        intervals = merge(interval for view in views if view for interval in view.intervals)
        baseline = None
        for index, interval in enumerate(intervals):
            is_outage = _is_outage(interval.state)
            if interval.start <= now < interval.end:
                baseline = is_outage
            elif interval.start > now and is_outage is not None and is_outage != baseline:
                return _event(intervals, index, now)
        return None


def _event(intervals: list[Interval], index: int, now: datetime) -> NextEvent:
    if intervals[index].state is SlotState.ON:
        first = index
        while first > 0 and intervals[first - 1].state is SlotState.SWITCHING:
            first -= 1
        return NextEvent(True, max(intervals[first].start, now), intervals[index].start)
    after = index
    while after < len(intervals) and intervals[after].state is SlotState.SWITCHING:
        after += 1
    guaranteed = after < len(intervals) and intervals[after].state is SlotState.OFF
    return NextEvent(False, intervals[index].start, intervals[after].start if guaranteed else None)


def _is_outage(state: SlotState) -> bool | None:
    return None if state is SlotState.UNKNOWN else state is not SlotState.ON
