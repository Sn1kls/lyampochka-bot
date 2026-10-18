from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
class PlannedWork:
    """Aware UTC instants; an empty `building_names` means the whole street."""

    id: int
    street_id: int
    starts_at: datetime
    ends_at: datetime
    reason: str
    building_names: tuple[str, ...]


@dataclass(frozen=True)
class DaySchedule:
    """`slots`: Kyiv wall-clock "HH:MM" -> raw value. Show `created_at` without tz conversion."""

    cherg_gpv: str
    day: date
    created_at: datetime
    slots: dict[str, str]


class MessageKind(StrEnum):
    SCHEDULE_UPDATED = "schedule_updated"
    REMINDER_OFF = "reminder_off"
    REMINDER_ON = "reminder_on"
    SUBQUEUES_CHANGED = "subqueues_changed"
    PLANNED_WORK = "planned_work"
    MENU_UPDATED = "menu_updated"


@dataclass(frozen=True)
class Subscription:
    id: int
    user_id: int
    label: str
    address: Address
    city_name: str
    street_name: str
    building_id: int
    subqueues: tuple[str, ...]  # every queue of the building, tracked ones first
    tracked_subqueues: tuple[str, ...]
    notify_on_update: bool
    remind_before_off_min: int
    remind_before_on_min: int
    created_at: datetime

    @property
    def instance_key(self) -> str:
        """Id plus creation time: SQLite may reuse the id of a deleted subscription."""
        return f"{self.id}.{int(self.created_at.timestamp())}"


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


@dataclass(frozen=True)
class DayView:
    """One subqueue's schedule for one day; `published_at` is dateCreate, shown as is."""

    cherg_gpv: str
    day: date
    intervals: list[Interval]
    published_at: datetime
    checked_at: datetime


@dataclass(frozen=True)
class NextEvent:
    """The window in which the change happens; `latest` is the guaranteed moment, None if only possible."""

    power_on: bool
    earliest: datetime
    latest: datetime | None


class AlertKind(StrEnum):
    API_SCHEMA = "api_schema"
    API_DOWN = "api_down"
    NEW_USER = "new_user"


@dataclass(frozen=True)
class SubqueueStatus:
    cherg_gpv: str
    last_polled_at: datetime | None


@dataclass(frozen=True)
class StatusReport:
    version: str
    users: int
    subscriptions: int
    pending_messages: int
    subqueues: tuple[SubqueueStatus, ...]
    stale_after: timedelta
