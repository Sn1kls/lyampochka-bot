"""Pretend the operator changed the schedule, to check the push end to end.

Run while the worker (or `all`) is running and after it has polled at least once: it
stores a version with the slot of the next hour flipped for every subscribed subqueue, and
the worker's next dispatch sends the push. The next real poll restores the real schedule
(and announces that as an update too).
"""

import asyncio
from datetime import UTC, datetime, timedelta

from poweron.adapters.db.repository import SqlRepository, create_engine
from poweron.config import Settings
from poweron.core.domain.models import KYIV, Address, DaySchedule
from poweron.core.services.polling import Polling


class FlippedNextHourSource:
    def __init__(self, repository: SqlRepository) -> None:
        self._repository = repository
        self.changed = 0

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        slot_time = datetime.now(KYIV) + timedelta(hours=1)
        day = slot_time.date()  # after 23:00 the slot belongs to tomorrow
        version = await self._repository.latest_version(cherg_gpv, day)
        if version is None:
            return []
        slot = f"{slot_time:%H}:00"
        flipped = "0" if version.slots.get(slot) == "1" else "1"
        self.changed += 1
        return [DaySchedule(cherg_gpv, day, version.created_at, version.slots | {slot: flipped})]


async def main() -> None:
    settings = Settings(bot_token="unused")  # type: ignore[arg-type]
    engine = create_engine(settings.database_url)
    repository = SqlRepository(engine)
    source = FlippedNextHourSource(repository)
    await Polling(repository, source).poll(datetime.now(UTC))
    await engine.dispose()
    if source.changed:
        print(f"flipped the schedule of {source.changed} subqueue(s); the worker sends the push")
    else:
        print("nothing changed: the worker has not polled yet, run it first and retry")


if __name__ == "__main__":
    asyncio.run(main())
