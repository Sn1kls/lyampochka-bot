from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import (
    Building,
    City,
    MessageKind,
    OutboxMessage,
    Street,
    Subscription,
)
from poweron.core.ports import SourceUnavailable
from poweron.core.services.groups import GroupResolver
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW

TERNOPIL = City(id=1032, name="Тернопіль", otg_name=None)
SADOVA = Street(id=9985, name="вул. Садова")
LATER = NOW + timedelta(days=2)


@dataclass
class FakeBuildings:
    queues: dict[str, list[str]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        self.calls.append(building_name)
        if building_name in self.failing:
            raise SourceUnavailable("down")
        return self.queues.get(building_name, [])


async def subscribe(
    repository: SqlRepository,
    external_id: str,
    queues: list[str],
    tracked: list[str],
    building_name: str = "96",
) -> Subscription:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", external_id, "telegram", external_id)
    building = Building(1, building_name, queues[0])
    return await subscriptions.add(user_id, "Дім", TERNOPIL, SADOVA, building, queues, tracked, NOW)


async def current(repository: SqlRepository, subscription: Subscription) -> Subscription:
    found = await Subscriptions(repository).get(subscription.user_id, subscription.id)
    assert found is not None
    return found


async def messages(repository: SqlRepository) -> list[OutboxMessage]:
    return [queued.message for queued in await repository.due_messages(LATER, 100, 5)]


@pytest.fixture
def buildings() -> FakeBuildings:
    return FakeBuildings()


@pytest.fixture
def resolver(repository: SqlRepository, buildings: FakeBuildings) -> GroupResolver:
    return GroupResolver(repository, buildings)


async def test_unchanged_queues_only_record_the_check(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    home = await subscribe(repository, "1", ["2.2", "4.1"], ["4.1"])
    buildings.queues["96"] = ["4.1", "2.2"]

    await resolver.resolve(LATER)

    assert await current(repository, home) == home
    assert await messages(repository) == []
    assert await repository.stale_subscriptions(LATER) == []


async def test_a_checked_subscription_is_not_checked_again_within_a_day(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    await subscribe(repository, "1", ["4.1"], ["4.1"])
    buildings.queues["96"] = ["4.1"]

    await resolver.resolve(LATER)
    await resolver.resolve(LATER + timedelta(hours=23))
    assert buildings.calls == ["96"]

    await resolver.resolve(LATER + timedelta(hours=25))
    assert buildings.calls == ["96", "96"]


async def test_changed_queues_are_replaced_and_announced_once(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    home = await subscribe(repository, "1", ["2.2", "4.1"], ["4.1"])
    buildings.queues["96"] = ["4.1", "5.2"]

    await resolver.resolve(LATER)
    await resolver.resolve(LATER + timedelta(days=2))

    updated = await current(repository, home)
    assert set(updated.subqueues) == {"4.1", "5.2"}
    assert updated.tracked_subqueues == ("4.1",)
    [message] = await messages(repository)
    assert message.kind is MessageKind.SUBQUEUES_CHANGED
    assert message.user_id == home.user_id
    assert message.payload == {
        "subscription_id": home.id,
        "label": "Дім",
        "previous": ["2.2", "4.1"],
        "current": ["4.1", "5.2"],
        "tracked": ["4.1"],
    }


async def test_new_queues_are_tracked_only_if_all_were_tracked(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    everything = await subscribe(repository, "1", ["2.2", "4.1"], ["2.2", "4.1"], "1")
    selective = await subscribe(repository, "2", ["2.2", "4.1"], ["4.1"], "2")
    buildings.queues = {"1": ["2.2", "4.1", "5.2"], "2": ["2.2", "4.1", "5.2"]}

    await resolver.resolve(LATER)

    assert set((await current(repository, everything)).tracked_subqueues) == {"2.2", "4.1", "5.2"}
    assert (await current(repository, selective)).tracked_subqueues == ("4.1",)


async def test_all_queues_become_tracked_when_no_tracked_one_survives(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    home = await subscribe(repository, "1", ["2.2", "4.1"], ["4.1"])
    buildings.queues["96"] = ["2.2", "5.2"]

    await resolver.resolve(LATER)

    updated = await current(repository, home)
    assert set(updated.tracked_subqueues) == {"2.2", "5.2"}
    [message] = await messages(repository)
    assert message.payload["tracked"] == ["2.2", "5.2"]


async def test_one_source_call_per_building(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    await subscribe(repository, "1", ["4.1"], ["4.1"], "96")
    await subscribe(repository, "2", ["4.1"], ["4.1"], "96")
    await subscribe(repository, "3", ["4.1"], ["4.1"], "97")
    buildings.queues = {"96": ["4.1"], "97": ["4.1"]}

    await resolver.resolve(LATER)

    assert sorted(buildings.calls) == ["96", "97"]


async def test_a_source_error_leaves_the_subscription_unchecked(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    home = await subscribe(repository, "1", ["4.1"], ["4.1"], "96")
    other = await subscribe(repository, "2", ["4.1"], ["4.1"], "97")
    buildings.failing = {"96"}
    buildings.queues["97"] = ["4.1"]

    await resolver.resolve(LATER)

    assert [stale.id for stale in await repository.stale_subscriptions(LATER)] == [home.id]
    assert await current(repository, other) == other
    assert await messages(repository) == []


async def test_an_empty_answer_keeps_the_stored_queues(
    repository: SqlRepository, buildings: FakeBuildings, resolver: GroupResolver
) -> None:
    home = await subscribe(repository, "1", ["2.2", "4.1"], ["4.1"])
    buildings.queues["96"] = []

    await resolver.resolve(LATER)

    assert await current(repository, home) == home
    assert await messages(repository) == []
    assert await repository.stale_subscriptions(LATER) == []
