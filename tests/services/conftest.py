from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import Address, Building, City, DaySchedule, Street
from poweron.core.ports import SourceUnavailable
from poweron.core.services.subscriptions import Subscriptions

TODAY = date(2026, 10, 17)
TOMORROW = date(2026, 10, 18)
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)


def day_schedule(
    day: date = TODAY,
    outages: Mapping[str, str] | None = None,
    cherg_gpv: str = "4.1",
    created_at: datetime = NOW,
) -> DaySchedule:
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    return DaySchedule(cherg_gpv, day, created_at, slots | dict(outages or {}))


@dataclass
class FakeSource:
    schedules: dict[str, list[DaySchedule]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    requested: list[str] = field(default_factory=list)

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        self.requested.append(cherg_gpv)
        if cherg_gpv in self.failing:
            raise SourceUnavailable("down")
        return self.schedules.get(cherg_gpv, [])


@dataclass
class FakeNotifier:
    sent: list[tuple[str, str, Mapping[str, Any]]] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)

    async def send(self, address: str, kind: str, payload: Mapping[str, Any]) -> None:
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append((address, kind, payload))


async def subscribe(repository: SqlRepository, external_id: str = "101") -> int:
    """One subscription to subqueue 4.1, created at NOW."""
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", external_id, "telegram", external_id)
    city, street = (
        City(id=1032, name="Тернопіль", otg_name=None),
        Street(id=9985, name="вул. Садова"),
    )
    building = Building(1, "1", "4.1")
    await subscriptions.add(user_id, "Дім", city, street, building, ["4.1"], ["4.1"], NOW)
    return user_id
