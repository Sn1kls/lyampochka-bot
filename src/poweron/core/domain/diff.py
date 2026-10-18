import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from poweron.core.domain.models import Interval, SlotState
from poweron.core.domain.schedule import parse_slots


def data_hash(slots: Mapping[str, str]) -> str:
    canonical = json.dumps(slots, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def outages(intervals: list[Interval]) -> list[Interval]:
    return [interval for interval in intervals if interval.state is not SlotState.ON]


@dataclass(frozen=True)
class ScheduleChange:
    cherg_gpv: str
    day: date
    previous: list[Interval] | None
    current: list[Interval]

    @property
    def added(self) -> list[Interval]:
        return [interval for interval in self.current if interval not in (self.previous or [])]

    @property
    def removed(self) -> list[Interval]:
        return [interval for interval in self.previous or [] if interval not in self.current]

    def payload(self) -> dict[str, Any]:
        return {
            "cherg_gpv": self.cherg_gpv,
            "day": self.day.isoformat(),
            "previous": None if self.previous is None else _serialize(self.previous),
            "current": _serialize(self.current),
            "added": _serialize(self.added),
            "removed": _serialize(self.removed),
        }


def schedule_change(
    cherg_gpv: str,
    day: date,
    previous_slots: Mapping[str, str] | None,
    current_slots: Mapping[str, str],
) -> ScheduleChange | None:
    """Outage change between two versions of one day; None if outages are the same."""
    current = outages(parse_slots(current_slots, day))
    previous = None if previous_slots is None else outages(parse_slots(previous_slots, day))
    if previous == current:
        return None
    return ScheduleChange(cherg_gpv, day, previous, current)


def _serialize(intervals: list[Interval]) -> list[dict[str, str]]:
    return [
        {
            "start": interval.start.isoformat(),
            "end": interval.end.isoformat(),
            "state": interval.state,
        }
        for interval in intervals
    ]
