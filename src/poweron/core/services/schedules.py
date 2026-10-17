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

    async def events(
        self, subscription: Subscription, now: datetime
    ) -> list[tuple[str, NextEvent]]:
        """Every change ahead (today and tomorrow) per tracked subqueue, ordered by `earliest`."""
        events = [
            (queue, event)
            for queue in subscription.tracked_subqueues
            for event in await self.queue_events(queue, now)
        ]
        return sorted(events, key=lambda queue_event: queue_event[1].earliest)

    async def next_event(
        self, subscription: Subscription, now: datetime
    ) -> list[tuple[str, NextEvent]]:
        """Per tracked subqueue that has one: the next change between power and outage."""
        first: dict[str, NextEvent] = {}
        for queue, event in await self.events(subscription, now):
            first.setdefault(queue, event)
        return [(queue, first[queue]) for queue in subscription.tracked_subqueues if queue in first]

    async def queue_events(self, cherg_gpv: str, now: datetime) -> list[NextEvent]:
        """Switching counts as outage; unknown is skipped; power returns only after a sure OFF."""
        today = now.astimezone(KYIV).date()
        views = [await self._view(cherg_gpv, day) for day in (today, today + timedelta(days=1))]
        intervals = merge(interval for view in views if view for interval in view.intervals)
        baseline = None
        had_sure_outage = False
        events = []
        for index, interval in enumerate(intervals):
            is_outage = _is_outage(interval.state)
            if interval.start <= now < interval.end:
                baseline = is_outage
            elif interval.start > now and is_outage is not None and is_outage != baseline:
                if is_outage or had_sure_outage:
                    events.append(_event(intervals, index, now))
                baseline = is_outage
            if is_outage is not None:
                had_sure_outage = is_outage and (had_sure_outage or interval.state is SlotState.OFF)
        return events


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
