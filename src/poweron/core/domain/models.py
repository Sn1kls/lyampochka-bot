from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


class SlotState(StrEnum):
    ON = "on"
    OFF = "off"
    SWITCHING = "switching"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Interval:
    """[start, end) as aware UTC datetimes; display in KYIV."""

    start: datetime
    end: datetime
    state: SlotState


@dataclass(frozen=True)
class Address:
    city_id: int
    street_id: int
    building_name: str


@dataclass(frozen=True)
class City:
    id: int
    name: str
    otg_name: str | None


@dataclass(frozen=True)
class Street:
    id: int
    name: str


@dataclass(frozen=True)
class Building:
    id: int
    name: str
    cherg_gpv: str | None


@dataclass(frozen=True)
class DaySchedule:
    """`slots`: Kyiv wall-clock "HH:MM" -> raw value. Show `created_at` without tz conversion."""

    cherg_gpv: str
    day: date
    created_at: datetime
    slots: dict[str, str]
