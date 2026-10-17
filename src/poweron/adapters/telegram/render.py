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


def render_list(subscriptions: Sequence[Subscription]) -> str:
    lines = [
        texts.LIST_ITEM.format(
            label=escape(item.label),
            address=render_address(item.city_name, item.street_name, item.address.building_name),
            subqueue=subqueue_label(item.cherg_gpv),
        )
        for item in subscriptions
    ]
    return "\n".join([texts.LIST_HEADER, *lines])


def render_confirm(
    city_name: str, street_name: str, building_name: str, cherg_gpv: str, label: str
) -> str:
    return texts.CONFIRM_ADDRESS.format(
        address=render_address(city_name, street_name, building_name),
        subqueue=subqueue_label(cherg_gpv),
        label=escape(label),
    )


def render_no_schedule_for_address(city_name: str, street_name: str, building_name: str) -> str:
    return texts.NO_SCHEDULE_FOR_ADDRESS.format(
        address=render_address(city_name, street_name, building_name)
    )


def render_day(subscription: Subscription, view: DayView | None, day: date, now: datetime) -> str:
    today = now.astimezone(KYIV).date()
    title = texts.DAY_TITLE.format(label=escape(subscription.label), day=_day_name(day, today))
    if view is None:
        missing = texts.NO_SCHEDULE_TODAY if day <= today else texts.NO_SCHEDULE_TOMORROW
        return "\n\n".join([title, missing, texts.NOTE])
    header = texts.SUBQUEUE_UPDATED.format(
        subqueue=subqueue_label(subscription.cherg_gpv),
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
    parts = [f"{title}\n{header}"]
    if now - view.checked_at > STALE_AFTER:
        checked = f"{view.checked_at.astimezone(KYIV):%d.%m %H:%M}"
        parts.append(texts.STALE_DATA.format(checked=checked))
    return "\n\n".join([*parts, _lines(view.intervals, day), total, texts.NOTE])


def render_next(subscription: Subscription, event: NextEvent | None, now: datetime) -> str:
    label = escape(subscription.label)
    if event is None:
        return texts.NEXT_NONE.format(label=label)
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
        label=label,
        earliest=f"{earliest:%H:%M}",
        latest=f"{latest:%H:%M}" if latest else "",
        delta=_duration(max(event.earliest - now, timedelta())),
    )


def render_update(payload: Mapping[str, Any]) -> str:
    day = date.fromisoformat(payload["day"])
    day_text = f"{day:%d.%m}"
    parts = [texts.UPDATE_TITLE.format(label=escape(payload["label"]))]
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
