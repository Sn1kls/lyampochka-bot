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
    return await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )


async def first_event(
    schedules: Schedules, subscription: Subscription, now: datetime
) -> NextEvent | None:
    events = await schedules.next_event(subscription, now)
    return events[0][1] if events else None


@pytest.fixture
def schedules(repository: SqlRepository) -> Schedules:
    return Schedules(repository)


async def test_day_view_carries_intervals_and_timestamps(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"10:00": "1", "10:30": "1"}))
    [view] = await schedules.day(subscription, TODAY)
    assert view.cherg_gpv == "4.1"
    assert view.day == TODAY
    assert view.published_at == NOW
    assert view.checked_at == CHECKED_AT
    outage_spans = [(i.start, i.end) for i in view.intervals if i.state is SlotState.OFF]
    assert outage_spans == [(kyiv(TODAY, 10), kyiv(TODAY, 11))]


async def test_day_without_a_version_is_none(
    schedules: Schedules, subscription: Subscription
) -> None:
    assert await schedules.day(subscription, TOMORROW) == []


async def test_next_event_within_today(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1", "20:30": "1"}))
    assert await first_event(schedules, subscription, kyiv(TODAY, 18)) == NextEvent(
        False, kyiv(TODAY, 20), kyiv(TODAY, 20)
    )
    assert await first_event(schedules, subscription, kyiv(TODAY, 20, 15)) == NextEvent(
        True, kyiv(TODAY, 21), kyiv(TODAY, 21)
    )


async def test_next_event_is_strictly_after_now(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1"}))
    event = await first_event(schedules, subscription, kyiv(TODAY, 20))
    assert event == NextEvent(True, kyiv(TODAY, 20, 30), kyiv(TODAY, 20, 30))


async def test_next_event_continues_across_midnight(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"23:00": "1", "23:30": "1"}))
    await save(repository, day_schedule(TOMORROW, outages={"00:00": "1", "00:30": "1"}))
    event = await first_event(schedules, subscription, kyiv(TODAY, 23, 10))
    assert event == NextEvent(True, kyiv(TOMORROW, 1), kyiv(TOMORROW, 1))


async def test_next_event_ignores_changes_between_outage_states(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "1", "20:30": "10", "21:00": "1"}))
    event = await first_event(schedules, subscription, kyiv(TODAY, 20, 10))
    assert event == NextEvent(True, kyiv(TODAY, 21, 30), kyiv(TODAY, 21, 30))


async def test_next_event_warns_from_the_start_of_switching(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "10", "20:30": "1"}))
    event = await first_event(schedules, subscription, kyiv(TODAY, 18))
    assert event == NextEvent(False, kyiv(TODAY, 20), kyiv(TODAY, 20, 30))


async def test_next_event_is_none_without_data_or_flip(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    assert await first_event(schedules, subscription, NOW) is None
    await save(repository, day_schedule())
    assert await first_event(schedules, subscription, NOW) is None


async def test_next_event_uses_tomorrow_when_today_is_missing(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(TOMORROW, outages={"00:00": "1", "00:30": "1"}))
    event = await first_event(schedules, subscription, kyiv(TODAY, 22))
    assert event == NextEvent(False, kyiv(TOMORROW, 0), kyiv(TOMORROW, 0))


async def test_unknown_slot_inside_power_is_not_an_event(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "?"}))
    assert await first_event(schedules, subscription, kyiv(TODAY, 18)) is None


SWITCHING_AROUND_OUTAGE = {
    "10:30": "10",
    **{f"{hour}:{minute}": "1" for hour in (11, 12, 13) for minute in ("00", "30")},
    "14:00": "10",
}


async def test_off_window_runs_from_switching_to_the_guaranteed_outage(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=SWITCHING_AROUND_OUTAGE))
    event = await first_event(schedules, subscription, kyiv(TODAY, 9))
    assert event == NextEvent(False, kyiv(TODAY, 10, 30), kyiv(TODAY, 11))


async def test_on_window_runs_from_switching_to_the_guaranteed_power(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=SWITCHING_AROUND_OUTAGE))
    event = await first_event(schedules, subscription, kyiv(TODAY, 12))
    assert event == NextEvent(True, kyiv(TODAY, 14), kyiv(TODAY, 14, 30))


async def test_on_window_starts_now_when_inside_the_switching(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=SWITCHING_AROUND_OUTAGE))
    event = await first_event(schedules, subscription, kyiv(TODAY, 14, 10))
    assert event == NextEvent(True, kyiv(TODAY, 14, 10), kyiv(TODAY, 14, 30))


async def test_switching_only_block_has_no_guaranteed_outage(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"20:00": "10"}))
    event = await first_event(schedules, subscription, kyiv(TODAY, 18))
    assert event == NextEvent(False, kyiv(TODAY, 20), None)


async def test_switching_between_power_is_a_possible_outage_but_no_power_on_event(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"10:00": "10", "10:30": "10"}))

    events = await schedules.events(subscription, kyiv(TODAY, 9))

    assert events == [("4.1", NextEvent(False, kyiv(TODAY, 10), None))]


async def test_power_on_follows_switching_that_came_after_an_outage(
    repository: SqlRepository, schedules: Schedules, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages={"09:00": "1", "09:30": "1", "10:00": "10"}))

    event = await first_event(schedules, subscription, kyiv(TODAY, 10, 10))

    assert event == NextEvent(True, kyiv(TODAY, 10, 10), kyiv(TODAY, 10, 30))


@pytest.fixture
async def two_queues(repository: SqlRepository) -> Subscription:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", "2", "telegram", "2")
    building = Building(2, "96", "4.1")
    queues = ["2.2", "4.1"]
    return await subscriptions.add(user_id, "Дім", TERNOPIL, SADOVA, building, queues, ["4.1"], NOW)


async def test_day_shows_tracked_queues_and_any_queue_of_the_building_on_request(
    repository: SqlRepository, schedules: Schedules, two_queues: Subscription
) -> None:
    await save(repository, day_schedule(cherg_gpv="2.2"))
    await save(repository, day_schedule(cherg_gpv="4.1"))
    await save(repository, day_schedule(cherg_gpv="9.9"))

    assert [view.cherg_gpv for view in await schedules.day(two_queues, TODAY)] == ["4.1"]
    assert [view.cherg_gpv for view in await schedules.day(two_queues, TODAY, "2.2")] == ["2.2"]
    assert await schedules.day(two_queues, TODAY, "9.9") == []


async def test_next_event_is_per_tracked_queue_that_has_one(
    repository: SqlRepository, schedules: Schedules, two_queues: Subscription
) -> None:
    await save(repository, day_schedule(cherg_gpv="2.2", outages={"20:00": "1"}))
    await save(repository, day_schedule(cherg_gpv="4.1", outages={"21:00": "1"}))

    events = await schedules.next_event(two_queues, kyiv(TODAY, 18))

    assert events == [("4.1", NextEvent(False, kyiv(TODAY, 21), kyiv(TODAY, 21)))]


async def test_events_list_every_change_of_both_days_ordered_by_earliest(
    repository: SqlRepository, schedules: Schedules
) -> None:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", "3", "telegram", "3")
    building = Building(3, "3", "4.1")
    both = await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, building, ["2.2", "4.1"], ["2.2", "4.1"], NOW
    )
    await save(repository, day_schedule(cherg_gpv="2.2", outages={"19:00": "1"}))
    await save(repository, day_schedule(cherg_gpv="4.1", outages={"20:00": "1"}))
    await save(repository, day_schedule(TOMORROW, cherg_gpv="4.1", outages={"01:00": "1"}))

    events = await schedules.events(both, kyiv(TODAY, 18))

    assert events == [
        ("2.2", NextEvent(False, kyiv(TODAY, 19), kyiv(TODAY, 19))),
        ("2.2", NextEvent(True, kyiv(TODAY, 19, 30), kyiv(TODAY, 19, 30))),
        ("4.1", NextEvent(False, kyiv(TODAY, 20), kyiv(TODAY, 20))),
        ("4.1", NextEvent(True, kyiv(TODAY, 20, 30), kyiv(TODAY, 20, 30))),
        ("4.1", NextEvent(False, kyiv(TOMORROW, 1), kyiv(TOMORROW, 1))),
        ("4.1", NextEvent(True, kyiv(TOMORROW, 1, 30), kyiv(TOMORROW, 1, 30))),
    ]
    assert await schedules.next_event(both, kyiv(TODAY, 18)) == [
        ("2.2", events[0][1]),
        ("4.1", events[2][1]),
    ]
