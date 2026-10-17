from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from poweron.core.domain.models import KYIV, DayView, Interval, NextEvent, SlotState, Subscription

from . import texts

STATE_LINES = {
    SlotState.ON: texts.LINE_ON,
    SlotState.OFF: texts.LINE_OFF,
    SlotState.SWITCHING: texts.LINE_SWITCHING,
    SlotState.UNKNOWN: texts.LINE_UNKNOWN,
}


def subqueue_label(cherg_gpv: str) -> str:
    return cherg_gpv.split("#")[0]


def render_day(subscription: Subscription, view: DayView | None, day: date, today: date) -> str:
    title = texts.DAY_TITLE.format(label=escape(subscription.label), day=_day_name(day, today))
    if view is None:
        missing = texts.NO_SCHEDULE_TODAY if day <= today else texts.NO_SCHEDULE_TOMORROW
        return "\n\n".join([title, missing, texts.NOTE])
    header = texts.SUBQUEUE_UPDATED.format(
        subqueue=subqueue_label(subscription.cherg_gpv),
        updated=f"{view.published_at:%d.%m %H:%M}",
    )
    outage = sum(
        (
            interval.end - interval.start
            for interval in view.intervals
            if interval.state is SlotState.OFF
        ),
        timedelta(),
    )
    total = texts.TOTAL_OFF.format(duration=_duration(outage)) if outage else texts.NO_OUTAGES
    return "\n\n".join([f"{title}\n{header}", _lines(view.intervals, day), total, texts.NOTE])


def render_next(subscription: Subscription, event: NextEvent | None, now: datetime) -> str:
    label = escape(subscription.label)
    if event is None:
        return texts.NEXT_NONE.format(label=label)
    template = texts.NEXT_ON if event.power_on else texts.NEXT_OFF
    return template.format(
        label=label,
        time=f"{event.at.astimezone(KYIV):%H:%M}",
        delta=_duration(max(event.at - now, timedelta())),
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
    parts.append(texts.UPDATE_LINK)
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


def _duration(span: timedelta) -> str:
    hours, minutes = divmod(int(span.total_seconds()) // 60, 60)
    parts = []
    if hours:
        parts.append(texts.DURATION_HOURS.format(hours=hours))
    if minutes or not hours:
        parts.append(texts.DURATION_MINUTES.format(minutes=minutes))
    return " ".join(parts)
