from datetime import datetime, timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import Building, City, Street
from poweron.core.ports import DeliveryTargetGone
from poweron.core.services.notifications import Notifications
from poweron.core.services.polling import Polling
from poweron.core.services.subscriptions import NoScheduleForAddress, Subscriptions
from tests.services.conftest import NOW, TODAY, TOMORROW, FakeNotifier, FakeSource, day_schedule

TERNOPIL = City(id=1032, name="Тернопіль", otg_name="Тернопільська")
SADOVA = Street(id=9985, name="вул. Садова")


async def subscribe(
    repository: SqlRepository,
    chat_id: str,
    cherg_gpv: str = "4.1",
    at: datetime = NOW - timedelta(hours=1),
) -> None:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", chat_id, "telegram", chat_id)
    building = Building(id=int(chat_id), name="1", cherg_gpv=cherg_gpv)
    await subscriptions.add(user_id, "Дім", TERNOPIL, SADOVA, building, at)


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()


async def cycle(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier, now=NOW
) -> None:
    await Polling(repository, source).poll(now)
    await Notifications(repository, {"telegram": notifier}).dispatch(now)


async def test_new_version_reaches_each_subscriber_exactly_once(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    await subscribe(repository, "102")
    await subscribe(repository, "103", cherg_gpv="1.2")

    source.schedules = {
        "4.1": [day_schedule(outages={"11:00": "1"})],
        "1.2": [day_schedule(cherg_gpv="1.2")],
    }
    await cycle(repository, source, notifier)
    assert notifier.sent == []  # the first load is not an update

    source.schedules["4.1"] = [day_schedule(outages={"12:00": "1"})]
    await cycle(repository, source, notifier)
    await cycle(repository, source, notifier, NOW + timedelta(minutes=5))
    await Notifications(repository, {"telegram": notifier}).dispatch(NOW + timedelta(hours=1))

    assert sorted(address for address, _, _ in notifier.sent) == ["101", "102"]
    _, kind, payload = notifier.sent[0]
    assert kind == "schedule_updated"
    assert payload["cherg_gpv"] == "4.1"
    assert payload["label"] == "Дім"
    assert [interval["start"] for interval in payload["removed"]] == ["2026-10-17T08:00:00+00:00"]


async def test_published_tomorrow_is_announced(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    source.schedules = {"4.1": [day_schedule()]}
    await cycle(repository, source, notifier)

    source.schedules["4.1"].append(day_schedule(TOMORROW, {"09:00": "1"}))
    await cycle(repository, source, notifier)

    [(_, _, payload)] = notifier.sent
    assert payload["day"] == TOMORROW.isoformat()
    assert payload["previous"] is None


async def test_new_publication_time_alone_is_silent(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    source.schedules = {"4.1": [day_schedule(outages={"11:00": "1"})]}
    await cycle(repository, source, notifier)

    later = NOW + timedelta(hours=1)
    source.schedules = {"4.1": [day_schedule(outages={"11:00": "1"}, created_at=later)]}
    await cycle(repository, source, notifier, later)

    assert notifier.sent == []


async def test_returning_to_an_earlier_version_is_announced(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    for minutes, outage in enumerate(["11:00", "12:00", "11:00"]):
        source.schedules = {"4.1": [day_schedule(outages={outage: "1"})]}
        await cycle(repository, source, notifier, NOW + timedelta(minutes=minutes))

    assert len(notifier.sent) == 2


async def test_failing_source_does_not_stop_other_subqueues(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101", cherg_gpv="1.2")
    await subscribe(repository, "102")
    source.schedules = {"4.1": [day_schedule()]}
    source.failing = {"1.2"}

    await Polling(repository, source).poll(NOW)

    assert await repository.latest_version("4.1", TODAY) is not None


async def test_failed_delivery_is_retried_later(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    source.schedules = {"4.1": [day_schedule()]}
    await cycle(repository, source, notifier)
    source.schedules = {"4.1": [day_schedule(outages={"11:00": "1"})]}
    notifier.errors = [RuntimeError("telegram is down")]

    await cycle(repository, source, notifier)
    notifications = Notifications(repository, {"telegram": notifier})
    await notifications.dispatch(NOW + timedelta(seconds=1))
    assert notifier.sent == []

    await notifications.dispatch(NOW + timedelta(minutes=5))
    assert len(notifier.sent) == 1


async def test_blocked_target_is_deactivated(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    source.schedules = {"4.1": [day_schedule()]}
    await cycle(repository, source, notifier)
    notifier.errors = [DeliveryTargetGone("bot was blocked")]

    source.schedules = {"4.1": [day_schedule(outages={"11:00": "1"})]}
    await cycle(repository, source, notifier)

    user_id = 1
    assert await repository.delivery_targets(user_id) == []
    assert await repository.due_messages(NOW + timedelta(days=1), 10, 5) == []


async def test_address_without_schedule_cannot_be_subscribed(repository: SqlRepository) -> None:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", "101", "telegram", "101")
    building = Building(id=350657, name="23", cherg_gpv=None)

    with pytest.raises(NoScheduleForAddress):
        await subscriptions.add(user_id, "Дім", TERNOPIL, SADOVA, building, NOW)


async def test_registering_twice_returns_the_same_user(repository: SqlRepository) -> None:
    subscriptions = Subscriptions(repository)
    first = await subscriptions.register("telegram", "101", "telegram", "101")
    assert await subscriptions.register("telegram", "101", "telegram", "101") == first


async def test_new_subscriber_to_an_abandoned_subqueue_gets_no_stale_update(
    repository: SqlRepository, source: FakeSource, notifier: FakeNotifier
) -> None:
    await subscribe(repository, "101")
    source.schedules = {"4.1": [day_schedule(outages={"11:00": "1"})]}
    await cycle(repository, source, notifier)
    assert await Subscriptions(repository).remove(user_id=1, subscription_id=1)

    week_later = NOW + timedelta(days=7)
    await subscribe(repository, "102", at=week_later)
    source.schedules = {"4.1": [day_schedule(outages={"12:00": "1"})]}
    await cycle(repository, source, notifier, week_later)
    assert notifier.sent == []

    source.schedules = {"4.1": [day_schedule(outages={"13:00": "1"})]}
    await cycle(repository, source, notifier, week_later + timedelta(minutes=5))
    assert [address for address, _, _ in notifier.sent] == ["102"]
