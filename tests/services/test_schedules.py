from datetime import UTC, date, datetime, timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.diff import data_hash
from poweron.core.domain.models import (
    Building,
    City,
    DaySchedule,
    NextEvent,
    ScheduleVersion,
    SlotState,
    Street,
)
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW, TODAY, TOMORROW, day_schedule

TERNOPIL = City(id=1032, name="Тернопіль", otg_name=None)
SADOVA = Street(id=9985, name="вул. Садова")
CHECKED_AT = NOW + timedelta(minutes=1)


def kyiv(day: date, hour: int, minute: int = 0) -> datetime:
    """Kyiv is UTC+3 on the test dates."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - timedelta(hours=3)


async def save(repository: SqlRepository, schedule: DaySchedule) -> None:
    version = ScheduleVersion(
        schedule.cherg_gpv,
        schedule.day,
        schedule.created_at,
        data_hash(schedule.slots),
        schedule.slots,
        CHECKED_AT,
    )
    await repository.save_version(version, [])


@pytest.fixture
async def user_id(repository: SqlRepository) -> int:
    return await Subscriptions(repository).register("telegram", "1", "telegram", "1")


@pytest.fixture
async def subscription_id(repository: SqlRepository, user_id: int) -> int:
    subscription = await Subscriptions(repository).add(
        user_id, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), NOW
    )
    return subscription.id


@pytest.fixture
def schedules(repository: SqlRepository) -> Schedules:
    return Schedules(repository)


async def test_day_view_carries_intervals_and_timestamps(
    repository: SqlRepository, schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    await save(repository, day_schedule(outages={"10:00": "1", "10:30": "1"}))
    view = await schedules.day(user_id, subscription_id, TODAY)
    assert view is not None
    assert view.day == TODAY
    assert view.published_at == NOW
    assert view.checked_at == CHECKED_AT
    outage_spans = [(i.start, i.end) for i in view.intervals if i.state is SlotState.OFF]
    assert outage_spans == [(kyiv(TODAY, 10), kyiv(TODAY, 11))]


async def test_day_without_a_version_is_none(
    schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    assert await schedules.day(user_id, subscription_id, TOMORROW) is None


async def test_other_users_subscription_is_invisible(
    repository: SqlRepository, schedules: Schedules, subscription_id: int
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1"}))
    stranger = await Subscriptions(repository).register("telegram", "2", "telegram", "2")
    assert await schedules.day(stranger, subscription_id, TODAY) is None
    assert await schedules.next_event(stranger, subscription_id, kyiv(TODAY, 18)) is None


async def test_next_event_within_today(
    repository: SqlRepository, schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1", "20:30": "1"}))
    assert await schedules.next_event(user_id, subscription_id, kyiv(TODAY, 18)) == NextEvent(
        kyiv(TODAY, 20), power_on=False
    )
    assert await schedules.next_event(user_id, subscription_id, kyiv(TODAY, 20, 15)) == NextEvent(
        kyiv(TODAY, 21), power_on=True
    )


async def test_next_event_is_strictly_after_now(
    repository: SqlRepository, schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1"}))
    event = await schedules.next_event(user_id, subscription_id, kyiv(TODAY, 20))
    assert event == NextEvent(kyiv(TODAY, 20, 30), power_on=True)


async def test_next_event_continues_across_midnight(
    repository: SqlRepository, schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    await save(repository, day_schedule(outages={"23:00": "1", "23:30": "1"}))
    await save(repository, day_schedule(TOMORROW, outages={"00:00": "1", "00:30": "1"}))
    event = await schedules.next_event(user_id, subscription_id, kyiv(TODAY, 23, 10))
    assert event == NextEvent(kyiv(TOMORROW, 1), power_on=True)


async def test_next_event_ignores_changes_between_outage_states(
    repository: SqlRepository, schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1", "20:30": "10", "21:00": "1"}))
    event = await schedules.next_event(user_id, subscription_id, kyiv(TODAY, 20, 10))
    assert event == NextEvent(kyiv(TODAY, 21, 30), power_on=True)


async def test_next_event_is_none_without_data_or_flip(
    repository: SqlRepository, schedules: Schedules, user_id: int, subscription_id: int
) -> None:
    assert await schedules.next_event(user_id, subscription_id, NOW) is None
    await save(repository, day_schedule())
    assert await schedules.next_event(user_id, subscription_id, NOW) is None
