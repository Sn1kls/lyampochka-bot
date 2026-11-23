import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta

from poweron.core.domain.models import KYIV, Interval, SlotState

logger = logging.getLogger(__name__)

SLOT_STATES: Mapping[str, SlotState] = {
    "0": SlotState.ON,
    "1": SlotState.OFF,
    "10": SlotState.SWITCHING,
}
SLOT_LENGTH = timedelta(minutes=30)


def day_slots(codes: Iterable[str]) -> dict[str, str]:
    """Raw codes of a day's half-hour slots, in order from 00:00, keyed by Kyiv start time."""
    return {f"{index // 2:02d}:{index % 2 * 30:02d}": code for index, code in enumerate(codes)}


def parse_slots(
    times: Mapping[str, str],
    day: date,
    semantics: Mapping[str, SlotState] = SLOT_STATES,
) -> list[Interval]:
    """Kyiv wall-clock slots -> merged UTC intervals; DST days are 23 or 25 h long."""
    slot_start = _kyiv_midnight(day)
    day_end = _kyiv_midnight(day + timedelta(days=1))
    intervals = []
    unknown_slots = {}
    while slot_start < day_end:
        label = f"{slot_start.astimezone(KYIV):%H:%M}"
        value = times.get(label)
        state = semantics.get(value) if value is not None else None
        if state is None:
            unknown_slots[label] = value
            state = SlotState.UNKNOWN
        intervals.append(Interval(slot_start, slot_start + SLOT_LENGTH, state))
        slot_start += SLOT_LENGTH
    if unknown_slots:
        logger.warning("unknown slot values on %s: %r", day, unknown_slots)
    return merge(intervals)


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for interval in sorted(intervals, key=lambda item: item.start):
        previous = merged[-1] if merged else None
        if previous and previous.state == interval.state and previous.end == interval.start:
            merged[-1] = Interval(previous.start, interval.end, interval.state)
        else:
            merged.append(interval)
    return merged


def sure(intervals: list[Interval]) -> list[Interval]:
    """Switching keeps the state before it: power is surely off once OFF starts, surely back once ON does.

    A gap between intervals counts as ON, so a list of outages alone works too.
    """
    result = []
    previous = SlotState.ON
    previous_end = None
    for interval in intervals:
        if previous_end is not None and interval.start != previous_end:
            previous = SlotState.ON
        state = previous if interval.state is SlotState.SWITCHING else interval.state
        result.append(Interval(interval.start, interval.end, state))
        if state is not SlotState.UNKNOWN:
            previous = state
        previous_end = interval.end
    return merge(result)


def _kyiv_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), KYIV).astimezone(UTC)
