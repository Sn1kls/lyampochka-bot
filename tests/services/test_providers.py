from datetime import timedelta

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import (
    Address,
    AlertKind,
    Building,
    City,
    DaySchedule,
    Street,
)
from poweron.core.domain.providers import (
    TOE,
    VOE,
    VOE_CATALOG_IMPORTED_KEY,
    plain_subqueue,
    provider_of,
    scoped_subqueue,
)
from poweron.core.services.alerts import Alerts
from poweron.core.services.catalog_age import STALE_AFTER, VoeCatalogAge
from poweron.core.services.groups import RECHECK_AFTER, SubqueueChecker
from poweron.core.services.planned_works import PlannedWorks
from poweron.core.services.polling import SchedulesByProvider
from poweron.core.services.subscriptions import Subscriptions
from tests.fakes import FakeAlerter
from tests.services.conftest import NOW

KIVERTSI = City(id=7, name="Ківерці", otg_name="Луцький р-н")
NEZALEZHNOSTI = Street(id=8, name="Незалежності")


def test_subqueue_keys_are_scoped_by_provider() -> None:
    assert scoped_subqueue(TOE, "4.1") == "4.1"
    assert scoped_subqueue(VOE, "6.1") == "voe:6.1"
    assert (provider_of("4.1"), plain_subqueue("4.1")) == (TOE, "4.1")
    assert (provider_of("voe:6.1"), plain_subqueue("voe:6.1")) == (VOE, "6.1")


class RecordingSource:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        self.requested.append(cherg_gpv)
        return []


async def test_each_subqueue_goes_to_its_providers_source() -> None:
    ternopil, volyn = RecordingSource(), RecordingSource()
    router = SchedulesByProvider({TOE: ternopil, VOE: volyn})
    address = Address(1, 2, "3")

    await router.fetch_schedules(address, "4.1")
    await router.fetch_schedules(address, "voe:6.1")

    assert (ternopil.requested, volyn.requested) == (["4.1"], ["voe:6.1"])


async def subscribe_in_volyn(repository: SqlRepository) -> None:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", "1", "telegram", "1")
    building = Building(9, "19", "voe:6.1")
    await subscriptions.add(
        user_id, "Дім", KIVERTSI, NEZALEZHNOSTI, building, ["voe:6.1"], ["voe:6.1"], NOW
    )


class Buildings:
    def __init__(self, queues: list[str]) -> None:
        self.queues = queues
        self.calls = 0

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        self.calls += 1
        return self.queues


async def test_the_subqueue_recheck_asks_the_providers_catalogue(
    repository: SqlRepository,
) -> None:
    await subscribe_in_volyn(repository)
    ternopil, volyn = Buildings(["4.1"]), Buildings(["voe:5.2"])

    await SubqueueChecker(repository, {TOE: ternopil, VOE: volyn}).check(NOW + RECHECK_AFTER * 2)

    [subscription] = await repository.all_subscriptions()
    assert (ternopil.calls, volyn.calls) == (0, 1)
    assert subscription.subqueues == ("voe:5.2",)
    assert subscription.provider == VOE


async def test_a_provider_without_a_catalogue_is_not_rechecked(repository: SqlRepository) -> None:
    await subscribe_in_volyn(repository)
    ternopil = Buildings(["4.1"])

    await SubqueueChecker(repository, {TOE: ternopil}).check(NOW + RECHECK_AFTER * 2)

    [subscription] = await repository.all_subscriptions()
    assert ternopil.calls == 0
    assert subscription.subqueues == ("voe:6.1",)


class NoWorks:
    def __init__(self) -> None:
        self.calls = 0

    async def planned_works(self, city_id: int, street_id: int, after: object) -> list[object]:
        self.calls += 1
        return []


async def test_planned_works_are_only_asked_for_ternopil(repository: SqlRepository) -> None:
    await subscribe_in_volyn(repository)
    source = NoWorks()

    await PlannedWorks(repository, source).check(NOW)  # type: ignore[arg-type]

    assert source.calls == 0


async def test_a_missing_or_old_volyn_import_alerts_the_admin(repository: SqlRepository) -> None:
    alerter = FakeAlerter()
    age = VoeCatalogAge(repository, Alerts(alerter, interval=timedelta(0)))

    await age.check(NOW)
    await repository.store_catalog(VOE_CATALOG_IMPORTED_KEY, {"buildings": 1}, NOW)
    await age.check(NOW + STALE_AFTER)
    await age.check(NOW + STALE_AFTER + timedelta(days=1))

    assert [kind for kind, _ in alerter.alerts] == [
        AlertKind.VOE_CATALOG_STALE,
        AlertKind.VOE_CATALOG_STALE,
    ]
