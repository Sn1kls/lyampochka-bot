from datetime import date, datetime, timedelta

from poweron.adapters.db.repository import SqlRepository
from poweron.core.services.polling import Polling
from poweron.core.services.status import Status
from tests.services.conftest import NOW, TODAY, FakeSource, day_schedule, subscribe

POLL_INTERVAL = timedelta(minutes=5)


async def subqueue_status(repository: SqlRepository) -> tuple[datetime | None, date | None]:
    [subqueue] = (await Status(repository, "1.0", POLL_INTERVAL).report()).subqueues
    return subqueue.polled_at, subqueue.latest_schedule_day


async def test_a_poll_without_schedules_still_counts_as_a_poll(repository: SqlRepository) -> None:
    await subscribe(repository)
    polling = Polling(repository, FakeSource())

    await polling.poll(NOW)
    await polling.poll(NOW + POLL_INTERVAL)

    assert await subqueue_status(repository) == (NOW + POLL_INTERVAL, None)


async def test_the_last_schedule_day_stays_while_polls_go_on(repository: SqlRepository) -> None:
    await subscribe(repository)
    source = FakeSource(schedules={"4.1": [day_schedule()]})
    await Polling(repository, source).poll(NOW)

    source.schedules = {}
    await Polling(repository, source).poll(NOW + POLL_INTERVAL)

    assert await subqueue_status(repository) == (NOW + POLL_INTERVAL, TODAY)


async def test_a_failed_fetch_is_not_a_poll(repository: SqlRepository) -> None:
    await subscribe(repository)

    await Polling(repository, FakeSource(failing={"4.1"})).poll(NOW)

    assert await subqueue_status(repository) == (None, None)
