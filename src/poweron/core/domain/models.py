from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
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


class MessageKind(StrEnum):
    SCHEDULE_UPDATED = "schedule_updated"


@dataclass(frozen=True)
class Subscription:
    id: int
    user_id: int
    label: str
    address: Address
    city_name: str
    street_name: str
    building_id: int
    cherg_gpv: str
    notify_on_update: bool
    remind_before_off_min: int
    remind_before_on_min: int
    created_at: datetime


@dataclass(frozen=True)
class ScheduleVersion:
    cherg_gpv: str
    day: date
    created_at: datetime
    data_hash: str
    slots: dict[str, str]
    fetched_at: datetime


@dataclass(frozen=True)
class OutboxMessage:
    user_id: int
    kind: MessageKind
    payload: dict[str, Any]
    dedupe_key: str


@dataclass(frozen=True)
class QueuedMessage:
    id: int
    attempts: int
    message: OutboxMessage


@dataclass(frozen=True)
class DeliveryTarget:
    id: int
    channel: str
    address: str
