from collections.abc import AsyncIterator
from datetime import date, datetime

import pytest
import respx

from poweron.adapters.yasno_api.client import PAIR_BASE, YasnoClient
from poweron.core.domain.models import KYIV, Address
from poweron.core.ports import ApiSchemaError, SourceUnavailable
from tests.conftest import load_fixture
from tests.fakes import FakeClock, blocks

API = "https://app.yasno.ua/api/blackout-service/public/shutdowns"
DNEM_URL = f"{API}/regions/3/dsos/301/planned-outages"
CEK_URL = f"{API}/regions/3/dsos/303/planned-outages"
DNEM_SCHEDULE = load_fixture("yasno_planned_outages_301.json")
CEK_SCHEDULE = load_fixture("yasno_planned_outages_303.json")
ADDRESS = Address(city_id=6, street_id=2078, building_name="1")
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=KYIV)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(clock: FakeClock) -> AsyncIterator[YasnoClient]:
    yasno_client = YasnoClient(now=lambda: NOW, monotonic=clock.monotonic, sleep=clock.sleep)
    yield yasno_client
    await yasno_client.aclose()


@respx.mock
async def test_todays_schedule_of_a_dnem_group(client: YasnoClient) -> None:
    respx.get(DNEM_URL).respond(json=DNEM_SCHEDULE)

    [schedule] = await client.fetch_schedules(ADDRESS, "dnem:17.1")

    assert schedule.cherg_gpv == "dnem:17.1"
    assert schedule.day == date(2026, 11, 27)
    assert schedule.created_at == datetime(2026, 11, 27, 11, 30, 2, tzinfo=KYIV)
    assert list(schedule.slots)[:2] == ["00:00", "00:30"]
    assert blocks("".join(schedule.slots.values())) == [
        ("01:00", "08:00"),
        ("10:00", "16:30"),
        ("19:00", "24:00"),
    ]


@respx.mock
async def test_a_day_without_outages_is_all_on(client: YasnoClient) -> None:
    respx.get(CEK_URL).respond(json=CEK_SCHEDULE)

    today, tomorrow = await client.fetch_schedules(ADDRESS, "cek:1.2")

    assert blocks("".join(today.slots.values())) == [("06:00", "13:00"), ("16:30", "23:30")]
    assert tomorrow.day == date(2026, 11, 28)
    assert set(tomorrow.slots.values()) == {"0"}


@respx.mock
async def test_a_pass_over_groups_costs_one_request_per_operator(client: YasnoClient) -> None:
    dnem = respx.get(DNEM_URL).respond(json=DNEM_SCHEDULE)
    cek = respx.get(CEK_URL).respond(json=CEK_SCHEDULE)

    for group in ("1.1", "17.1", "18.1"):
        await client.fetch_schedules(ADDRESS, f"dnem:{group}")
    await client.fetch_schedules(ADDRESS, "cek:1.1")

    assert dnem.call_count == 1
    assert cek.call_count == 1


@respx.mock
async def test_an_unknown_group_has_no_schedule(client: YasnoClient) -> None:
    respx.get(DNEM_URL).respond(json=DNEM_SCHEDULE)

    assert await client.fetch_schedules(ADDRESS, "dnem:1.2") == []


def with_today(**today: object) -> dict[str, object]:
    group = DNEM_SCHEDULE["17.1"]
    return {"17.1": group | {"today": group["today"] | today}}


@respx.mock
async def test_emergency_shutdowns_keep_the_last_schedule(client: YasnoClient) -> None:
    respx.get(DNEM_URL).respond(json=with_today(status="EmergencyShutdowns", slots=[]))

    assert await client.fetch_schedules(ADDRESS, "dnem:17.1") == []


@pytest.mark.parametrize(
    "today",
    [
        {"slots": [{"start": 0, "end": 45, "type": "Definite"}]},  # off the half-hour grid
        {"slots": [{"start": 600, "end": 600, "type": "Definite"}]},  # empty
        {"slots": [{"start": 0, "end": 1500, "type": "Definite"}]},  # past midnight
        {"slots": [{"start": 0, "end": 60, "type": "Possible"}]},  # an unknown state
        {"status": "SomethingNew"},
    ],
)
@respx.mock
async def test_an_unexpected_day_is_a_schema_error(
    client: YasnoClient, today: dict[str, object]
) -> None:
    respx.get(DNEM_URL).respond(json=with_today(**today))

    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(ADDRESS, "dnem:17.1")


@respx.mock
async def test_a_challenge_page_is_a_schema_error(client: YasnoClient) -> None:
    respx.get(DNEM_URL).respond(html="<html><script src='/_Incapsula_Resource'></script></html>")

    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(ADDRESS, "dnem:17.1")


ADDRESSES = f"{API}/addresses/v2"
DNEM_CITIES = [
    {"id": 6, "value": "м. Дніпро"},
    {"id": 8, "value": "м. Кам’янське"},
    {"id": 9, "value": "м. Кам'янське"},
]
CEK_CITIES = load_fixture("yasno_cities_303.json")


def mock_cities() -> None:
    respx.get(f"{ADDRESSES}/cities", params={"dsoId": "301"}).respond(json=DNEM_CITIES)
    respx.get(f"{ADDRESSES}/cities", params={"dsoId": "303"}).respond(json=CEK_CITIES)


@respx.mock
async def test_a_city_of_both_operators_is_one_city(client: YasnoClient) -> None:
    mock_cities()

    cities = {city.name: city for city in await client.cities()}

    assert "Дніпро" not in cities  # CEK's spelling of «м. Дніпро»
    assert cities["м. Дніпро"].id == 6 * PAIR_BASE + 6
    assert cities["Жовті Води"].id == 8  # CEK only
    # DnEM lists Kamianske twice; one operator's duplicates are kept as they are.
    assert [city.id for city in await client.cities() if "Кам" in city.name] == [
        8 * PAIR_BASE,
        9 * PAIR_BASE,
    ]


DNIPRO = 6 * PAIR_BASE + 6
ZHOVTI_VODY = 8  # CEK only


def mock_streets(provider_id: str, streets: list[dict[str, object]]) -> respx.Route:
    return respx.get(f"{ADDRESSES}/streets", params={"dsoId": provider_id}).respond(json=streets)


@respx.mock
async def test_a_street_of_both_operators_is_one_street(client: YasnoClient) -> None:
    dnem = mock_streets("301", [{"id": 5, "value": "вул. Шевченка"}])
    mock_streets(
        "303", [{"id": 235, "value": "вул. Шевченка "}, {"id": 7, "value": "пл. Шевченка"}]
    )

    streets = await client.search_streets(DNIPRO, "Шевч")

    assert [(street.id, street.name) for street in streets] == [
        (5 * PAIR_BASE + 235, "вул. Шевченка"),
        (7, "пл. Шевченка"),
    ]
    assert dict(dnem.calls.last.request.url.params) == {
        "regionId": "3",
        "dsoId": "301",
        "cityId": "6",
        "query": "шевч",
    }


@respx.mock
async def test_a_city_of_one_operator_asks_only_that_operator(client: YasnoClient) -> None:
    dnem = mock_streets("301", [])
    cek = mock_streets("303", [{"id": 1, "value": "вул. Козацька"}])

    await client.search_streets(ZHOVTI_VODY, "Коза")

    assert not dnem.called
    assert cek.call_count == 1


@respx.mock
async def test_a_street_query_under_three_letters_asks_nothing(client: YasnoClient) -> None:
    route = mock_streets("301", [])

    assert await client.search_streets(DNIPRO, " Ше ") == []
    assert not route.called


STREET = 2608 * PAIR_BASE + 147  # вул. Братів Горобців: DnEM 2608, CEK 147
DNEM_HOUSES = [
    {"id": 11, "value": "1 ввод 1"},
    {"id": 12, "value": "1 ввод 2"},
    {"id": 13, "value": "10"},
]
CEK_HOUSES = [{"id": 21, "value": "10"}, {"id": 22, "value": "12"}]


def mock_houses() -> tuple[respx.Route, respx.Route]:
    return (
        respx.get(f"{ADDRESSES}/houses", params={"dsoId": "301"}).respond(json=DNEM_HOUSES),
        respx.get(f"{ADDRESSES}/houses", params={"dsoId": "303"}).respond(json=CEK_HOUSES),
    )


def mock_group(house_id: int, group: int, subgroup: int) -> None:
    respx.get(f"{ADDRESSES}/group", params={"houseId": str(house_id)}).respond(
        json={"group": group, "subgroup": subgroup}
    )


@respx.mock
async def test_a_house_number_finds_houses_of_both_operators(client: YasnoClient) -> None:
    dnem, _ = mock_houses()

    buildings = await client.search_buildings(DNIPRO, STREET, "1")

    assert [building.name for building in buildings] == ["1", "10", "12"]  # inputs are one
    assert all(building.cherg_gpv is None for building in buildings)  # known once picked
    assert dict(dnem.calls.last.request.url.params) == {
        "regionId": "3",
        "dsoId": "301",
        "cityId": "6",
        "streetId": "2608",
        "query": "1",
    }


@respx.mock
async def test_building_ids_survive_a_new_search(client: YasnoClient) -> None:
    mock_houses()

    first = await client.search_buildings(DNIPRO, STREET, "1")
    again = await client.search_buildings(DNIPRO, STREET, "10")

    ids = {building.name: building.id for building in first}
    assert ids["10"] == {building.name: building.id for building in again}["10"]


@respx.mock
async def test_the_inputs_of_a_house_give_all_their_queues(client: YasnoClient) -> None:
    mock_houses()
    mock_group(11, 17, 1)
    mock_group(12, 9, 1)

    assert await client.building_subqueues(DNIPRO, STREET, "1") == ["dnem:17.1", "dnem:9.1"]


@respx.mock
async def test_a_house_of_both_operators_gives_both_queues(client: YasnoClient) -> None:
    mock_houses()
    mock_group(13, 17, 1)
    mock_group(21, 1, 2)

    assert await client.building_subqueues(DNIPRO, STREET, "10") == ["cek:1.2", "dnem:17.1"]


@respx.mock
async def test_a_house_gone_from_the_lists_has_no_queue(client: YasnoClient) -> None:
    mock_houses()

    assert await client.building_subqueues(DNIPRO, STREET, "99") == []


@respx.mock
async def test_emergency_shutdowns_today_suspend_the_schedule(client: YasnoClient) -> None:
    respx.get(DNEM_URL).respond(json=with_today(status="EmergencyShutdowns", slots=[]))

    assert await client.suspended("dnem:17.1")
    assert not await client.suspended("dnem:1.1")  # not in the answer


@respx.mock
async def test_a_schedule_that_applies_is_not_suspended(client: YasnoClient) -> None:
    respx.get(DNEM_URL).respond(json=DNEM_SCHEDULE)

    assert not await client.suspended("dnem:17.1")


@respx.mock
async def test_a_typed_house_and_its_queues_cost_one_house_search(client: YasnoClient) -> None:
    dnem, cek = mock_houses()
    mock_group(13, 17, 1)
    mock_group(21, 1, 2)

    await client.search_buildings(DNIPRO, STREET, "10")
    await client.building_subqueues(DNIPRO, STREET, "10")

    assert (dnem.call_count, cek.call_count) == (1, 1)


@respx.mock
async def test_emergency_shutdowns_are_reported_once_per_operator_and_day(
    clock: FakeClock,
) -> None:
    reported: list[str] = []

    async def report(details: str) -> None:
        reported.append(details)

    client = YasnoClient(
        now=lambda: NOW, monotonic=clock.monotonic, sleep=clock.sleep, on_suspended=report
    )
    suspended = with_today(status="EmergencyShutdowns", slots=[])
    respx.get(DNEM_URL).respond(json=suspended | {"9.1": suspended["17.1"]})
    try:
        await client.fetch_schedules(ADDRESS, "dnem:17.1")
        await client.fetch_schedules(ADDRESS, "dnem:9.1")
        clock.monotonic_now += 120  # the next poll
        await client.fetch_schedules(ADDRESS, "dnem:17.1")
    finally:
        await client.aclose()

    assert reported == ["dnem 2026-11-27"]


@respx.mock
async def test_latin_letters_and_a_type_prefix_are_cleaned_from_a_query(
    client: YasnoClient,
) -> None:
    dnem, _ = mock_houses()
    streets = mock_streets("301", [])
    mock_streets("303", [])

    await client.search_streets(DNIPRO, "вул. Кoрoленкa")
    await client.search_buildings(DNIPRO, STREET, " 12a ")

    assert streets.calls.last.request.url.params["query"] == "короленка"
    assert dnem.calls.last.request.url.params["query"] == "12а"


@respx.mock
async def test_an_id_too_big_for_a_pair_id_is_skipped(client: YasnoClient) -> None:
    mock_streets("301", [{"id": 1_000_000, "value": "вул. Нова"}, {"id": 5, "value": "вул. Стара"}])
    mock_streets("303", [])

    streets = await client.search_streets(DNIPRO, "вул")

    assert [street.name for street in streets] == ["вул. Стара"]


@respx.mock
async def test_a_house_missing_from_a_cut_off_answer_is_unknown(client: YasnoClient) -> None:
    others = [{"id": number, "value": f"{number}"} for number in range(100, 120)]  # 20: the cap
    respx.get(f"{ADDRESSES}/houses", params={"dsoId": "301"}).respond(json=others)
    respx.get(f"{ADDRESSES}/houses", params={"dsoId": "303"}).respond(json=[])

    with pytest.raises(SourceUnavailable):
        await client.building_subqueues(DNIPRO, STREET, "1")
