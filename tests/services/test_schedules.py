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
    Subscription,
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
async def subscription(repository: SqlRepository) -> Subscription:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    return await subscriptions.add(user_id, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), NOW)


@pytest.fixture
def schedules(repository: SqlRepository) -> Schedules:
    return Schedules(repository)


async def test_day_view_carries_intervals_and_timestamps(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"10:00": "1", "10:30": "1"}))
    view = await schedules.day(subscription, TODAY)
    assert view is not None
    assert view.day == TODAY
    assert view.published_at == NOW
    assert view.checked_at == CHECKED_AT
    outage_spans = [(i.start, i.end) for i in view.intervals if i.state is SlotState.OFF]
    assert outage_spans == [(kyiv(TODAY, 10), kyiv(TODAY, 11))]


async def test_day_without_a_version_is_none(
    schedules: Schedules, subscription: Subscription
) -> None:
    assert await schedules.day(subscription, TOMORROW) is None


async def test_next_event_within_today(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1", "20:30": "1"}))
    assert await schedules.next_event(subscription, kyiv(TODAY, 18)) == NextEvent(
        False, kyiv(TODAY, 20), kyiv(TODAY, 20)
    )
    assert await schedules.next_event(subscription, kyiv(TODAY, 20, 15)) == NextEvent(
        True, kyiv(TODAY, 21), kyiv(TODAY, 21)
    )


async def test_next_event_is_strictly_after_now(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1"}))
    event = await schedules.next_event(subscription, kyiv(TODAY, 20))
    assert event == NextEvent(True, kyiv(TODAY, 20, 30), kyiv(TODAY, 20, 30))


async def test_next_event_continues_across_midnight(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"23:00": "1", "23:30": "1"}))
    await save(repository, day_schedule(TOMORROW, outages={"00:00": "1", "00:30": "1"}))
    event = await schedules.next_event(subscription, kyiv(TODAY, 23, 10))
    assert event == NextEvent(True, kyiv(TOMORROW, 1), kyiv(TOMORROW, 1))


async def test_next_event_ignores_changes_between_outage_states(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1", "20:30": "10", "21:00": "1"}))
    event = await schedules.next_event(subscription, kyiv(TODAY, 20, 10))
    assert event == NextEvent(True, kyiv(TODAY, 21, 30), kyiv(TODAY, 21, 30))


async def test_next_event_warns_from_the_start_of_switching(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "10", "20:30": "1"}))
    event = await schedules.next_event(subscription, kyiv(TODAY, 18))
    assert event == NextEvent(False, kyiv(TODAY, 20), kyiv(TODAY, 20, 30))


async def test_next_event_is_none_without_data_or_flip(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    assert await schedules.next_event(subscription, NOW) is None
    await save(repository, day_schedule())
    assert await schedules.next_event(subscription, NOW) is None


async def test_next_event_uses_tomorrow_when_today_is_missing(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(TOMORROW, outages={"00:00": "1", "00:30": "1"}))
    event = await schedules.next_event(subscription, kyiv(TODAY, 22))
    assert event == NextEvent(False, kyiv(TOMORROW, 0), kyiv(TOMORROW, 0))


async def test_unknown_slot_inside_power_is_not_an_event(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "?"}))
    assert await schedules.next_event(subscription, kyiv(TODAY, 18)) is None


SWITCHING_AROUND_OUTAGE = {
    "10:30": "10",
    **{f"{hour}:{minute}": "1" for hour in (11, 12, 13) for minute in ("00", "30")},
    "14:00": "10",
}


async def test_off_window_runs_from_switching_to_the_guaranteed_outage(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=SWITCHING_AROUND_OUTAGE))
    event = await schedules.next_event(subscription, kyiv(TODAY, 9))
    assert event == NextEvent(False, kyiv(TODAY, 10, 30), kyiv(TODAY, 11))


async def test_on_window_runs_from_switching_to_the_guaranteed_power(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=SWITCHING_AROUND_OUTAGE))
    event = await schedules.next_event(subscription, kyiv(TODAY, 12))
    assert event == NextEvent(True, kyiv(TODAY, 14), kyiv(TODAY, 14, 30))


async def test_on_window_starts_now_when_inside_the_switching(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=SWITCHING_AROUND_OUTAGE))
    event = await schedules.next_event(subscription, kyiv(TODAY, 14, 10))
    assert event == NextEvent(True, kyiv(TODAY, 14, 10), kyiv(TODAY, 14, 30))


async def test_switching_only_block_has_no_guaranteed_outage(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "10"}))
    event = await schedules.next_event(subscription, kyiv(TODAY, 18))
    assert event == NextEvent(False, kyiv(TODAY, 20), None)
