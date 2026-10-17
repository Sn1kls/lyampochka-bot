from datetime import date, datetime, timedelta

from poweron.core.domain.models import KYIV, DayView, Interval, NextEvent, SlotState, Subscription
from poweron.core.domain.schedule import merge, parse_slots
from poweron.core.ports import Repository


class Schedules:
    """Callers pass a subscription they have already checked belongs to the user."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def day(
        self, subscription: Subscription, day: date, subqueue: str | None = None
    ) -> list[DayView]:
        """Tracked subqueues that have data, or just `subqueue` if it is one of the building's."""
        queues = (
            subscription.tracked_subqueues
            if subqueue is None
            else tuple(queue for queue in subscription.subqueues if queue == subqueue)
        )
        views = [await self._view(queue, day) for queue in queues]
        return [view for view in views if view is not None]

    async def _view(self, cherg_gpv: str, day: date) -> DayView | None:
        version = await self._repository.latest_version(cherg_gpv, day)
        if version is None:
            return None
        return DayView(
            cherg_gpv=cherg_gpv,
            day=day,
            intervals=parse_slots(version.slots, day),
            published_at=version.created_at,
            checked_at=version.fetched_at,
        )

    async def next_event(
        self, subscription: Subscription, now: datetime
    ) -> list[tuple[str, NextEvent]]:
        """Per tracked subqueue that has one: the next change between power and outage."""
        events = [
            (queue, await self._next_event(queue, now)) for queue in subscription.tracked_subqueues
        ]
        return [(queue, event) for queue, event in events if event is not None]

    async def _next_event(self, cherg_gpv: str, now: datetime) -> NextEvent | None:
        """Switching counts as outage; unknown is skipped."""
        today = now.astimezone(KYIV).date()
        views = [await self._view(cherg_gpv, day) for day in (today, today + timedelta(days=1))]
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
