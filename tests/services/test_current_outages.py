import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import CurrentOutage, OutageKind, PlannedWork, Subscription
from poweron.core.domain.providers import DNEM, TOE, VOE
from poweron.core.ports import SourceUnavailable
from poweron.core.services.current_outages import CACHE_TTL, FAILURE_TTL, CurrentOutages
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
WORK = replace(OUTAGE, id=2, ends_at=NOW + timedelta(hours=5), reason="Ремонт ПЛ")


@dataclass
class FakeOutages:
    outages: list[PlannedWork] = field(default_factory=lambda: [OUTAGE])
    works: list[PlannedWork] = field(default_factory=list)
    error: Exception | None = None
    delay: float = 0.0
    calls: list[str] = field(default_factory=list)

    async def emergency_outages(self, city_id: int, street_id: int) -> list[PlannedWork]:
        return await self._answer("emergency", self.outages, street_id)

    async def planned_works(
        self, city_id: int, street_id: int, after: datetime
    ) -> list[PlannedWork]:
        return await self._answer("planned", self.works, street_id)

    async def _answer(
        self, kind: str, items: list[PlannedWork], street_id: int
    ) -> list[PlannedWork]:
        self.calls.append(kind)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return [item for item in items if item.street_id == street_id]


def outages(source: FakeOutages, timeout: float = 3.0) -> CurrentOutages:
    return CurrentOutages({TOE: source}, timeout=timeout)


@pytest.fixture
async def home(repository: SqlRepository) -> Subscription:
    return await subscribe(repository, "101", building_name="3-а")


async def test_an_outage_listing_the_building_is_shown(home: Subscription) -> None:
    assert await outages(FakeOutages()).current(home, NOW) == CurrentOutage(
        OutageKind.EMERGENCY, OUTAGE
    )


async def test_a_whole_street_outage_is_shown(home: Subscription) -> None:
    whole_street = replace(OUTAGE, building_names=())

    found = await outages(FakeOutages([whole_street])).current(home, NOW)
    assert found == CurrentOutage(OutageKind.EMERGENCY, whole_street)


async def test_an_outage_of_other_buildings_is_not_shown(repository: SqlRepository) -> None:
    neighbour = await subscribe(repository, "102", building_name="5")

    assert await outages(FakeOutages()).current(neighbour, NOW) is None


async def test_an_outage_past_its_planned_end_is_not_shown(home: Subscription) -> None:
    forgotten = replace(OUTAGE, ends_at=NOW - timedelta(minutes=1))

    assert await outages(FakeOutages([forgotten])).current(home, NOW) is None


async def test_an_outage_that_has_not_started_is_not_shown(home: Subscription) -> None:
    upcoming = replace(OUTAGE, starts_at=NOW + timedelta(minutes=30))

    assert await outages(FakeOutages([upcoming])).current(home, NOW) is None


async def test_a_planned_work_going_on_now_is_shown(home: Subscription) -> None:
    source = FakeOutages(outages=[], works=[WORK])

    assert await outages(source).current(home, NOW) == CurrentOutage(OutageKind.PLANNED, WORK)


async def test_a_planned_work_that_has_not_started_is_not_shown(home: Subscription) -> None:
    tomorrow = replace(
        WORK, starts_at=NOW + timedelta(days=1), ends_at=NOW + timedelta(days=1, hours=4)
    )

    assert await outages(FakeOutages(outages=[], works=[tomorrow])).current(home, NOW) is None


async def test_an_emergency_wins_and_planned_works_are_not_asked(home: Subscription) -> None:
    source = FakeOutages(works=[WORK])

    assert await outages(source).current(home, NOW) == CurrentOutage(OutageKind.EMERGENCY, OUTAGE)
    assert source.calls == ["emergency"]


async def test_a_failure_is_remembered_for_a_minute(home: Subscription) -> None:
    source = FakeOutages(error=SourceUnavailable("down"))
    current = outages(source)

    await current.current(home, NOW)
    await current.current(home, NOW + FAILURE_TTL - timedelta(seconds=1))
    assert source.calls == ["emergency", "planned"]

    source.error = None
    found = await current.current(home, NOW + FAILURE_TTL)
    assert found == CurrentOutage(OutageKind.EMERGENCY, OUTAGE)


async def test_regions_without_a_source_ask_nothing(home: Subscription) -> None:
    source = FakeOutages()
    lviv = replace(home, subqueues=("loe:3.1",), tracked_subqueues=("loe:3.1",))

    assert await outages(source).current(lviv, NOW) is None
    assert source.calls == []


async def test_each_region_asks_its_own_source(home: Subscription) -> None:
    ternopil, volyn = FakeOutages(outages=[]), FakeOutages()
    home_in_volyn = replace(home, subqueues=("voe:6.1",), tracked_subqueues=("voe:6.1",))

    found = await CurrentOutages({TOE: ternopil, VOE: volyn}).current(home_in_volyn, NOW)

    assert found == CurrentOutage(OutageKind.EMERGENCY, OUTAGE)
    assert ternopil.calls == []


@pytest.mark.parametrize(
    "source",
    [FakeOutages(error=SourceUnavailable("down")), FakeOutages(delay=1.0)],
    ids=["failing", "slow"],
)
async def test_a_failing_or_slow_source_means_nothing_to_show(
    home: Subscription, source: FakeOutages
) -> None:
    assert await outages(source, timeout=0.01).current(home, NOW) is None


async def test_both_requests_share_one_time_budget(home: Subscription) -> None:
    source = FakeOutages(outages=[], works=[WORK], delay=0.1)  # 0.2 s for both

    assert await outages(source, timeout=0.15).current(home, NOW) is None


async def test_answers_are_cached_per_street_and_kind_for_a_while(home: Subscription) -> None:
    source = FakeOutages(outages=[])
    current = outages(source)

    await current.current(home, NOW)
    await current.current(home, NOW + CACHE_TTL - timedelta(seconds=1))
    assert source.calls == ["emergency", "planned"]

    await current.current(home, NOW + CACHE_TTL)
    assert source.calls == ["emergency", "planned"] * 2


@dataclass
class FakeSuspensions:
    suspended_queues: set[str] = field(default_factory=set)
    delay: float = 0.0
    error: Exception | None = None

    async def suspended(self, cherg_gpv: str) -> bool:
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return cherg_gpv in self.suspended_queues


def in_dnipro(home: Subscription, *queues: str) -> Subscription:
    return replace(home, subqueues=queues, tracked_subqueues=queues)


async def test_emergency_shutdowns_of_the_operator_are_shown(home: Subscription) -> None:
    suspensions = FakeSuspensions({"dnem:17.1"})

    found = await CurrentOutages({}, suspensions={DNEM: suspensions}).current(
        in_dnipro(home, "dnem:17.1"), NOW
    )

    assert found == CurrentOutage(OutageKind.SUSPENDED, None)


async def test_a_schedule_that_applies_shows_nothing(home: Subscription) -> None:
    suspensions = FakeSuspensions({"dnem:9.1"})

    found = await CurrentOutages({}, suspensions={DNEM: suspensions}).current(
        in_dnipro(home, "dnem:17.1"), NOW
    )

    assert found is None


@pytest.mark.parametrize(
    "suspensions",
    [FakeSuspensions({"dnem:17.1"}, error=SourceUnavailable("down")), FakeSuspensions(delay=1.0)],
    ids=["failing", "slow"],
)
async def test_a_failing_or_slow_suspension_check_shows_nothing(
    home: Subscription, suspensions: FakeSuspensions
) -> None:
    current = CurrentOutages({}, timeout=0.01, suspensions={DNEM: suspensions})

    assert await current.current(in_dnipro(home, "dnem:17.1"), NOW) is None
