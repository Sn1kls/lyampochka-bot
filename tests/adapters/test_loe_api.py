from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx
import pytest
import respx

from poweron.adapters.loe_api.client import LoeClient
from poweron.adapters.loe_api.schedule import parse_schedule
from poweron.core.domain.models import KYIV, Address, City, Street
from poweron.core.ports import ApiSchemaError, SourceUnavailable
from tests.conftest import load_fixture

TODAY_ITEM = load_fixture("loe_menu_item_today.json")
EMPTY_ITEM = load_fixture("loe_menu_item_tomorrow.json")
TODAY_HTML = TODAY_ITEM["rawHtml"]
TODAY_URL = "https://api.loe.lviv.ua/api/menu_items/238"
TOMORROW_URL = "https://api.loe.lviv.ua/api/menu_items/256"
ADDRESS = Address(city_id=693, street_id=31831, building_name="3")
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=KYIV)
POWER_API = "https://power-api.loe.lviv.ua/api"
RYNOK_ACCOUNTS = load_fixture("loe_pw_accounts_rynok.json")
GROUPS = [f"{queue}.{half}" for queue in range(1, 7) for half in (1, 2)]


def clock_time(index: int) -> str:
    return f"{index // 2:02d}:{index % 2 * 30:02d}"


def blocks(codes: str) -> list[tuple[str, str]]:
    """OFF stretches as ("HH:MM", "HH:MM") pairs."""
    found = []
    start = None
    for index, code in enumerate(codes + "0"):
        if code == "1" and start is None:
            start = index
        if code == "0" and start is not None:
            found.append((clock_time(start), clock_time(index)))
            start = None
    return found


def schedule_html(*group_lines: str, day: str = "24.11.2026") -> str:
    lines = [
        f"<p><b>Графік погодинних відключень на {day}</b></p>",
        "<p><b>Інформація станом на 19:07 23.11.2026</b></p>",
        *(f"<p>{line}</p>" for line in group_lines),
    ]
    return "<div>" + "\n".join(lines) + "</div>"


def all_groups(**lines: str) -> list[str]:
    """Every group has power, except the given ones ("1_1"="... з 10:00 до 12:00.")."""
    return [
        f"Група {group}. {lines.get(group.replace('.', '_'), 'Електроенергія є.')}"
        for group in GROUPS
    ]


def test_parses_the_published_text() -> None:
    schedule = parse_schedule(TODAY_HTML)

    assert schedule.day == date(2026, 11, 23)
    assert schedule.published_at == datetime(2026, 11, 23, 8, 8, tzinfo=KYIV)
    assert sorted(schedule.groups) == GROUPS
    assert blocks(schedule.groups["1.1"]) == [("16:30", "20:00")]
    assert blocks(schedule.groups["2.1"]) == []
    assert blocks(schedule.groups["5.2"]) == [("20:00", "22:30")]
    assert blocks(schedule.groups["6.1"]) == [("22:30", "24:00")]
    assert all(len(codes) == 48 for codes in schedule.groups.values())


def test_several_outages_of_a_group() -> None:
    html = schedule_html(
        *all_groups(
            **{"3_2": "Електроенергії немає з 00:00 до 02:30, з 09:00 до 12:00, з 21:30 до 24:00."}
        )
    )

    groups = parse_schedule(html).groups

    assert blocks(groups["3.2"]) == [("00:00", "02:30"), ("09:00", "12:00"), ("21:30", "24:00")]


def test_an_empty_item_has_no_schedule() -> None:
    assert parse_schedule("") is None


@pytest.mark.parametrize(
    "group_lines",
    [
        all_groups()[:-1],  # a group is missing
        [*all_groups(), "Група 1.1. Електроенергія є."],  # a group twice
        all_groups(**{"1_1": "Електроенергії немає з 00:00 до 00:00."}),
        all_groups(**{"1_1": "Електроенергії немає з 12:00 до 10:00."}),
        all_groups(**{"1_1": "Електроенергії немає з 10:15 до 11:00."}),
        all_groups(**{"1_1": "Електроенергії немає з 10:00 до 25:00."}),
        all_groups(**{"1_1": "Електроенергії немає орієнтовно з 10:00."}),
    ],
)
def test_an_unexpected_text_is_a_schema_error(group_lines: list[str]) -> None:
    with pytest.raises(ApiSchemaError):
        parse_schedule(schedule_html(*group_lines))


def test_a_text_without_its_day_is_a_schema_error() -> None:
    with pytest.raises(ApiSchemaError):
        parse_schedule("<p>Група 1.1. Електроенергія є.</p>")


def test_a_note_next_to_the_groups_is_ignored() -> None:
    html = schedule_html(*all_groups(), "<b>Увага! Графік може змінюватися.</b>")

    assert len(parse_schedule(html).groups) == 12


class FakeClock:
    def __init__(self) -> None:
        self.monotonic_now = 1000.0

    def monotonic(self) -> float:
        return self.monotonic_now

    async def sleep(self, seconds: float) -> None:
        self.monotonic_now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(clock: FakeClock) -> AsyncIterator[LoeClient]:
    loe_client = LoeClient(now=lambda: NOW, monotonic=clock.monotonic, sleep=clock.sleep)
    yield loe_client
    await loe_client.aclose()


def item(raw_html: str) -> dict[str, Any]:
    return EMPTY_ITEM | {"rawHtml": raw_html}


def mock_items(today: dict[str, Any], tomorrow: dict[str, Any]) -> tuple[respx.Route, respx.Route]:
    return respx.get(TODAY_URL).respond(json=today), respx.get(TOMORROW_URL).respond(json=tomorrow)


@respx.mock
async def test_todays_schedule_of_a_subqueue(client: LoeClient) -> None:
    mock_items(TODAY_ITEM, EMPTY_ITEM)

    [schedule] = await client.fetch_schedules(ADDRESS, "loe:1.1")

    assert schedule.cherg_gpv == "loe:1.1"
    assert schedule.day == date(2026, 11, 23)
    assert schedule.created_at == datetime(2026, 11, 23, 8, 8, tzinfo=KYIV)
    assert list(schedule.slots)[:3] == ["00:00", "00:30", "01:00"]
    assert blocks("".join(schedule.slots.values())) == [("16:30", "20:00")]


@respx.mock
async def test_tomorrow_comes_after_today(client: LoeClient) -> None:
    tomorrow = schedule_html(*all_groups(**{"1_1": "Електроенергії немає з 08:00 до 10:00."}))
    mock_items(TODAY_ITEM, item(tomorrow))

    result = await client.fetch_schedules(ADDRESS, "loe:1.1")

    assert [schedule.day for schedule in result] == [date(2026, 11, 23), date(2026, 11, 24)]
    assert blocks("".join(result[1].slots.values())) == [("08:00", "10:00")]


@respx.mock
async def test_a_day_other_than_today_or_tomorrow_is_ignored(client: LoeClient) -> None:
    mock_items(TODAY_ITEM, item(schedule_html(*all_groups(), day="12.08.2024")))

    result = await client.fetch_schedules(ADDRESS, "loe:1.1")

    assert [schedule.day for schedule in result] == [date(2026, 11, 23)]


@respx.mock
async def test_the_newer_text_wins_when_both_items_carry_the_same_day(client: LoeClient) -> None:
    newer = schedule_html(*all_groups(), day="23.11.2026")  # published 19:07, after 08:08
    mock_items(TODAY_ITEM, item(newer))

    [schedule] = await client.fetch_schedules(ADDRESS, "loe:1.1")

    assert blocks("".join(schedule.slots.values())) == []


@respx.mock
async def test_a_pass_over_subqueues_costs_two_requests(client: LoeClient) -> None:
    today, tomorrow = mock_items(TODAY_ITEM, EMPTY_ITEM)

    for subqueue in ("loe:1.1", "loe:3.2", "loe:6.2"):
        await client.fetch_schedules(ADDRESS, subqueue)

    assert (today.call_count, tomorrow.call_count) == (1, 1)


@respx.mock
async def test_the_items_are_fetched_again_after_a_minute(
    client: LoeClient, clock: FakeClock
) -> None:
    today, _ = mock_items(TODAY_ITEM, EMPTY_ITEM)

    await client.fetch_schedules(ADDRESS, "loe:1.1")
    clock.monotonic_now += 61
    await client.fetch_schedules(ADDRESS, "loe:1.1")

    assert today.call_count == 2


@respx.mock
async def test_an_unknown_subqueue_asks_nothing(client: LoeClient) -> None:
    today, _ = mock_items(TODAY_ITEM, EMPTY_ITEM)

    assert await client.fetch_schedules(ADDRESS, "loe:7.1") == []
    assert today.call_count == 0


@respx.mock
async def test_a_failed_pass_is_not_retried_by_every_subqueue(client: LoeClient) -> None:
    today = respx.get(TODAY_URL).respond(503)

    for subqueue in ("loe:1.1", "loe:1.2"):
        with pytest.raises(SourceUnavailable):
            await client.fetch_schedules(ADDRESS, subqueue)

    assert today.call_count == 3


@respx.mock
async def test_an_item_of_an_unexpected_shape_is_a_schema_error(client: LoeClient) -> None:
    mock_items({"rawHtml": None}, EMPTY_ITEM)

    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(ADDRESS, "loe:1.1")


def account(building: str, queue: str) -> dict[str, Any]:
    return RYNOK_ACCOUNTS[0] | {"buildingName": building, "chergGpv": queue}


@respx.mock
@pytest.mark.parametrize("wrap", [lambda rows: rows, lambda rows: {"hydra:member": rows}])
async def test_cities_carry_their_hromada(client: LoeClient, wrap: Any) -> None:
    route = respx.get(f"{POWER_API}/pw_cities").respond(
        json=wrap(
            [
                {
                    "@id": "/api/pw_cities/1",
                    "id": 1,
                    "name": "Броди",
                    "codeOtg": "UA46040010000033885",
                    "otg": {"@id": "/api/pw_otgs/9", "name": "Бродівська"},
                }
            ]
        )
    )

    assert await client.cities() == [City(id=1, name="Броди", otg_name="Бродівська")]
    assert route.calls.last.request.url.params["pagination"] == "false"


@respx.mock
async def test_streets_of_a_city(client: LoeClient) -> None:
    route = respx.get(f"{POWER_API}/pw_streets").respond(
        json=[{"city": "/api/pw_cities/693", "id": 31831, "name": "Ринок. пл."}]
    )

    assert await client.streets(693) == [Street(id=31831, name="Ринок. пл.")]
    assert route.calls.last.request.url.params["city.id"] == "693"


@respx.mock
async def test_buildings_are_gathered_from_account_rows(client: LoeClient) -> None:
    route = respx.get(f"{POWER_API}/pw_accounts").respond(json=RYNOK_ACCOUNTS)

    buildings = {
        building.name: building.cherg_gpv for building in await client.buildings(693, 31831)
    }

    # «Не входить» next to a queue counts as that queue; a nameless row is dropped.
    assert buildings == {"1": "loe:4.1", "10": "loe:4.1", "13": "loe:4.1", "14": "loe:1.1"}
    params = route.calls.last.request.url.params
    assert (params["city.id"], params["street.id"]) == ("693", "31831")


@respx.mock
async def test_a_building_outside_the_schedules_has_no_queue(client: LoeClient) -> None:
    respx.get(f"{POWER_API}/pw_accounts").respond(json=[account("5", "Не входить")])

    [building] = await client.buildings(693, 31831)

    assert building.cherg_gpv is None
    assert await client.building_subqueues(693, 31831, "5") == []


@respx.mock
async def test_a_building_in_two_queues_lists_both(client: LoeClient) -> None:
    respx.get(f"{POWER_API}/pw_accounts").respond(
        json=[account("9", "4.1"), account("9", "3.1"), account("9", "4.1"), account("8", "2.2")]
    )

    assert await client.building_subqueues(693, 31831, "9") == ["loe:3.1", "loe:4.1"]


@respx.mock
async def test_building_ids_do_not_depend_on_row_order(client: LoeClient, clock: FakeClock) -> None:
    rows = [account("9", "4.1"), account("8", "2.2")]
    respx.get(f"{POWER_API}/pw_accounts").mock(
        side_effect=[httpx.Response(200, json=rows), httpx.Response(200, json=rows[::-1])]
    )

    first = await client.buildings(693, 31831)
    clock.monotonic_now += 61
    second = await client.buildings(693, 31831)

    assert sorted(first, key=lambda building: building.name) == sorted(
        second, key=lambda building: building.name
    )
    assert len({building.id for building in first}) == 2


@respx.mock
async def test_adding_an_address_asks_for_the_street_once(client: LoeClient) -> None:
    route = respx.get(f"{POWER_API}/pw_accounts").respond(json=RYNOK_ACCOUNTS)

    await client.buildings(693, 31831)
    await client.building_subqueues(693, 31831, "14")

    assert route.call_count == 1


@respx.mock
async def test_account_rows_of_an_unexpected_shape_are_a_schema_error(client: LoeClient) -> None:
    respx.get(f"{POWER_API}/pw_accounts").respond(json=[{"buildingName": 14}])

    with pytest.raises(ApiSchemaError):
        await client.buildings(693, 31831)
