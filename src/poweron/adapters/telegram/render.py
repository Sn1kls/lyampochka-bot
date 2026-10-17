from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from poweron.core.domain.models import KYIV, DayView, Interval, NextEvent, SlotState, Subscription

from . import texts

STALE_AFTER = timedelta(minutes=30)

STATE_LINES = {
    SlotState.ON: texts.LINE_ON,
    SlotState.OFF: texts.LINE_OFF,
    SlotState.SWITCHING: texts.LINE_SWITCHING,
    SlotState.UNKNOWN: texts.LINE_UNKNOWN,
}


def subqueue_label(cherg_gpv: str) -> str:
    """HTML-safe: the value comes from the API."""
    return escape(cherg_gpv.split("#")[0])


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
    lines = [
        texts.LIST_ITEM.format(
            label=escape(item.label),
            address=render_address(item.city_name, item.street_name, item.address.building_name),
            queues=render_queues(item.subqueues, item.tracked_subqueues),
        )
        for item in subscriptions
    ]
    return "\n".join([texts.LIST_HEADER, *lines])


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
        return "\n\n".join([title, missing, texts.NOTE])
    not_loaded = texts.QUEUE_NOT_LOADED if day <= today else texts.NO_SCHEDULE_TOMORROW
    blocks = [
        _queue_block(by_queue[queue], day, now)
        if queue in by_queue
        else [texts.SUBQUEUE.format(subqueue=subqueue_label(queue)), not_loaded]
        for queue in shown
    ]
    if len(blocks) == 1:
        header, *rest = blocks[0]
        return "\n\n".join([f"{title}\n{header}", *rest, texts.NOTE])
    texts_per_queue = [f"{header}\n" + "\n\n".join(rest) for header, *rest in blocks]
    return "\n\n".join([title, *texts_per_queue, texts.NOTE])


def _queue_block(view: DayView, day: date, now: datetime) -> list[str]:
    """Header, optional stale warning, interval lines and total of one subqueue."""
    header = texts.SUBQUEUE_UPDATED.format(
        subqueue=subqueue_label(view.cherg_gpv),
        updated=f"{view.published_at:%d.%m %H:%M}",
    )
    outage = _state_duration(view, SlotState.OFF)
    switching = _state_duration(view, SlotState.SWITCHING)
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
        latest=f"{latest:%H:%M}" if latest else "",
        delta=_duration(max(event.earliest - now, timedelta())),
    )


def render_update(payload: Mapping[str, Any]) -> str:
    day = date.fromisoformat(payload["day"])
    day_text = f"{day:%d.%m}"
    queue = (
        texts.UPDATE_QUEUE.format(queue=subqueue_label(payload["cherg_gpv"]))
        if payload.get("queue_count", 1) > 1
        else ""
    )
    parts = [texts.UPDATE_TITLE.format(label=escape(payload["label"]), queue=queue)]
    if payload["previous"] is None:
        current = _intervals(payload["current"])
        if current:
            parts += [texts.UPDATE_NEW_DAY.format(date=day_text), _lines(current, day)]
        else:
            parts.append(texts.UPDATE_NEW_DAY_EMPTY.format(date=day_text))
    else:
        parts.append(texts.UPDATE_CHANGED_DAY.format(date=day_text))
        for heading, key in ((texts.UPDATE_ADDED, "added"), (texts.UPDATE_REMOVED, "removed")):
            intervals = _intervals(payload[key])
            if intervals:
                parts.append(f"{heading}\n{_lines(intervals, day)}")
    parts += [texts.NOTE, texts.UPDATE_LINK]
    return "\n\n".join(parts)


def render_reminder(payload: Mapping[str, Any], *, power_on: bool) -> str:
    earliest = datetime.fromisoformat(payload["earliest"]).astimezone(KYIV)
    latest = payload["latest"] and datetime.fromisoformat(payload["latest"]).astimezone(KYIV)
    if latest is None:
        template = texts.REMINDER_ON_POSSIBLE if power_on else texts.REMINDER_OFF_POSSIBLE
    elif latest == earliest:
        template = texts.REMINDER_ON_EXACT if power_on else texts.REMINDER_OFF_EXACT
    else:
        template = texts.REMINDER_ON_WINDOW if power_on else texts.REMINDER_OFF_WINDOW
    queue = (
        texts.UPDATE_QUEUE.format(queue=subqueue_label(payload["cherg_gpv"]))
        if payload["queue_count"] > 1
        else ""
    )
    return template.format(
        label=escape(payload["label"]),
        queue=queue,
        minutes=payload["minutes"],
        earliest=f"{earliest:%H:%M}",
        latest=f"{latest:%H:%M}" if latest else "",
    )


def render_subqueues_changed(payload: Mapping[str, Any]) -> str:
    return texts.SUBQUEUES_CHANGED.format(
        label=escape(payload["label"]),
        previous=_queue_list(payload["previous"]),
        current=_queue_list(payload["current"]),
        tracked=_queue_list(payload["tracked"]),
    )


def _queue_list(subqueues: Sequence[str]) -> str:
    return ", ".join(subqueue_label(queue) for queue in subqueues) or texts.NO_QUEUES


def render_settings(subscription: Subscription) -> str:
    def reminder(minutes: int) -> str:
        if minutes:
            return texts.SETTINGS_REMINDER_MINUTES.format(minutes=minutes)
        return texts.SETTINGS_REMINDER_NONE

    updates = texts.SETTINGS_ENABLED if subscription.notify_on_update else texts.SETTINGS_DISABLED
    return "\n".join(
        [
            texts.SETTINGS_TITLE.format(label=escape(subscription.label)),
            texts.SETTINGS_UPDATES.format(state=updates),
            texts.SETTINGS_REMINDER_OFF.format(when=reminder(subscription.remind_before_off_min)),
            texts.SETTINGS_REMINDER_ON.format(when=reminder(subscription.remind_before_on_min)),
        ]
    )


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


def _state_duration(view: DayView, state: SlotState) -> timedelta:
    return sum(
        (item.end - item.start for item in view.intervals if item.state is state), timedelta()
    )


def _duration(span: timedelta) -> str:
    hours, minutes = divmod(int(span.total_seconds()) // 60, 60)
    parts = []
    if hours:
        parts.append(texts.DURATION_HOURS.format(hours=hours))
    if minutes or not hours:
        parts.append(texts.DURATION_MINUTES.format(minutes=minutes))
    return " ".join(parts)
