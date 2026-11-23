from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from html import escape
from typing import Any

from poweron.core.domain.models import (
    KYIV,
    DayView,
    Interval,
    NextEvent,
    SlotState,
    StatusReport,
    SubqueueStatus,
    Subscription,
)
from poweron.core.domain.providers import TOE, VOE, plain_subqueue, provider_of

from . import texts

STALE_AFTER = timedelta(minutes=30)

STATE_LINES = {
    SlotState.ON: texts.LINE_ON,
    SlotState.OFF: texts.LINE_OFF,
    SlotState.SWITCHING: texts.LINE_SWITCHING,
    SlotState.UNKNOWN: texts.LINE_UNKNOWN,
}


# Regions in display order, by provider.
REGIONS = {TOE: texts.REGION_TERNOPIL, VOE: texts.REGION_VOLYN}


def _site(provider: str) -> tuple[str, str]:
    """The oblenergo's schedule page."""
    return {TOE: texts.SITE_TERNOPIL, VOE: texts.SITE_VOLYN}[provider]


def _note(provider: str) -> str:
    return texts.NOTE.format(site=_site(provider)[1])


def _link(provider: str) -> str:
    url, site = _site(provider)
    return texts.UPDATE_LINK.format(url=url, site=site)


def queue_name(cherg_gpv: str) -> str:
    """The queue as people know it: no region prefix, no API suffix."""
    return plain_subqueue(cherg_gpv).split("#")[0]


def subqueue_label(cherg_gpv: str) -> str:
    """HTML-safe: the value comes from the API."""
    return escape(queue_name(cherg_gpv))


def render_address(city_name: str, street_name: str, building_name: str) -> str:
    return escape(f"{city_name}, {street_name}, {building_name}")


def render_queues(subqueues: Sequence[str], tracked: Sequence[str]) -> str:
    """Marks the tracked queues only when the building has queues that are not tracked."""
    labels = [subqueue_label(queue) for queue in subqueues]
    if len(labels) == 1:
        return texts.QUEUES_ONE.format(queues=labels[0])
    if set(subqueues) <= set(tracked):
        joined = texts.QUEUES_AND.join([", ".join(labels[:-1]), labels[-1]])
    else:
        joined = ", ".join(
            texts.QUEUE_TRACKED.format(queue=label) if queue in tracked else label
            for queue, label in zip(subqueues, labels, strict=True)
        )
    return texts.QUEUES_MANY.format(queues=joined)


def render_list(subscriptions: Sequence[Subscription]) -> str:
    return "\n".join([texts.LIST_HEADER, *_list_items(subscriptions)])


def _list_items(subscriptions: Sequence[Subscription]) -> list[str]:
    return [
        texts.LIST_ITEM.format(
            label=escape(item.label),
            address=render_address(item.city_name, item.street_name, item.address.building_name),
            queues=render_queues(item.subqueues, item.tracked_subqueues),
        )
        for item in subscriptions
    ]


def render_feedback_header(user_id: int, name: str, subscriptions: Sequence[Subscription]) -> str:
    return texts.FEEDBACK_HEADER.format(
        user_id=user_id,
        name=escape(name),
        addresses="\n".join(_list_items(subscriptions)) or texts.FEEDBACK_NO_ADDRESSES,
    )


def render_confirm(
    city_name: str,
    street_name: str,
    building_name: str,
    subqueues: Sequence[str],
    tracked: Sequence[str],
    label: str,
) -> str:
    queues = render_queues(subqueues, tracked)
    return texts.CONFIRM_ADDRESS.format(
        address=render_address(city_name, street_name, building_name),
        queues=queues[0].upper() + queues[1:],
        label=escape(label),
    )


def render_no_schedule_for_address(city_name: str, street_name: str, building_name: str) -> str:
    return texts.NO_SCHEDULE_FOR_ADDRESS.format(
        address=render_address(city_name, street_name, building_name)
    )


def render_day(
    subscription: Subscription,
    views: Sequence[DayView],
    day: date,
    now: datetime,
    queues: Sequence[str] | None = None,
) -> str:
    """One block per queue in `queues` (default: the tracked ones), even if it has no data yet."""
    today = now.astimezone(KYIV).date()
    title = texts.DAY_TITLE.format(label=escape(subscription.label), day=_day_name(day, today))
    missing = texts.NO_SCHEDULE_TODAY if day <= today else texts.NO_SCHEDULE_TOMORROW
    by_queue = {view.cherg_gpv: view for view in views}
    shown = list(queues or subscription.tracked_subqueues)
    if not views and len(subscription.subqueues) <= 1:
        return "\n\n".join([title, missing, _note(subscription.provider)])
    not_loaded = texts.QUEUE_NOT_LOADED if day <= today else texts.NO_SCHEDULE_TOMORROW
    blocks = [
        _queue_block(by_queue[queue], day, now)
        if queue in by_queue
        else [texts.SUBQUEUE.format(subqueue=subqueue_label(queue)), not_loaded]
        for queue in shown
    ]
    if len(blocks) == 1:
        header, *rest = blocks[0]
        return "\n\n".join([f"{title}\n{header}", *rest, _note(subscription.provider)])
    texts_per_queue = [f"{header}\n" + "\n\n".join(rest) for header, *rest in blocks]
    return "\n\n".join([title, *texts_per_queue, _note(subscription.provider)])


def _queue_block(view: DayView, day: date, now: datetime) -> list[str]:
    """Header, optional stale warning, interval lines and total of one subqueue."""
    header = texts.SUBQUEUE_UPDATED.format(
        subqueue=subqueue_label(view.cherg_gpv),
        updated=f"{view.published_at:%d.%m %H:%M}",
    )
    outage = _state_duration(view.intervals, SlotState.OFF)
    switching = _state_duration(view.intervals, SlotState.SWITCHING)
    if not outage:
        total = (
            texts.ONLY_SWITCHING.format(duration=_duration(switching))
            if switching
            else texts.NO_OUTAGES
        )
    else:
        total = texts.TOTAL_OFF.format(duration=_duration(outage))
        if switching:
            total += texts.TOTAL_WITH_SWITCHING.format(duration=_duration(outage + switching))
    block = [header]
    if now - view.checked_at > STALE_AFTER:
        checked = f"{view.checked_at.astimezone(KYIV):%d.%m %H:%M}"
        block.append(texts.STALE_DATA.format(checked=checked))
    return [*block, _lines(view.intervals, day), total]


def render_next(
    subscription: Subscription, events: Sequence[tuple[str, NextEvent]], now: datetime
) -> str:
    label = escape(subscription.label)
    if not events:
        return texts.NEXT_NONE.format(label=label)
    if len(subscription.tracked_subqueues) == 1:
        return texts.NEXT_ONE.format(label=label, event=_next_sentence(events[0][1], now))
    lines = [
        texts.NEXT_QUEUE.format(queue=subqueue_label(queue), event=_next_sentence(event, now))
        for queue, event in events
    ]
    return "\n".join([texts.NEXT_TITLE.format(label=label), *lines])


def _next_sentence(event: NextEvent, now: datetime) -> str:
    earliest = event.earliest.astimezone(KYIV)
    latest = event.latest and event.latest.astimezone(KYIV)
    if latest is None:
        template = texts.NEXT_OFF_POSSIBLE
    elif event.power_on and event.earliest <= now:
        template = texts.NEXT_ON_ANYTIME
    elif event.power_on:
        template = texts.NEXT_ON if event.earliest == event.latest else texts.NEXT_ON_WINDOW
    else:
        template = texts.NEXT_OFF if event.earliest == event.latest else texts.NEXT_OFF_WINDOW
    return template.format(
        earliest=f"{earliest:%H:%M}",
        at_latest=_at(latest, f"{latest:%H:%M}") if latest else "",
        delta=_duration(max(event.earliest - now, timedelta())),
    )


def _at(moment: datetime, time: str) -> str:
    """«о 10:00», but «об 11:00»; `time` may list several times starting with `moment`."""
    return (texts.AT_ELEVEN if moment.hour == 11 else texts.AT).format(time=time)


def render_update(payload: Mapping[str, Any], now: datetime) -> str:
    day = date.fromisoformat(payload["day"])
    current = _intervals(payload["current"])
    day_name = _day_name(day, now.astimezone(KYIV).date())
    parts = [texts.UPDATE_TITLE.format(day=day_name, target=_for(payload))]
    # Messages queued before this key existed have none.
    if stale := payload.get("stale_reminders"):
        starts = [datetime.fromisoformat(start).astimezone(KYIV) for start in stale]
        times = ", ".join(f"{start:%H:%M}" for start in starts)
        parts.append(texts.UPDATE_STALE_REMINDER.format(at_times=_at(starts[0], times)))
    # On a brand-new day everything is "added"; marking it all would mean nothing.
    added = [] if payload["previous"] is None else _intervals(payload["added"])
    lines = [
        _line(interval, day) + (texts.UPDATE_NEW_LINE if interval in added else "")
        for interval in _with_light(current, day)
    ]
    parts.append("\n".join(lines))
    provider = provider_of(payload["cherg_gpv"])
    parts += [_note(provider), _link(provider)]
    return "\n\n".join(parts)


def _for(payload: Mapping[str, Any]) -> str:
    """Which address (if the user has several) and queue (if it has several) the push is about."""
    queue = subqueue_label(payload["cherg_gpv"])
    several_queues = payload.get("queue_count", 1) > 1
    # Messages queued before address_count existed name the address, as they used to.
    if payload.get("address_count", 2) == 1:
        return texts.FOR_QUEUE.format(queue=queue) if several_queues else ""
    template = texts.FOR_ADDRESS_QUEUE if several_queues else texts.FOR_ADDRESS
    return template.format(label=escape(payload["label"]), queue=queue)


def _with_light(outages: list[Interval], day: date) -> list[Interval]:
    """The whole day: outages with the gaps between them filled as light."""
    cursor = datetime.combine(day, time(), KYIV)
    day_end = datetime.combine(day + timedelta(days=1), time(), KYIV)
    intervals = []
    for outage in outages:
        if outage.start > cursor:
            intervals.append(Interval(cursor, outage.start, SlotState.ON))
        intervals.append(outage)
        cursor = outage.end
    if cursor < day_end:
        intervals.append(Interval(cursor, day_end, SlotState.ON))
    return intervals


def render_reminder(payload: Mapping[str, Any], *, power_on: bool) -> str:
    earliest = datetime.fromisoformat(payload["earliest"]).astimezone(KYIV)
    latest = (
        None
        if payload["latest"] is None
        else datetime.fromisoformat(payload["latest"]).astimezone(KYIV)
    )
    if latest is None:
        template = texts.REMINDER_ON_POSSIBLE if power_on else texts.REMINDER_OFF_POSSIBLE
    elif latest == earliest:
        template = texts.REMINDER_ON_EXACT if power_on else texts.REMINDER_OFF_EXACT
    else:
        template = texts.REMINDER_ON_WINDOW if power_on else texts.REMINDER_OFF_WINDOW
    text = template.format(
        minutes=payload["minutes"],
        earliest=f"{earliest:%H:%M}",
        at_latest=_at(latest, f"{latest:%H:%M}") if latest else "",
    )
    return text + _for(payload)


def render_subqueues_changed(payload: Mapping[str, Any]) -> str:
    if not payload["current"]:
        return texts.SUBQUEUES_GONE.format(
            label=escape(payload["label"]), link=_link(provider_of(payload["previous"][0]))
        )
    return texts.SUBQUEUES_CHANGED.format(
        label=escape(payload["label"]),
        previous=_queue_list(payload["previous"]),
        current=_queue_list(payload["current"]),
        tracked=_queue_list(payload["tracked"]),
    )


def render_planned_work(payload: Mapping[str, Any]) -> str:
    starts_at = datetime.fromisoformat(payload["starts_at"]).astimezone(KYIV)
    ends_at = datetime.fromisoformat(payload["ends_at"]).astimezone(KYIV)
    end = f"{ends_at:%H:%M}" if ends_at.date() == starts_at.date() else f"{ends_at:%d.%m %H:%M}"
    text = texts.PLANNED_WORK.format(
        label=escape(payload["label"]),
        date=f"{starts_at:%d.%m}",
        start=f"{starts_at:%H:%M}",
        end=end,
    )
    if payload["reason"]:
        text += texts.PLANNED_WORK_REASON.format(reason=escape(payload["reason"]))
    return text


def _queue_list(subqueues: Sequence[str]) -> str:
    return ", ".join(subqueue_label(queue) for queue in subqueues)


def minutes_text(minutes: int) -> str:
    return texts.DURATION_MINUTES.format(minutes=minutes) if minutes else texts.REMINDER_NONE


def render_settings(subscription: Subscription) -> str:
    updates = texts.SETTINGS_ENABLED if subscription.notify_on_update else texts.SETTINGS_DISABLED
    lines = [
        texts.SETTINGS_TITLE.format(label=escape(subscription.label)),
        texts.SETTINGS_UPDATES.format(state=updates),
        texts.SETTINGS_REMINDER_OFF.format(when=minutes_text(subscription.remind_before_off_min)),
        texts.SETTINGS_REMINDER_ON.format(when=minutes_text(subscription.remind_before_on_min)),
    ]
    if subscription.has_switching:
        lines.append(
            texts.SETTINGS_REMIND_EXACT
            if subscription.remind_exact
            else texts.SETTINGS_REMIND_POSSIBLE
        )
    return "\n".join(lines)


def _intervals(raw_intervals: Sequence[Mapping[str, str]]) -> list[Interval]:
    return [
        Interval(
            datetime.fromisoformat(raw["start"]),
            datetime.fromisoformat(raw["end"]),
            SlotState(raw["state"]),
        )
        for raw in raw_intervals
    ]


def _lines(intervals: Sequence[Interval], day: date) -> str:
    return "\n".join(_line(interval, day) for interval in intervals)


def _line(interval: Interval, day: date) -> str:
    end = interval.end.astimezone(KYIV)
    return STATE_LINES[interval.state].format(
        start=f"{interval.start.astimezone(KYIV):%H:%M}",
        end="24:00" if end.date() > day else f"{end:%H:%M}",
    )


def _day_name(day: date, today: date) -> str:
    date_text = f"{day:%d.%m}"
    if day == today:
        return texts.DAY_TODAY.format(date=date_text)
    if day == today + timedelta(days=1):
        return texts.DAY_TOMORROW.format(date=date_text)
    return date_text


def _state_duration(intervals: Sequence[Interval], state: SlotState) -> timedelta:
    return sum((item.end - item.start for item in intervals if item.state is state), timedelta())


def _duration(span: timedelta) -> str:
    hours, minutes = divmod(int(span.total_seconds()) // 60, 60)
    parts = []
    if hours:
        parts.append(texts.DURATION_HOURS.format(hours=hours))
    if minutes or not hours:
        parts.append(texts.DURATION_MINUTES.format(minutes=minutes))
    return " ".join(parts)


def _region(subqueue: SubqueueStatus) -> str:
    return provider_of(subqueue.cherg_gpv)


def render_status(report: StatusReport, now: datetime) -> str:
    lines = [
        texts.STATUS_TITLE.format(version=escape(report.version)),
        texts.STATUS_COUNTS.format(
            users=report.users,
            subscriptions=report.subscriptions,
            pending=report.pending_messages,
        ),
    ]
    by_region = sorted(report.subqueues, key=lambda item: list(REGIONS).index(_region(item)))
    region = None
    for subqueue in by_region:  # stable: the report's order is kept within a region
        if _region(subqueue) != region:
            region = _region(subqueue)
            lines.append(texts.STATUS_REGION.format(region=REGIONS[region]))
        label = subqueue_label(subqueue.cherg_gpv)
        polled, day = subqueue.polled_at, subqueue.latest_schedule_day
        if polled is None:
            lines.append(texts.STATUS_NEVER_POLLED.format(label=label))
            continue
        stale = now - polled > report.stale_after
        template = texts.STATUS_SUBQUEUE_STALE if stale else texts.STATUS_SUBQUEUE
        schedule = (
            texts.STATUS_NO_SCHEDULE
            if day is None
            else texts.STATUS_LAST_SCHEDULE.format(day=f"{day:%d.%m}")
        )
        lines.append(
            template.format(
                label=label, polled=f"{polled.astimezone(KYIV):%d.%m %H:%M}", schedule=schedule
            )
        )
    return "\n".join(lines)
