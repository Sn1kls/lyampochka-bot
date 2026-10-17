from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from poweron.adapters.db.repository import SqlRepository, create_engine, run_migrations
from poweron.core.domain.models import Address, DaySchedule
from poweron.core.ports import SourceUnavailable

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

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
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


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    run_migrations(url)
    return url


@pytest.fixture
async def repository(database_url: str) -> AsyncIterator[SqlRepository]:
    engine = create_engine(database_url)
    yield SqlRepository(engine)
    await engine.dispose()
