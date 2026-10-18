from datetime import datetime, timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.diff import data_hash
from poweron.core.domain.models import (
    Building,
    City,
    DaySchedule,
    MessageKind,
    NextEvent,
    OutboxMessage,
    ScheduleVersion,
    Street,
    Subscription,
)
from poweron.core.services.reminders import Reminders
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW, TODAY, day_schedule
from tests.services.test_schedules import kyiv

TERNOPIL = City(id=1032, name="Тернопіль", otg_name=None)
SADOVA = Street(id=9985, name="вул. Садова")
OUTAGE_AT_20 = {"20:00": "1"}  # off 20:00, power back 20:30 Kyiv


async def save(repository: SqlRepository, schedule: DaySchedule, fetched_after: int = 0) -> None:
    version = ScheduleVersion(
        schedule.cherg_gpv,
        schedule.day,
        schedule.created_at,
        data_hash(schedule.slots),
        schedule.slots,
        NOW + timedelta(minutes=fetched_after),
    )
    await repository.save_version(version, [])


async def queued(repository: SqlRepository) -> list[OutboxMessage]:
    return [queued.message for queued in await repository.due_messages(NOW, 100, 5)]


@pytest.fixture
def subscriptions(repository: SqlRepository) -> Subscriptions:
    return Subscriptions(repository)


@pytest.fixture
async def subscription(subscriptions: Subscriptions) -> Subscription:
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    return await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, Building(1, "1", "4.1"), ["4.1"], ["4.1"], NOW
    )


@pytest.fixture
def reminders(repository: SqlRepository) -> Reminders:
    return Reminders(repository, Schedules(repository))


async def test_off_reminder_fires_only_inside_the_window_and_only_once(
    repository: SqlRepository, reminders: Reminders, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=OUTAGE_AT_20))

    await reminders.tick(kyiv(TODAY, 19, 29))
    assert await queued(repository) == []

    await reminders.tick(kyiv(TODAY, 19, 30))
    await reminders.tick(kyiv(TODAY, 19, 45))
    [message] = await queued(repository)
    assert message.kind is MessageKind.REMINDER_OFF
    assert message.user_id == subscription.user_id
    assert message.payload == {
        "subscription_id": subscription.id,
        "label": "Дім",
        "cherg_gpv": "4.1",
        "queue_count": 1,
        "minutes": 30,
        "earliest": kyiv(TODAY, 20).isoformat(),
        "latest": kyiv(TODAY, 20).isoformat(),
    }
    assert message.dedupe_key == (
        f"remind:{subscription.instance_key}:4.1:{kyiv(TODAY, 20).isoformat()}:reminder_off"
    )


async def test_nothing_is_sent_once_the_event_has_started(
    repository: SqlRepository, reminders: Reminders, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=OUTAGE_AT_20))
    await reminders.tick(kyiv(TODAY, 20))
    await reminders.tick(kyiv(TODAY, 20, 10))
    assert await queued(repository) == []


async def test_on_reminder_is_separate_and_disabled_by_default(
    repository: SqlRepository,
    reminders: Reminders,
    subscriptions: Subscriptions,
    subscription: Subscription,
) -> None:
    await save(repository, day_schedule(outages=OUTAGE_AT_20))
    await reminders.tick(kyiv(TODAY, 20, 20))
    assert await queued(repository) == []

    await subscriptions.update_settings(
        subscription.user_id, subscription.id, remind_before_on_min=15
    )
    await reminders.tick(kyiv(TODAY, 20, 20))
    [message] = await queued(repository)
    assert message.kind is MessageKind.REMINDER_ON
    assert message.payload["minutes"] == 10
    assert message.payload["earliest"] == kyiv(TODAY, 20, 30).isoformat()
    assert message.dedupe_key.endswith(":reminder_on")


async def test_zero_minutes_disables_the_off_reminder(
    repository: SqlRepository,
    reminders: Reminders,
    subscriptions: Subscriptions,
    subscription: Subscription,
) -> None:
    await save(repository, day_schedule(outages=OUTAGE_AT_20))
    await subscriptions.update_settings(
        subscription.user_id, subscription.id, remind_before_off_min=0
    )
    await reminders.tick(kyiv(TODAY, 19, 45))
    assert await queued(repository) == []


async def test_a_changed_schedule_moves_the_reminder(
    repository: SqlRepository, reminders: Reminders, subscription: Subscription
) -> None:
    await save(repository, day_schedule(outages=OUTAGE_AT_20))
    await reminders.tick(kyiv(TODAY, 19, 30))
    await save(repository, day_schedule(outages={"21:00": "1"}), fetched_after=5)

    await reminders.tick(kyiv(TODAY, 19, 45))
    assert len(await queued(repository)) == 1

    await reminders.tick(kyiv(TODAY, 20, 30))
    earliest = [message.payload["earliest"] for message in await queued(repository)]
    assert earliest == [kyiv(TODAY, 20).isoformat(), kyiv(TODAY, 21).isoformat()]


async def test_only_tracked_queues_are_reminded(
    repository: SqlRepository, subscriptions: Subscriptions, reminders: Reminders
) -> None:
    user_id = await subscriptions.register("telegram", "2", "telegram", "2")
    await subscriptions.add(
        user_id, "Дім", TERNOPIL, SADOVA, Building(2, "2", "4.1"), ["2.2", "4.1"], ["4.1"], NOW
    )
    await save(repository, day_schedule(cherg_gpv="2.2", outages=OUTAGE_AT_20))
    await save(repository, day_schedule(cherg_gpv="4.1", outages=OUTAGE_AT_20))

    await reminders.tick(kyiv(TODAY, 19, 45))

    [message] = await queued(repository)
    assert message.payload["cherg_gpv"] == "4.1"


async def test_minutes_are_what_is_actually_left_rounded_up(
    repository: SqlRepository,
    reminders: Reminders,
    subscriptions: Subscriptions,
    subscription: Subscription,
) -> None:
    await save(repository, day_schedule(outages=OUTAGE_AT_20))
    await subscriptions.update_settings(
        subscription.user_id, subscription.id, remind_before_off_min=60
    )

    await reminders.tick(kyiv(TODAY, 19, 55) + timedelta(seconds=20))

    [message] = await queued(repository)
    assert message.payload["minutes"] == 5


async def test_switching_between_power_never_reminds_about_power_returning(
    repository: SqlRepository,
    reminders: Reminders,
    subscriptions: Subscriptions,
    subscription: Subscription,
) -> None:
    await save(repository, day_schedule(outages={"10:00": "10", "10:30": "10"}))
    await subscriptions.update_settings(
        subscription.user_id, subscription.id, remind_before_on_min=60
    )

    await reminders.tick(kyiv(TODAY, 9, 50))
    await reminders.tick(kyiv(TODAY, 10, 40))

    assert [message.kind for message in await queued(repository)] == [MessageKind.REMINDER_OFF]


class FailingQueue(Schedules):
    async def queue_events(self, cherg_gpv: str, now: datetime) -> list[NextEvent]:
        if cherg_gpv == "2.2":
            raise RuntimeError("broken")
        return await super().queue_events(cherg_gpv, now)


async def test_a_failing_subscription_does_not_drop_the_others(
    repository: SqlRepository, subscriptions: Subscriptions, subscription: Subscription
) -> None:
    user_id = await subscriptions.register("telegram", "2", "telegram", "2")
    broken = await subscriptions.add(
        user_id, "Дача", TERNOPIL, SADOVA, Building(2, "2", "2.2"), ["2.2"], ["2.2"], NOW
    )
    await save(repository, day_schedule(outages=OUTAGE_AT_20))

    await Reminders(repository, FailingQueue(repository)).tick(kyiv(TODAY, 19, 45))

    [message] = await queued(repository)
    assert message.payload["subscription_id"] == subscription.id != broken.id


async def test_a_queue_shared_by_subscriptions_is_computed_once_per_tick(
    repository: SqlRepository, subscriptions: Subscriptions, subscription: Subscription
) -> None:
    user_id = await subscriptions.register("telegram", "3", "telegram", "3")
    await subscriptions.add(
        user_id, "Дача", TERNOPIL, SADOVA, Building(3, "3", "4.1"), ["4.1"], ["4.1"], NOW
    )

    class Counting(Schedules):
        calls = 0

        async def queue_events(self, cherg_gpv: str, now: datetime) -> list[NextEvent]:
            Counting.calls += 1
            return await super().queue_events(cherg_gpv, now)

    await Reminders(repository, Counting(repository)).tick(kyiv(TODAY, 19, 45))

    assert Counting.calls == 1
