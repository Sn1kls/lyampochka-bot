"""Pretend the operator changed today's schedule, to check the push end to end.

Run while the worker (or `all`) is running and after it has polled at least once: it
stores a version with the next hour's slot flipped for every subscribed subqueue, and
the worker's next dispatch sends the push. The next real poll restores the real schedule
(and announces that as an update too).
"""

import asyncio
from datetime import UTC, datetime, timedelta

from poweron.adapters.db.repository import SqlRepository, create_engine
from poweron.config import Settings
from poweron.core.domain.models import KYIV, Address, DaySchedule
from poweron.core.services.polling import Polling


class FlippedTodaySource:
    def __init__(self, repository: SqlRepository) -> None:
        self._repository = repository

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        now = datetime.now(KYIV)
        version = await self._repository.latest_version(cherg_gpv, now.date())
        if version is None:
            return []
        slot = f"{now + timedelta(hours=1):%H}:00"
        flipped = "0" if version.slots.get(slot) == "1" else "1"
        slots = version.slots | {slot: flipped}
        return [DaySchedule(cherg_gpv, now.date(), version.created_at, slots)]


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = create_engine(settings.database_url)
    repository = SqlRepository(engine)
    await Polling(repository, FlippedTodaySource(repository)).poll(datetime.now(UTC))
    await engine.dispose()
    print("flipped schedule stored; the worker sends the push within a few seconds")


if __name__ == "__main__":
    asyncio.run(main())
