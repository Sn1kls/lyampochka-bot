from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import (
    Building,
    City,
    MessageKind,
    OutboxMessage,
    PlannedWork,
    Street,
    Subscription,
)
from poweron.core.ports import SourceUnavailable
from poweron.core.services.planned_works import PlannedWorks
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW

TERNOPIL = City(id=1032, name="Тернопіль", otg_name=None)
SADOVA = Street(id=9985, name="вул. Садова")
STUSA = Street(id=10057, name="вул. Стуса")
LATER = NOW + timedelta(days=2)
WORK = PlannedWork(
    id=7,
    street_id=SADOVA.id,
    starts_at=datetime(2026, 10, 20, 5, 30, tzinfo=UTC),
    ends_at=datetime(2026, 10, 20, 14, 30, tzinfo=UTC),
    reason="Ремонт ПЛ",
    building_names=("1", "3-А"),
)


@dataclass
class FakeWorks:
    works: dict[int, list[PlannedWork]] = field(default_factory=dict)
    failing: set[int] = field(default_factory=set)
    calls: list[tuple[int, int, datetime]] = field(default_factory=list)

    async def planned_works(
        self, city_id: int, street_id: int, after: datetime
    ) -> list[PlannedWork]:
        self.calls.append((city_id, street_id, after))
        if street_id in self.failing:
            raise SourceUnavailable("down")
        return self.works.get(street_id, [])


async def subscribe(
    repository: SqlRepository,
    external_id: str,
    building_name: str = "1",
    street: Street = SADOVA,
    label: str = "Дім",
) -> Subscription:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", external_id, "telegram", external_id)
    building = Building(1, building_name, "4.1")
    return await subscriptions.add(
        user_id, label, TERNOPIL, street, building, ["4.1"], ["4.1"], NOW
    )


async def messages(repository: SqlRepository) -> list[OutboxMessage]:
    return [queued.message for queued in await repository.due_messages(LATER, 100, 5)]


@pytest.fixture
def source() -> FakeWorks:
    return FakeWorks({SADOVA.id: [WORK]})


@pytest.fixture
def planned_works(repository: SqlRepository, source: FakeWorks) -> PlannedWorks:
    return PlannedWorks(repository, source)


async def test_a_listed_building_gets_one_message(
    repository: SqlRepository, planned_works: PlannedWorks
) -> None:
    home = await subscribe(repository, "1")

    await planned_works.check(NOW)
    sent = await messages(repository)

    assert len(sent) == 1
    assert sent[0].kind is MessageKind.PLANNED_WORK
    assert sent[0].user_id == home.user_id
    assert sent[0].payload == {
        "subscription_id": home.id,
        "label": "Дім",
        "starts_at": "2026-10-20T05:30:00+00:00",
        "ends_at": "2026-10-20T14:30:00+00:00",
        "reason": "Ремонт ПЛ",
    }


async def test_an_unlisted_building_gets_nothing(
    repository: SqlRepository, planned_works: PlannedWorks
) -> None:
    await subscribe(repository, "1", building_name="2")

    await planned_works.check(NOW)

    assert await messages(repository) == []


async def test_building_names_are_compared_after_normalisation(
    repository: SqlRepository, planned_works: PlannedWorks
) -> None:
    await subscribe(repository, "1", building_name="3-a")  # Latin "a" for Cyrillic "а"

    await planned_works.check(NOW)

    assert len(await messages(repository)) == 1


async def test_a_work_without_buildings_covers_the_whole_street(
    repository: SqlRepository, source: FakeWorks, planned_works: PlannedWorks
) -> None:
    source.works[SADOVA.id] = [replace(WORK, building_names=())]
    await subscribe(repository, "1", building_name="2")

    await planned_works.check(NOW)

    assert len(await messages(repository)) == 1


async def test_updates_switched_off_skip_the_subscription(
    repository: SqlRepository, planned_works: PlannedWorks
) -> None:
    home = await subscribe(repository, "1")
    await Subscriptions(repository).update_settings(home.user_id, home.id, notify_on_update=False)

    await planned_works.check(NOW)

    assert await messages(repository) == []


async def test_a_rescheduled_work_is_announced_again(
    repository: SqlRepository, source: FakeWorks, planned_works: PlannedWorks
) -> None:
    await subscribe(repository, "1")
    await planned_works.check(NOW)
    source.works[SADOVA.id] = [replace(WORK, ends_at=WORK.ends_at + timedelta(hours=2))]

    await planned_works.check(NOW)

    assert len(await messages(repository)) == 2


async def test_repeated_checks_do_not_duplicate(
    repository: SqlRepository, planned_works: PlannedWorks
) -> None:
    await subscribe(repository, "1")

    await planned_works.check(NOW)
    await planned_works.check(NOW + timedelta(hours=1))

    assert len(await messages(repository)) == 1


async def test_one_source_call_per_street(
    repository: SqlRepository, source: FakeWorks, planned_works: PlannedWorks
) -> None:
    await subscribe(repository, "1")
    await subscribe(repository, "2", building_name="3-А")
    await subscribe(repository, "3", street=STUSA)

    await planned_works.check(NOW)

    assert sorted(call[:2] for call in source.calls) == [(1032, SADOVA.id), (1032, STUSA.id)]
    assert all(call[2] == NOW for call in source.calls)
    assert len(await messages(repository)) == 2


async def test_a_failing_street_does_not_stop_the_others(
    repository: SqlRepository, source: FakeWorks, planned_works: PlannedWorks
) -> None:
    source.failing.add(STUSA.id)
    await subscribe(repository, "1", street=STUSA)
    await subscribe(repository, "2")

    await planned_works.check(NOW)

    assert len(await messages(repository)) == 1
