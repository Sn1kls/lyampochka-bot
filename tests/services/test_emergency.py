import asyncio
from dataclasses import dataclass, field, replace
from datetime import timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import PlannedWork, Subscription
from poweron.core.ports import SourceUnavailable
from poweron.core.services.emergency import CACHE_TTL, FAILURE_TTL, EmergencyOutages
from tests.services.conftest import NOW
from tests.services.test_planned_works import SADOVA, subscribe

OUTAGE = PlannedWork(
    id=1,
    street_id=SADOVA.id,
    starts_at=NOW - timedelta(hours=1),
    ends_at=NOW + timedelta(hours=2),
    reason="Пошкодження КЛ",
    building_names=("1", "3-А"),
)


@dataclass
class FakeOutages:
    outages: list[PlannedWork] = field(default_factory=lambda: [OUTAGE])
    error: Exception | None = None
    delay: float = 0.0
    calls: int = 0

    async def emergency_outages(self, city_id: int, street_id: int) -> list[PlannedWork]:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return [outage for outage in self.outages if outage.street_id == street_id]


@pytest.fixture
async def home(repository: SqlRepository) -> Subscription:
    return await subscribe(repository, "101", building_name="3-а")


async def test_an_outage_listing_the_building_is_shown(home: Subscription) -> None:
    assert await EmergencyOutages(FakeOutages()).current(home, NOW) == OUTAGE


async def test_a_whole_street_outage_is_shown(home: Subscription) -> None:
    whole_street = replace(OUTAGE, building_names=())

    assert await EmergencyOutages(FakeOutages([whole_street])).current(home, NOW) == whole_street


async def test_an_outage_of_other_buildings_is_not_shown(repository: SqlRepository) -> None:
    neighbour = await subscribe(repository, "102", building_name="5")

    assert await EmergencyOutages(FakeOutages()).current(neighbour, NOW) is None


async def test_an_outage_past_its_planned_end_is_not_shown(home: Subscription) -> None:
    forgotten = replace(OUTAGE, ends_at=NOW - timedelta(minutes=1))

    assert await EmergencyOutages(FakeOutages([forgotten])).current(home, NOW) is None


async def test_an_outage_that_has_not_started_is_not_shown(home: Subscription) -> None:
    upcoming = replace(OUTAGE, starts_at=NOW + timedelta(minutes=30))

    assert await EmergencyOutages(FakeOutages([upcoming])).current(home, NOW) is None


async def test_a_failure_is_remembered_for_a_minute(home: Subscription) -> None:
    source = FakeOutages(error=SourceUnavailable("down"))
    emergency = EmergencyOutages(source)

    await emergency.current(home, NOW)
    await emergency.current(home, NOW + FAILURE_TTL - timedelta(seconds=1))
    assert source.calls == 1

    source.error = None
    assert await emergency.current(home, NOW + FAILURE_TTL) == OUTAGE


async def test_other_regions_do_not_ask_the_source(home: Subscription) -> None:
    source = FakeOutages()
    volyn = replace(home, subqueues=("voe:6.1",), tracked_subqueues=("voe:6.1",))

    assert await EmergencyOutages(source).current(volyn, NOW) is None
    assert source.calls == 0


@pytest.mark.parametrize(
    "source",
    [FakeOutages(error=SourceUnavailable("down")), FakeOutages(delay=1.0)],
    ids=["failing", "slow"],
)
async def test_a_failing_or_slow_source_means_nothing_to_show(
    home: Subscription, source: FakeOutages
) -> None:
    assert await EmergencyOutages(source, timeout=0.01).current(home, NOW) is None


async def test_answers_are_cached_per_street_for_a_while(home: Subscription) -> None:
    source = FakeOutages()
    emergency = EmergencyOutages(source)

    await emergency.current(home, NOW)
    await emergency.current(home, NOW + CACHE_TTL - timedelta(seconds=1))
    assert source.calls == 1

    await emergency.current(home, NOW + CACHE_TTL)
    assert source.calls == 2
